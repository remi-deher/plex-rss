import json as _json
import os as _os
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_auth
from ..models import ArrInstance, MediaRequest, PlexUser, Settings, VfEpisodeStatus
from ..serializers import format_datetime
from ..utils import now_utc_naive

router = APIRouter(prefix="/api", tags=["misc"])


def _delete_vf_episode_cache(db: Session, request_id: int) -> None:
    """Purge le cache VF par Ã©pisode d'une demande supprimÃ©e (Ã©vite les lignes orphelines)."""
    db.query(VfEpisodeStatus).filter(
        VfEpisodeStatus.source_type == "request", VfEpisodeStatus.source_id == request_id
    ).delete()


@router.get("/onboarding")
def onboarding_status(db: Session = Depends(get_db), _: None = Depends(require_auth)):
    """Retourne l'Ã©tat d'avancement de la configuration initiale (checklist)."""
    s = db.query(Settings).first()
    users_count = db.query(PlexUser).count()
    has_sonarr = db.query(ArrInstance).filter(ArrInstance.arr_type == "sonarr", ArrInstance.enabled).first() is not None
    has_radarr = db.query(ArrInstance).filter(ArrInstance.arr_type == "radarr", ArrInstance.enabled).first() is not None
    steps = [
        {"id": "rss", "label": "Flux RSS Plex configurÃ©", "done": bool(s and s.plex_rss_url)},
        {"id": "sonarr", "label": "Sonarr configurÃ©", "done": has_sonarr},
        {"id": "radarr", "label": "Radarr configurÃ©", "done": has_radarr},
        {"id": "smtp", "label": "Email (SMTP) configurÃ©", "done": bool(s and s.smtp_host)},
        {"id": "users", "label": "Au moins un utilisateur dÃ©tectÃ©", "done": users_count > 0},
        {
            "id": "webhooks",
            "label": "Webhooks Sonarr/Radarr configurÃ©s",
            "done": has_sonarr or has_radarr,
            "optional": True,
        },
    ]
    return {"steps": steps, "complete": all(s["done"] for s in steps if not s.get("optional"))}


@router.post("/plex/sso/pin")
async def plex_sso_pin(request: Request, _: None = Depends(require_auth)):
    """CrÃ©e une demande de PIN Plex SSO et retourne l'URL d'authentification."""
    from ..services.plex_api import get_auth_pin

    try:
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.url.netloc)
        forward_url = f"{scheme}://{host}/settings"
        return await get_auth_pin(forward_url=forward_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur d'initialisation SSO Plex : {str(e)}")


@router.get("/plex/sso/check/{pin_id}")
async def plex_sso_check(pin_id: int, _: None = Depends(require_auth)):
    """VÃ©rifie si le PIN Plex a Ã©tÃ© validÃ© et retourne le token."""
    from ..services.plex_api import check_auth_pin

    try:
        token = await check_auth_pin(pin_id)
        return {"authenticated": bool(token), "token": token}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Conflits et Nettoyage de base de donnÃ©es
# ---------------------------------------------------------------------------

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
        "poster_url": r.poster_url,
        "requested_at": format_datetime(r.requested_at),
        "available_at": format_datetime(r.available_at),
    }


def _merge_entries(keeper: MediaRequest, dup: MediaRequest, db):
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
    db.delete(dup)


@router.get("/conflicts")
def list_conflicts(db: Session = Depends(get_db), _: None = Depends(require_auth)):
    """Retourne tous les conflits dÃ©tectÃ©s, filtrÃ©s des ignorÃ©s."""
    ignored = _load_ignored()
    all_reqs = db.query(MediaRequest).all()
    known_user_ids = {u.plex_user_id for u in db.query(PlexUser).all()}
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
def resolve_conflict(body: dict, db: Session = Depends(get_db), _: None = Depends(require_auth)):
    keep_id: int = body.get("keep_id")
    delete_ids: list[int] = body.get("delete_ids", [])
    if not keep_id or not delete_ids:
        raise HTTPException(400, "keep_id et delete_ids requis")
    keeper = db.get(MediaRequest, keep_id)
    if not keeper:
        raise HTTPException(404, f"EntrÃ©e {keep_id} introuvable")
    for del_id in delete_ids:
        dup = db.get(MediaRequest, del_id)
        if dup:
            _merge_entries(keeper, dup, db)
    db.commit()
    return {"ok": True, "kept": keep_id, "deleted": delete_ids}


@router.post("/conflicts/auto-resolve")
def auto_resolve_conflicts(db: Session = Depends(get_db), _: None = Depends(require_auth)):
    """RÃ©sout automatiquement tous les conflits tmdb : garde l'entrÃ©e Seer."""
    all_reqs = db.query(MediaRequest).all()
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
                _merge_entries(keeper, dup, db)
        resolved += 1

    db.commit()
    return {"ok": True, "resolved": resolved}


@router.post("/conflicts/ignore")
def ignore_conflict(body: dict, _: None = Depends(require_auth)):
    """Marque un conflit comme ignorÃ© (ne rÃ©apparaÃ®tra plus)."""
    key: str = body.get("key")
    if not key:
        raise HTTPException(400, "key requis")
    ignored = _load_ignored()
    ignored.add(key)
    _save_ignored(ignored)
    return {"ok": True}


@router.delete("/conflicts/ignore/{key:path}")
def unignore_conflict(key: str, _: None = Depends(require_auth)):
    """Retire un conflit de la liste des ignorÃ©s."""
    ignored = _load_ignored()
    ignored.discard(key)
    _save_ignored(ignored)
    return {"ok": True}


@router.delete("/conflicts/no-tmdb/{request_id}")
def delete_no_tmdb(request_id: int, db: Session = Depends(get_db), _: None = Depends(require_auth)):
    req = db.get(MediaRequest, request_id)
    if not req:
        raise HTTPException(404, "EntrÃ©e introuvable")
    if req.tmdb_id:
        raise HTTPException(400, "Cette entrÃ©e a un tmdb_id â€” utilisez /conflicts/resolve")
    _delete_vf_episode_cache(db, req.id)
    db.delete(req)
    db.commit()
    return {"ok": True}


@router.delete("/conflicts/orphan/{request_id}")
def delete_orphan(request_id: int, db: Session = Depends(get_db), _: None = Depends(require_auth)):
    req = db.get(MediaRequest, request_id)
    if not req:
        raise HTTPException(404, "EntrÃ©e introuvable")
    _delete_vf_episode_cache(db, req.id)
    db.delete(req)
    db.commit()
    return {"ok": True}
