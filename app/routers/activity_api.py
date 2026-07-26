"""API d'activité Plex en direct, historique et statistiques."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db_async
from ..dependencies import get_settings_or_404, require_admin
from ..models import Settings
from ..services.playback_activity import (
    activity_snapshot,
    collect_plex_activity,
    import_tautulli_history,
    test_tautulli,
)

router = APIRouter(prefix="/api/playback", tags=["activity"], dependencies=[Depends(require_admin)])


class TautulliImportRequest(BaseModel):
    length: int = 1000


@router.get("")
async def get_activity(days: int = Query(30, ge=1, le=3650), db: AsyncSession = Depends(get_db_async)):
    return await activity_snapshot(days, db=db)


@router.post("/refresh")
async def refresh_activity():
    try:
        await collect_plex_activity()
        return await activity_snapshot(30)
    except Exception as exc:
        raise HTTPException(502, f"Lecture des sessions Plex impossible : {exc}") from exc


@router.post("/tautulli/test")
async def test_tautulli_connection(settings: Settings = Depends(get_settings_or_404)):
    ok, message = await test_tautulli(settings.tautulli_url or "", settings.tautulli_api_key or "")
    if not ok:
        raise HTTPException(502, message)
    return {"ok": True, "message": message}


@router.post("/tautulli/import")
async def import_tautulli(data: TautulliImportRequest):
    try:
        return await import_tautulli_history(length=data.length)
    except Exception as exc:
        raise HTTPException(502, f"Import Tautulli impossible : {exc}") from exc
