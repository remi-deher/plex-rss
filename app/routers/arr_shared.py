"""Helpers partages par les routers *arr : resolution d'instance et appels delegues."""

import logging
from typing import Optional

import sqlalchemy
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..dependencies import require_admin
from ..models import ArrInstance, Settings

router = APIRouter(prefix="/api", tags=["arr"], dependencies=[Depends(require_admin)])
logger = logging.getLogger(__name__)

# Cache memoire tres court (secondes) pour absorber le polling frequent (la barre laterale
# et la page Telechargements interrogent toutes les 5 s en parallele) sans multiplier les
# appels reseau reels vers Sonarr/Radarr/qBittorrent a chaque requete entrante.
#
# Partage : arr_queue_api et downloads_api le remplissent, manual_import_api l'invalide
# apres un import force -- sinon le prochain GET /arr/queue montrerait encore l'item en
# erreur pendant plusieurs secondes.
_QUEUE_CACHE_TTL = 4.0
_queue_cache: dict = {"data": None, "ts": 0.0}
_direct_cache: dict = {"data": None, "ts": 0.0}


async def _set_single_default(db: AsyncSession, model, type_col: str, type_val: str, exclude_id: Optional[int] = None) -> None:
    """Remet is_default=False sur toutes les instances du même type, sauf exclude_id."""
    conditions = [getattr(model, type_col) == type_val]
    if exclude_id is not None:
        conditions.append(model.id != exclude_id)
    await db.execute(sqlalchemy.update(model).where(*conditions).values(is_default=False))

async def _resolve_arr_instance(db: AsyncSession, instance_id: Optional[int], arr_type: str) -> ArrInstance:
    if instance_id is not None:
        inst = (await db.execute(select(ArrInstance).filter(ArrInstance.id == instance_id, ArrInstance.arr_type == arr_type))).scalars().first()
        if not inst:
            raise HTTPException(404, f"Instance {instance_id} ({arr_type}) introuvable")
        return inst
    inst = (await db.execute(select(ArrInstance).filter(ArrInstance.is_default, ArrInstance.arr_type == arr_type))).scalars().first()
    if not inst:
        # Fallback de compatibilité avec settings globales
        settings = (await db.execute(select(Settings))).scalars().first()
        if arr_type == "sonarr" and settings and settings.sonarr_url:
            return ArrInstance(
                url=settings.sonarr_url,
                api_key=settings.sonarr_api_key,
                root_folder=settings.sonarr_root_folder,
            )
        elif arr_type == "radarr" and settings and settings.radarr_url:
            return ArrInstance(
                url=settings.radarr_url,
                api_key=settings.radarr_api_key,
                root_folder=settings.radarr_root_folder,
                minimum_availability=settings.radarr_minimum_availability or "released",
            )
        raise HTTPException(400, f"Aucune instance par défaut configurée pour {arr_type}")
    return inst

async def _arr_call(
    url: Optional[str],
    api_key: Optional[str],
    instance_id: Optional[int],
    arr_type: str,
    db: AsyncSession,
    coro_fn,
):
    """Appelle coro_fn(url, api_key) en résolvant l'instance si url/api_key ne sont pas fournis inline."""
    if url and api_key:
        return await coro_fn(url, api_key)
    inst = await _resolve_arr_instance(db, instance_id, arr_type)
    return await coro_fn(inst.url, inst.api_key)

async def _arr_folders(
    url: Optional[str],
    api_key: Optional[str],
    instance_id: Optional[int],
    arr_type: str,
    db: AsyncSession,
    coro_fn,
):
    default_root = None
    if url and api_key:
        folders = await coro_fn(url, api_key)
    else:
        inst = await _resolve_arr_instance(db, instance_id, arr_type)
        default_root = inst.root_folder
        folders = await coro_fn(inst.url, inst.api_key)

    out = []
    for folder in folders:
        data = {"path": folder} if isinstance(folder, str) else dict(folder)
        path = data.get("path")
        data["is_default"] = bool(default_root and path == default_root)
        out.append(data)
    return out
