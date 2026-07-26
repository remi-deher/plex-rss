"""Prowlarr : indexeurs, recherche manuelle et envoi d'une release a un client direct."""

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import get_db_async
from ..dependencies import require_admin
from ..models import ArrInstance, DownloadClient, MediaRequest, RequestStatus, Settings
from ..services import prowlarr
from ..services.download_clients import (
    add_torrent_file_to_client,
    add_torrent_to_client,
)
from ..services.request_lifecycle import transition_request
from ..utils import async_get_or_404
from .arr_shared import _resolve_arr_instance

router = APIRouter(prefix="/api", tags=["arr"], dependencies=[Depends(require_admin)])
logger = logging.getLogger(__name__)

class ProwlarrGrabRequest(BaseModel):
    guid: str
    indexer_id: int
    instance_id: int
    request_id: Optional[int] = None

class DownloadReleaseRequest(BaseModel):
    torrent_url_or_magnet: str
    client_id: int
    category: Optional[str] = None
    tags: Optional[str] = None
    request_id: Optional[int] = None

@router.get("/prowlarr/indexers")
async def get_prowlarr_indexers(
    instance_id: Optional[int] = None,
    url: Optional[str] = None,
    api_key: Optional[str] = None,
    db: AsyncSession = Depends(get_db_async),
):
    if url and api_key:
        indexers = await prowlarr.get_indexers(url, api_key)
        return [{"id": idx["id"], "name": idx["name"]} for idx in indexers]
    inst = await _resolve_arr_instance(db, instance_id, "prowlarr")
    indexers = await prowlarr.get_indexers(inst.url, inst.api_key)
    return [{"id": idx["id"], "name": idx["name"]} for idx in indexers]

@router.get("/prowlarr/{instance_id}/download-client-status")
async def get_prowlarr_download_client_status(instance_id: int, db: AsyncSession = Depends(get_db_async)):
    """Indique si Prowlarr a lui-même un client de téléchargement actif."""
    inst = await async_get_or_404(db, ArrInstance, instance_id, "Instance Prowlarr introuvable")
    clients = await prowlarr.get_download_clients(inst.url, inst.api_key)
    return {"has_client": any(c.get("enable") for c in clients)}

@router.post("/prowlarr/grab")
async def prowlarr_grab_release(body: ProwlarrGrabRequest, db: AsyncSession = Depends(get_db_async)):
    """Grab d'une release via le client de téléchargement configuré dans Prowlarr lui-même."""
    inst = await async_get_or_404(db, ArrInstance, body.instance_id, "Instance Prowlarr introuvable")
    ok, msg = await prowlarr.grab(inst.url, inst.api_key, body.guid, body.indexer_id)
    if not ok:
        raise HTTPException(500, msg)
    if body.request_id:
        req = (await db.execute(select(MediaRequest).filter(MediaRequest.id == body.request_id))).scalars().first()
        if req and req.status not in (RequestStatus.available,):
            await transition_request(db, req, "submitted", source="prowlarr_manual")
            await db.commit()
            from ..services.notification_policy import dispatch_transition_notification

            settings = (await db.execute(select(Settings))).scalars().first()
            await dispatch_transition_notification(settings, req, db, "submitted")
    return {"success": True, "message": msg}

_search_cache: dict[tuple[str, str, int | None], tuple[float, list[dict]]] = {}

@router.get("/search")
async def search_prowlarr(
    query: str,
    media_type: str = "movie",
    instance_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db_async),
):
    """Effectue une recherche via Prowlarr avec un cache en mémoire de 60 minutes."""
    cache_key = (query, media_type, instance_id)
    now = time.time()

    if cache_key in _search_cache:
        cached_time, cached_results = _search_cache[cache_key]
        if now - cached_time < 3600:  # 60 minutes
            return cached_results

    try:
        inst = await _resolve_arr_instance(db, instance_id, "prowlarr")
    except HTTPException:
        raise HTTPException(400, "Aucune instance Prowlarr configurée et active")

    results = await prowlarr.search(
        url=inst.url,
        api_key=inst.api_key,
        query=query,
        media_type=media_type,
        indexer_ids=None,
    )

    formatted_results = []
    for r in results:
        formatted_results.append(
            {
                "title": r.get("title"),
                "size": r.get("size"),
                "seeders": r.get("seeders", 0),
                "leechers": r.get("leechers", 0),
                "guid": r.get("guid"),
                "indexerId": r.get("indexerId"),
                "downloadUrl": r.get("downloadUrl") or r.get("magnetUrl"),
                "indexer": r.get("indexer"),
                "protocol": r.get("protocol"),
                "publishDate": r.get("publishDate"),
                "infoUrl": r.get("infoUrl"),
            }
        )

    formatted_results.sort(key=lambda x: x["seeders"], reverse=True)
    _search_cache[cache_key] = (now, formatted_results)
    return formatted_results

@router.post("/download")
async def download_release(body: DownloadReleaseRequest, db: AsyncSession = Depends(get_db_async)):
    client = await async_get_or_404(db, DownloadClient, body.client_id, "Client de téléchargement introuvable")

    ok, msg, info_hash = await add_torrent_to_client(
        client_type=client.client_type,
        url=client.url,
        username=client.username,
        password=client.password,
        torrent_url_or_magnet=body.torrent_url_or_magnet,
        category=body.category or client.category,
        tags=body.tags or client.tags,
    )

    if not ok:
        raise HTTPException(status_code=500, detail=msg)

    if body.request_id and info_hash:
        req = (await db.execute(select(MediaRequest).filter(MediaRequest.id == body.request_id))).scalars().first()
        if req:
            req.download_client_id = client.id
            req.torrent_hash = info_hash
            await transition_request(db, req, "submitted", source="torrent_manual")
            await db.commit()
            from ..services.notification_policy import dispatch_transition_notification

            settings = (await db.execute(select(Settings))).scalars().first()
            await dispatch_transition_notification(settings, req, db, "submitted")

    return {"success": True, "message": msg, "info_hash": info_hash}

@router.post("/download/file")
async def download_torrent_file(
    file: UploadFile,
    client_id: int,
    category: Optional[str] = None,
    tags: Optional[str] = None,
    request_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db_async),
):
    """Upload d'un fichier .torrent directement vers un client de téléchargement."""
    client = await async_get_or_404(db, DownloadClient, client_id, "Client de téléchargement introuvable")
    torrent_bytes = await file.read()
    ok, msg, info_hash = await add_torrent_file_to_client(
        client_type=client.client_type,
        url=client.url,
        username=client.username,
        password=client.password,
        torrent_bytes=torrent_bytes,
        filename=file.filename or "upload.torrent",
        category=category or client.category,
        tags=tags or client.tags,
    )
    if not ok:
        raise HTTPException(500, msg)
    if request_id and info_hash:
        req = (await db.execute(select(MediaRequest).filter(MediaRequest.id == request_id))).scalars().first()
        if req:
            req.download_client_id = client.id
            req.torrent_hash = info_hash
            await transition_request(db, req, "submitted", source="torrent_file_manual")
            await db.commit()
            from ..services.notification_policy import dispatch_transition_notification

            settings = (await db.execute(select(Settings))).scalars().first()
            await dispatch_transition_notification(settings, req, db, "submitted")
    return {"success": True, "message": msg, "info_hash": info_hash}
