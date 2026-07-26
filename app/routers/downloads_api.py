"""Telechargements directs en cours et historique des telechargements termines."""

import asyncio
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import get_db_async
from ..dependencies import require_admin
from ..models import DownloadClient, MediaRequest
from ..utils import wrap_image_proxy
from .arr_shared import _QUEUE_CACHE_TTL, _direct_cache

router = APIRouter(prefix="/api", tags=["arr"], dependencies=[Depends(require_admin)])
logger = logging.getLogger(__name__)


@router.get("/downloads/direct")
async def direct_downloads(db: AsyncSession = Depends(get_db_async)):
    """Torrents poussés en direct-client (hors *arr), suivis via download_client_id + torrent_hash sur les demandes."""
    from ..services.download_clients import get_torrent_status

    now = time.monotonic()
    if _direct_cache["data"] is not None and now - _direct_cache["ts"] < _QUEUE_CACHE_TTL:
        return _direct_cache["data"]

    reqs = (
        await db.execute(
            select(MediaRequest).filter(
                MediaRequest.torrent_hash.isnot(None),
                MediaRequest.download_client_id.isnot(None),
            )
        )
    ).scalars().all()
    clients = {c.id: c for c in (await db.execute(select(DownloadClient))).scalars().all()}
    tracked = [(req, clients.get(req.download_client_id)) for req in reqs]
    tracked = [(req, client) for req, client in tracked if client and client.enabled]

    async def _status(req, client):
        try:
            return await get_torrent_status(
                client.client_type, client.url, client.username, client.password, req.torrent_hash
            )
        except Exception:
            return None

    statuses = await asyncio.gather(*[_status(req, client) for req, client in tracked])

    out = []
    for (req, client), st in zip(tracked, statuses):
        if not st:
            continue
        progress = round(st.get("progress") or 0, 1)
        eta = st.get("eta") or 0
        if progress >= 100 or eta <= 0:
            timeleft = "—"
        else:
            h, m = eta // 3600, (eta % 3600) // 60
            timeleft = f"{h}h {m}m" if h else f"{m}m"
        out.append(
            {
                "title": req.title + (f" ({req.year})" if req.year else ""),
                "status": "completed" if progress >= 100 else "downloading",
                "progress": progress,
                "size": None,
                "sizeleft": None,
                "timeleft": timeleft,
                "download_client": client.name,
                "indexer": None,
                "instance": client.name,
                "arr_type": "direct",
                "error": None,
                "request_id": req.id,
                "library_id": req.library_item_id,
            }
        )
    _direct_cache["data"] = out
    _direct_cache["ts"] = now
    return out

@router.get("/downloads/history")
async def downloads_history(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    media_type: Optional[str] = None,
    source: Optional[str] = None,
    db: AsyncSession = Depends(get_db_async),
):
    """Historique des téléchargements terminés (Sonarr/Radarr/Plex/torrent direct)."""
    from ..models import DownloadHistory

    q = select(DownloadHistory)
    if media_type in ("movie", "show"):
        q = q.filter(DownloadHistory.media_type == media_type)
    if source:
        q = q.filter(DownloadHistory.source == source)
    rows = (
        await db.execute(q.order_by(DownloadHistory.completed_at.desc()).offset(offset).limit(limit))
    ).scalars().all()
    return [
        {
            "id": h.id,
            "title": h.title,
            "year": h.year,
            "media_type": h.media_type,
            "source": h.source,
            "instance_name": h.instance_name,
            "poster_url": wrap_image_proxy(h.poster_url),
            "request_id": h.request_id,
            "completed_at": h.completed_at.isoformat() if h.completed_at else None,
        }
        for h in rows
    ]
