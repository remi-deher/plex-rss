"""File de telechargement Sonarr/Radarr : consultation, retrait et relance d'import."""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy import tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..cache import cache
from ..database import AsyncSessionLocal, get_db_async
from ..dependencies import require_admin
from ..models import ArrInstance, LibraryItem, MediaRequest
from ..services import radarr, sonarr
from ..services.arr_queue_service import fetch_instance_queue
from ..utils import async_get_or_404, wrap_image_proxy
from .arr_shared import ARR_QUEUE_CACHE_KEY, invalidate_arr_queue_cache

router = APIRouter(prefix="/api", tags=["arr"], dependencies=[Depends(require_admin)])
logger = logging.getLogger(__name__)



@router.get("/arr/queue")
async def arr_download_queue(db: AsyncSession = Depends(get_db_async)):
    """File d'attente de téléchargement unifiée : agrège les queues de toutes les instances Sonarr/Radarr actives."""
    async def _background():
        async with AsyncSessionLocal() as fresh_db:
            return await _compute_arr_download_queue(fresh_db)

    return await cache.get_or_refresh(
        ARR_QUEUE_CACHE_KEY,
        soft_ttl_seconds=5,
        hard_ttl_seconds=30,
        compute_sync=lambda: _compute_arr_download_queue(db),
        compute_background=_background,
    )


async def _compute_arr_download_queue(db: AsyncSession) -> list[dict]:
    instances = (await db.execute(select(ArrInstance).filter(ArrInstance.enabled))).scalars().all()
    results = await asyncio.gather(
        *(fetch_instance_queue(instance) for instance in instances), return_exceptions=True
    )
    records_by_instance = []
    lookup_keys: set[tuple[int, int]] = set()
    for instance, result in zip(instances, results):
        if isinstance(result, Exception):
            logger.warning("Lecture de la file %s impossible: %s", instance.name, result)
            continue
        records_by_instance.append((instance, result))
        lookup_keys.update(
            (instance.id, int(record["arr_media_id"]))
            for record in result
            if record.get("arr_media_id") is not None
        )

    req_by_key: dict[tuple[int, int], MediaRequest] = {}
    lib_by_key: dict[tuple[int, int], LibraryItem] = {}
    requests = (
        (await db.execute(select(MediaRequest).filter(
            tuple_(MediaRequest.arr_instance_id, MediaRequest.arr_id).in_(lookup_keys)
        ))).scalars().all()
        if lookup_keys else []
    )
    library_items = (
        (await db.execute(select(LibraryItem).filter(
            tuple_(LibraryItem.arr_instance_id, LibraryItem.arr_id).in_(lookup_keys)
        ))).scalars().all()
        if lookup_keys else []
    )
    for req in requests:
        if req.arr_instance_id:
            req_by_key[(req.arr_instance_id, req.arr_id)] = req
    for li in library_items:
        if li.arr_instance_id:
            lib_by_key[(li.arr_instance_id, li.arr_id)] = li

    items = []
    for inst, records in records_by_instance:
        for rec in records:
            rec["instance"] = inst.name
            rec["instance_id"] = inst.id
            rec["arr_type"] = inst.arr_type

            poster = rec.get("poster_url")
            if poster:
                if poster.startswith("/"):
                    poster = f"{inst.url.rstrip('/')}{poster}"
                rec["poster_url"] = wrap_image_proxy(poster)

            arr_media_id = rec.get("arr_media_id")
            key = (inst.id, arr_media_id) if arr_media_id else None
            li = lib_by_key.get(key) if key else None
            req = req_by_key.get(key) if key else None
            from ..services.operational_projection import plex_library_projection, request_operational_projection

            operational = request_operational_projection(req) if req else (
                plex_library_projection() if li else {
                    "origin_kind": "arr",
                    "origin_label": "Ajoute directement dans *ARR",
                    "operational_status": "downloading",
                    "operational_status_label": "Telechargement gere par *ARR",
                    "waiting_reason": "Aucune demande utilisateur n'est liee a cette entree *ARR.",
                }
            )
            rec["library_id"] = li.id if li else None
            rec["request_id"] = req.id if (req and not li) else None
            rec["linked_request_id"] = req.id if req else None
            rec.update(operational)
            items.append(rec)
    items.sort(key=lambda x: x.get("progress") or 0)
    return jsonable_encoder(items)

@router.delete("/arr/queue/{instance_id}/{queue_id}")
async def delete_arr_queue_item(
    instance_id: int,
    queue_id: int,
    blocklist: bool = False,
    search: bool = True,
    db: AsyncSession = Depends(get_db_async),
):
    """Supprime un item de la file *arr (avec blocklist et relance de recherche optionnelles)."""
    inst = await async_get_or_404(db, ArrInstance, instance_id, "Instance introuvable")
    if inst.arr_type == "sonarr":
        ok, msg = await sonarr.delete_queue_item(inst.url, inst.api_key, queue_id, blocklist=blocklist, search=search)
    elif inst.arr_type == "radarr":
        ok, msg = await radarr.delete_queue_item(inst.url, inst.api_key, queue_id, blocklist=blocklist, search=search)
    else:
        raise HTTPException(400, "Instance non applicable (ni Sonarr ni Radarr)")
    if not ok:
        raise HTTPException(502, msg)
    await invalidate_arr_queue_cache()
    return {"status": "ok", "message": msg}

class TriggerImportBody(BaseModel):
    output_path: Optional[str] = None
    download_id: Optional[str] = None

@router.post("/arr/queue/{instance_id}/{queue_id}/import")
async def trigger_arr_import(
    instance_id: int,
    queue_id: int,
    body: TriggerImportBody,
    db: AsyncSession = Depends(get_db_async),
):
    """Déclenche l'import d'un item dont le téléchargement est terminé mais bloqué
    en attente d'import (trackedDownloadState == importPending). Envoie la commande
    DownloadedEpisodesScan (Sonarr) ou DownloadedMoviesScan (Radarr) à l'instance *arr
    avec le chemin de sortie ou le download_id pour cibler précisément l'item.
    """
    inst = await async_get_or_404(db, ArrInstance, instance_id, "Instance introuvable")
    if inst.arr_type == "sonarr":
        ok, msg = await sonarr.trigger_import(
            inst.url, inst.api_key,
            output_path=body.output_path,
            download_id=body.download_id,
        )
    elif inst.arr_type == "radarr":
        ok, msg = await radarr.trigger_import(
            inst.url, inst.api_key,
            output_path=body.output_path,
            download_id=body.download_id,
        )
    else:
        raise HTTPException(400, "Instance non applicable (ni Sonarr ni Radarr)")
    if not ok:
        raise HTTPException(502, msg)
    # Invalide le cache pour que la prochaine lecture reflète l'état réel
    await invalidate_arr_queue_cache()
    return {"status": "ok", "message": msg}
