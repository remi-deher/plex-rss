"""CRUD des instances Sonarr/Radarr/Prowlarr et lecture de leur configuration (profils de qualite, dossiers racine, tags)."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import get_db_async
from ..dependencies import require_admin
from ..models import ArrInstance, DownloadClient
from ..services import prowlarr, radarr, sonarr
from ..utils import async_get_or_404
from .arr_shared import _arr_call, _arr_folders, _set_single_default

router = APIRouter(prefix="/api", tags=["arr"], dependencies=[Depends(require_admin)])
logger = logging.getLogger(__name__)

class ArrInstanceCreate(BaseModel):
    name: str
    arr_type: str
    url: str
    api_key: str
    quality_profile_id: Optional[int] = None
    root_folder: Optional[str] = None
    minimum_availability: Optional[str] = "released"
    enabled: Optional[bool] = True
    is_default: Optional[bool] = False
    indexer_ids: Optional[str] = None

class TestArrInstanceBody(BaseModel):
    url: str
    api_key: str
    arr_type: str

@router.get("/arr-instances")
async def list_arr_instances(db: AsyncSession = Depends(get_db_async)):
    return (await db.execute(select(ArrInstance))).scalars().all()

@router.get("/arr/capabilities")
async def arr_capabilities(db: AsyncSession = Depends(get_db_async)):
    all_instances = (await db.execute(select(ArrInstance))).scalars().all()
    enabled_instances = [i for i in all_instances if i.enabled]
    configured_types = {i.arr_type for i in all_instances}
    enabled_types = {i.arr_type for i in enabled_instances}
    has_enabled_clients = (await db.execute(select(DownloadClient).filter(DownloadClient.enabled))).scalars().first() is not None
    has_clients = (await db.execute(select(DownloadClient))).scalars().first() is not None
    return {
        "has_sonarr": "sonarr" in enabled_types,
        "has_radarr": "radarr" in enabled_types,
        "has_prowlarr": "prowlarr" in enabled_types,
        "sonarr_configured": "sonarr" in configured_types,
        "radarr_configured": "radarr" in configured_types,
        "prowlarr_configured": "prowlarr" in configured_types,
        "sonarr_disabled": "sonarr" in configured_types and "sonarr" not in enabled_types,
        "radarr_disabled": "radarr" in configured_types and "radarr" not in enabled_types,
        "prowlarr_disabled": "prowlarr" in configured_types and "prowlarr" not in enabled_types,
        "has_arr_downloads": bool({"sonarr", "radarr"} & enabled_types),
        "arr_downloads_disabled": bool({"sonarr", "radarr"} & configured_types)
        and not bool({"sonarr", "radarr"} & enabled_types),
        "has_download_clients": has_enabled_clients,
        "download_clients_configured": has_clients,
        "download_clients_disabled": has_clients and not has_enabled_clients,
    }

@router.post("/arr-instances")
async def create_arr_instance(data: ArrInstanceCreate, db: AsyncSession = Depends(get_db_async)):
    if data.is_default:
        await _set_single_default(db, ArrInstance, "arr_type", data.arr_type)
    inst = ArrInstance(**data.model_dump())
    db.add(inst)
    await db.commit()
    await db.refresh(inst)
    return inst

@router.put("/arr-instances/{instance_id}")
async def update_arr_instance(instance_id: int, data: ArrInstanceCreate, db: AsyncSession = Depends(get_db_async)):
    inst = await async_get_or_404(db, ArrInstance, instance_id, "Instance introuvable")
    if data.is_default:
        await _set_single_default(db, ArrInstance, "arr_type", data.arr_type, exclude_id=instance_id)
    for k, v in data.model_dump().items():
        setattr(inst, k, v)
    await db.commit()
    await db.refresh(inst)
    return inst

@router.delete("/arr-instances/{instance_id}")
async def delete_arr_instance(instance_id: int, db: AsyncSession = Depends(get_db_async)):
    inst = await async_get_or_404(db, ArrInstance, instance_id, "Instance introuvable")
    await db.delete(inst)
    await db.commit()
    return {"status": "deleted"}

@router.patch("/arr-instances/{instance_id}/toggle")
async def toggle_arr_instance(instance_id: int, db: AsyncSession = Depends(get_db_async)):
    inst = await async_get_or_404(db, ArrInstance, instance_id, "Instance introuvable")
    inst.enabled = not inst.enabled
    await db.commit()
    return {"id": inst.id, "enabled": inst.enabled}

@router.patch("/arr-instances/by-type/{arr_type}/toggle")
async def toggle_arr_instances_by_type(arr_type: str, db: AsyncSession = Depends(get_db_async)):
    """Active/désactive en un clic toutes les instances d'un type (carte de la vue Connexions)."""
    instances = (await db.execute(select(ArrInstance).filter(ArrInstance.arr_type == arr_type))).scalars().all()
    if not instances:
        raise HTTPException(404, f"Aucune instance {arr_type} configurée")
    new_state = not any(i.enabled for i in instances)
    for inst in instances:
        inst.enabled = new_state
    await db.commit()
    return {"arr_type": arr_type, "enabled": new_state, "count": len(instances)}

@router.post("/test/arr-instance")
async def test_arr_instance(body: TestArrInstanceBody):
    if body.arr_type == "prowlarr":
        ok = await prowlarr.check_connection(body.url, body.api_key)
        return {"success": ok, "message": "Prowlarr connecté" if ok else "Erreur de connexion Prowlarr"}
    elif body.arr_type == "sonarr":
        ok, msg = await sonarr.check_connection(body.url, body.api_key)
        return {"success": ok, "message": msg}
    elif body.arr_type == "radarr":
        ok, msg = await radarr.check_connection(body.url, body.api_key)
        return {"success": ok, "message": msg}
    return {"success": False, "message": f"Type d'instance inconnu : {body.arr_type}"}

@router.get("/sonarr/profiles")
async def sonarr_profiles(
    instance_id: Optional[int] = None,
    url: Optional[str] = None,
    api_key: Optional[str] = None,
    db: AsyncSession = Depends(get_db_async),
):
    return await _arr_call(url, api_key, instance_id, "sonarr", db, sonarr.get_quality_profiles)

@router.get("/sonarr/folders")
async def sonarr_folders(
    instance_id: Optional[int] = None,
    url: Optional[str] = None,
    api_key: Optional[str] = None,
    db: AsyncSession = Depends(get_db_async),
):
    return await _arr_folders(url, api_key, instance_id, "sonarr", db, sonarr.get_root_folders)

@router.get("/radarr/profiles")
async def radarr_profiles(
    instance_id: Optional[int] = None,
    url: Optional[str] = None,
    api_key: Optional[str] = None,
    db: AsyncSession = Depends(get_db_async),
):
    return await _arr_call(url, api_key, instance_id, "radarr", db, radarr.get_quality_profiles)

@router.get("/radarr/folders")
async def radarr_folders(
    instance_id: Optional[int] = None,
    url: Optional[str] = None,
    api_key: Optional[str] = None,
    db: AsyncSession = Depends(get_db_async),
):
    return await _arr_folders(url, api_key, instance_id, "radarr", db, radarr.get_root_folders)

@router.get("/sonarr/tags")
async def sonarr_tags(
    instance_id: Optional[int] = None,
    url: Optional[str] = None,
    api_key: Optional[str] = None,
    db: AsyncSession = Depends(get_db_async),
):
    return await _arr_call(url, api_key, instance_id, "sonarr", db, sonarr.get_tags)

@router.get("/radarr/tags")
async def radarr_tags(
    instance_id: Optional[int] = None,
    url: Optional[str] = None,
    api_key: Optional[str] = None,
    db: AsyncSession = Depends(get_db_async),
):
    return await _arr_call(url, api_key, instance_id, "radarr", db, radarr.get_tags)
