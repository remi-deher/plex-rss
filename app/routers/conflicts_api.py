"""Doublons et entrees incoherentes de la table des demandes : detection, fusion, mise en sourdine."""

import json as _json
import logging
import os as _os
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import get_db_async
from ..dependencies import require_admin
from ..models import MediaRequest, PlexUser
from ..serializers import format_datetime
from ..services.vf_cache import delete_request_episode_cache
from ..utils import now_utc_naive, wrap_image_proxy

router = APIRouter(prefix="/api", tags=["misc"])
logger = logging.getLogger(__name__)

_IGNORED_FILE = "data/ignored_conflicts.json"

def _load_ignored() -> set[str]:
    try:
        with open(_IGNORED_FILE) as f:
            return set(_json.load(f))
    except Exception:
        return set()

def _save_ignored(keys: set[str]):
    _os.makedirs("data", exist_ok=True)
    with open(_IGNORED_FILE, "w") as f:
        _json.dump(sorted(keys), f)

def _req_dict(r: MediaRequest) -> dict:
    return {
        "id": r.id,
        "title": r.title,
        "tmdb_id": r.tmdb_id,
        "tvdb_id": r.tvdb_id,
        "source": r.source,
        "status": r.status,
        "plex_user": r.plex_user,
        "plex_user_id": r.plex_user_id,
        "arr_id": r.arr_id,
        "poster_url": wrap_image_proxy(r.poster_url),
        "requested_at": format_datetime(r.requested_at),
        "available_at": format_datetime(r.available_at),
    }

async def _merge_entries(keeper: MediaRequest, dup: MediaRequest, db: AsyncSession):
    """Fusionne dup dans keeper : co-demandeurs + champs manquants."""
    extras: list[dict] = _json.loads(keeper.extra_requesters or "[]")
    existing_ids = {keeper.plex_user_id} | {e["plex_user_id"] for e in extras}
    for e in _json.loads(dup.extra_requesters or "[]"):
        if e["plex_user_id"] not in existing_ids:
            extras.append(e)
            existing_ids.add(e["plex_user_id"])
    if dup.plex_user_id not in existing_ids:
        extras.append({"plex_user_id": dup.plex_user_id, "display_name": dup.plex_user or dup.plex_user_id})

    if dup.source == "seer" and dup.tmdb_id:
        keeper.tmdb_id = dup.tmdb_id
    elif not keeper.tmdb_id and dup.tmdb_id:
        keeper.tmdb_id = dup.tmdb_id
    if not keeper.tvdb_id and dup.tvdb_id:
        keeper.tvdb_id = dup.tvdb_id
    if not keeper.poster_url and dup.poster_url:
        keeper.poster_url = dup.poster_url
    keeper.extra_requesters = _json.dumps(extras, ensure_ascii=False)
    await db.delete(dup)

@router.get("/conflicts")
async def list_conflicts(db: AsyncSession = Depends(get_db_async), _: None = Depends(require_admin)):
    """Retourne tous les conflits détectés, filtrés des ignorés."""
    ignored = _load_ignored()
    all_reqs = (await db.execute(select(MediaRequest))).scalars().all()
    known_user_ids = {u.plex_user_id for u in (await db.execute(select(PlexUser))).scalars().all()}
    now = now_utc_naive()

    tvdb_groups: dict[tuple, list[MediaRequest]] = defaultdict(list)
    for r in all_reqs:
        if r.tvdb_id:
            tvdb_groups[(r.media_type, r.tvdb_id)].append(r)

    tmdb_conflicts = []
    for (media_type, tvdb_id), rows in tvdb_groups.items():
        tmdb_ids = {r.tmdb_id for r in rows if r.tmdb_id}
        if len(tmdb_ids) <= 1:
            continue
        key = f"tmdb:{media_type}:{tvdb_id}"
        if key in ignored:
            continue
        seer_entry = next((r for r in rows if r.source == "seer"), None)
        recommended_id = seer_entry.id if seer_entry else None
        tmdb_conflicts.append(
            {
                "type": "tmdb_conflict",
                "key": key,
                "media_type": media_type,
                "tvdb_id": tvdb_id,
                "recommended_id": recommended_id,
                "entries": [_req_dict(r) for r in sorted(rows, key=lambda x: (x.source != "seer", x.id))],
            }
        )

    orphaned = []
    for r in all_reqs:
        if r.plex_user_id not in known_user_ids:
            key = f"orphan:{r.id}"
            if key in ignored:
                continue
            orphaned.append({"key": key, **_req_dict(r)})

    long_pending = []
    for r in all_reqs:
        if r.status != "pending":
            continue
        if not r.requested_at:
            continue
        age = (now - r.requested_at).days
        if age < 30:
            continue
        key = f"pending:{r.id}"
        if key in ignored:
            continue
        long_pending.append({"key": key, "age_days": age, **_req_dict(r)})

    return {
        "tmdb_conflicts": tmdb_conflicts,
        "orphaned": orphaned,
        "long_pending": long_pending,
    }

@router.post("/conflicts/resolve")
async def resolve_conflict(body: dict, db: AsyncSession = Depends(get_db_async), _: None = Depends(require_admin)):
    keep_id: int = body.get("keep_id")
    delete_ids: list[int] = body.get("delete_ids", [])
    if not keep_id or not delete_ids:
        raise HTTPException(400, "keep_id et delete_ids requis")
    keeper = await db.get(MediaRequest, keep_id)
    if not keeper:
        raise HTTPException(404, f"Entrée {keep_id} introuvable")
    for del_id in delete_ids:
        dup = await db.get(MediaRequest, del_id)
        if dup:
            await _merge_entries(keeper, dup, db)
    await db.commit()
    return {"ok": True, "kept": keep_id, "deleted": delete_ids}

@router.post("/conflicts/auto-resolve")
async def auto_resolve_conflicts(db: AsyncSession = Depends(get_db_async), _: None = Depends(require_admin)):
    """Résout automatiquement tous les conflits tmdb : garde l'entrée Seer."""
    all_reqs = (await db.execute(select(MediaRequest))).scalars().all()
    tvdb_groups: dict[tuple, list[MediaRequest]] = defaultdict(list)
    for r in all_reqs:
        if r.tvdb_id:
            tvdb_groups[(r.media_type, r.tvdb_id)].append(r)

    resolved = 0
    for (media_type, tvdb_id), rows in tvdb_groups.items():
        tmdb_ids = {r.tmdb_id for r in rows if r.tmdb_id}
        if len(tmdb_ids) <= 1:
            continue
        seer = next((r for r in rows if r.source == "seer"), None)
        keeper = seer or min(rows, key=lambda x: x.id)
        for dup in rows:
            if dup.id != keeper.id:
                await _merge_entries(keeper, dup, db)
        resolved += 1

    await db.commit()
    return {"ok": True, "resolved": resolved}

@router.post("/conflicts/ignore")
def ignore_conflict(body: dict, _: None = Depends(require_admin)):
    """Marque un conflit comme ignoré (ne réapparaîtra plus)."""
    key: str = body.get("key")
    if not key:
        raise HTTPException(400, "key requis")
    ignored = _load_ignored()
    ignored.add(key)
    _save_ignored(ignored)
    return {"ok": True}

@router.delete("/conflicts/ignore/{key:path}")
def unignore_conflict(key: str, _: None = Depends(require_admin)):
    """Retire un conflit de la liste des ignorés."""
    ignored = _load_ignored()
    ignored.discard(key)
    _save_ignored(ignored)
    return {"ok": True}

@router.delete("/conflicts/no-tmdb/{request_id}")
async def delete_no_tmdb(request_id: int, db: AsyncSession = Depends(get_db_async), _: None = Depends(require_admin)):
    req = await db.get(MediaRequest, request_id)
    if not req:
        raise HTTPException(404, "Entrée introuvable")
    if req.tmdb_id:
        raise HTTPException(400, "Cette entrée a un tmdb_id — utilisez /conflicts/resolve")
    await delete_request_episode_cache(db, req.id)
    await db.delete(req)
    await db.commit()
    return {"ok": True}

@router.delete("/conflicts/orphan/{request_id}")
async def delete_orphan(request_id: int, db: AsyncSession = Depends(get_db_async), _: None = Depends(require_admin)):
    req = await db.get(MediaRequest, request_id)
    if not req:
        raise HTTPException(404, "Entrée introuvable")
    await delete_request_episode_cache(db, req.id)
    await db.delete(req)
    await db.commit()
    return {"ok": True}
