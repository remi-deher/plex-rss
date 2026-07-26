"""File de telechargement Sonarr/Radarr : consultation, retrait et relance d'import."""

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import get_db_async
from ..dependencies import require_admin
from ..models import ArrInstance, LibraryItem, MediaRequest
from ..services import radarr, sonarr
from ..services.arr_queue_service import fetch_instance_queue
from ..utils import async_get_or_404, wrap_image_proxy
from .arr_shared import _QUEUE_CACHE_TTL, _queue_cache

router = APIRouter(prefix="/api", tags=["arr"], dependencies=[Depends(require_admin)])
logger = logging.getLogger(__name__)



@router.get("/arr/queue")
async def arr_download_queue(db: AsyncSession = Depends(get_db_async)):
    """File d'attente de téléchargement unifiée : agrège les queues de toutes les instances Sonarr/Radarr actives."""
    now = time.monotonic()
    if _queue_cache["data"] is not None and now - _queue_cache["ts"] < _QUEUE_CACHE_TTL:
        return _queue_cache["data"]

    instances = (await db.execute(select(ArrInstance).filter(ArrInstance.enabled))).scalars().all()

    # Pré-charge les demandes/items bibliothèque par (arr_instance_id, arr_id) pour lier
    # chaque ligne de la file à sa fiche média (lien "Voir la fiche" côté UI).
    req_by_key: dict[tuple[int, int], MediaRequest] = {}
    lib_by_key: dict[tuple[int, int], LibraryItem] = {}
    for req in (await db.execute(select(MediaRequest).filter(MediaRequest.arr_id.isnot(None)))).scalars().all():
        if req.arr_instance_id:
            req_by_key[(req.arr_instance_id, req.arr_id)] = req
    for li in (await db.execute(select(LibraryItem).filter(LibraryItem.arr_id.isnot(None)))).scalars().all():
        if li.arr_instance_id:
            lib_by_key[(li.arr_instance_id, li.arr_id)] = li

    items = []
    for inst in instances:
        records = await fetch_instance_queue(inst)
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
    _queue_cache["data"] = items
    _queue_cache["ts"] = now
    return items

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
    _queue_cache["data"] = None
    return {"status": "ok", "message": msg}
