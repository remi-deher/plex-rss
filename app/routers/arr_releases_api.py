"""Recherche interactive de releases via Sonarr/Radarr, avec mise en avant des versions francaises."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..cache import cache
from ..database import AsyncSessionLocal, get_db_async
from ..dependencies import require_admin
from ..models import MediaRequest, RequestStatus, Settings
from ..services import radarr, sonarr
from ..services.request_lifecycle import transition_request
from .arr_shared import _resolve_arr_instance

router = APIRouter(prefix="/api", tags=["arr"], dependencies=[Depends(require_admin)])
logger = logging.getLogger(__name__)

_FRENCH_LANG_NAMES = {"french", "français", "francais"}

_FRENCH_TITLE_WORDS = {"french", "truefrench", "vff", "vf", "vfi", "vfq", "multi"}

def _release_is_french(rel: dict) -> bool:
    """Heuristique VF pour une release : langue « French » déclarée ou marqueur dans le titre."""
    if any((lang or "").lower() in _FRENCH_LANG_NAMES for lang in rel.get("languages", [])):
        return True
    title = (rel.get("title") or "").lower()
    words = set(title.replace(".", " ").replace("-", " ").replace("_", " ").split())
    return bool(words & _FRENCH_TITLE_WORDS)

_RELEASES_SOFT_TTL = 20

_RELEASES_HARD_TTL = 120

async def _compute_releases(db: AsyncSession, media_type: str, arr_id: int, instance_id: Optional[int], episode_id: Optional[int]) -> list[dict]:
    arr_type = "radarr" if media_type == "movie" else "sonarr"
    inst = await _resolve_arr_instance(db, instance_id, arr_type)
    if media_type == "movie":
        releases = await radarr.get_releases(inst.url, inst.api_key, arr_id)
    else:
        releases = await sonarr.get_releases(inst.url, inst.api_key, series_id=arr_id, episode_id=episode_id)

    for rel in releases:
        rel["is_french"] = _release_is_french(rel)

    releases.sort(key=lambda r: (r["is_french"], r.get("custom_format_score", 0), r.get("seeders", 0)), reverse=True)
    return releases

class ArrGrabRequest(BaseModel):
    media_type: str  # "movie" | "show"
    guid: str
    indexer_id: int
    instance_id: Optional[int] = None
    request_id: Optional[int] = None

@router.get("/arr/releases")
async def arr_interactive_releases(
    media_type: str,
    arr_id: int,
    instance_id: Optional[int] = None,
    episode_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db_async),
):
    """Recherche interactive Sonarr/Radarr : releases déjà scorées (qualité + custom
    format + langue) avec marquage VF.

    Mis en cache tres court (stale-while-revalidate, voir cache.py) : evite de
    re-taper l'indexeur a chaque clic/rechargement rapproche sur la meme recherche,
    sans jamais retarder un premier lancement (recalcul synchrone si rien en cache).
    """
    args = (media_type, arr_id, instance_id, episode_id)
    key = f"plexarr:releases:{media_type}:{arr_id}:{instance_id}:{episode_id}"

    async def _background():
        async with AsyncSessionLocal() as fresh_db:
            return await _compute_releases(fresh_db, *args)

    return await cache.get_or_refresh(
        key, _RELEASES_SOFT_TTL, _RELEASES_HARD_TTL,
        compute_sync=lambda: _compute_releases(db, *args), compute_background=_background,
    )

@router.post("/arr/grab")
async def arr_grab_release(body: ArrGrabRequest, db: AsyncSession = Depends(get_db_async)):
    """Grab d'une release via Sonarr/Radarr."""
    arr_type = "radarr" if body.media_type == "movie" else "sonarr"
    inst = await _resolve_arr_instance(db, body.instance_id, arr_type)
    svc = radarr if body.media_type == "movie" else sonarr
    ok, msg = await svc.grab_release(inst.url, inst.api_key, body.guid, body.indexer_id)
    if not ok:
        raise HTTPException(500, msg)
    if body.request_id:
        req = (await db.execute(select(MediaRequest).filter(MediaRequest.id == body.request_id))).scalars().first()
        if req and req.status not in (RequestStatus.available,):
            await transition_request(db, req, "submitted", source=arr_type)
            await db.commit()
            from ..services.notification_policy import dispatch_transition_notification

            settings = (await db.execute(select(Settings))).scalars().first()
            await dispatch_transition_notification(settings, req, db, "submitted")
    return {"success": True, "message": msg}
