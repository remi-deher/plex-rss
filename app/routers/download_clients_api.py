"""CRUD des clients de telechargement direct (qBittorrent, Transmission, Deluge)."""

import logging
from typing import Optional

import sqlalchemy
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import get_db_async
from ..dependencies import require_admin
from ..models import DownloadClient
from ..services.download_clients import (
    check_client_connection,
)
from ..utils import async_get_or_404

router = APIRouter(prefix="/api", tags=["arr"], dependencies=[Depends(require_admin)])
logger = logging.getLogger(__name__)

class DownloadClientCreate(BaseModel):
    name: str
    client_type: str
    url: str
    username: Optional[str] = None
    password: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    is_default: Optional[bool] = False
    enabled: Optional[bool] = True

class TestDownloadClientBody(BaseModel):
    client_type: str
    url: str
    username: Optional[str] = None
    password: Optional[str] = None

@router.get("/download-clients")
async def list_download_clients(db: AsyncSession = Depends(get_db_async)):
    return (await db.execute(select(DownloadClient))).scalars().all()

@router.post("/download-clients")
async def create_download_client(data: DownloadClientCreate, db: AsyncSession = Depends(get_db_async)):
    if data.is_default:
        await db.execute(sqlalchemy.update(DownloadClient).values({"is_default": False}))
    client = DownloadClient(**data.model_dump())
    db.add(client)
    await db.commit()
    await db.refresh(client)
    return client

@router.put("/download-clients/{client_id}")
async def update_download_client(client_id: int, data: DownloadClientCreate, db: AsyncSession = Depends(get_db_async)):
    client = await async_get_or_404(db, DownloadClient, client_id, "Client introuvable")
    if data.is_default:
        await db.execute(sqlalchemy.update(DownloadClient).where(DownloadClient.id != client_id).values({"is_default": False}))
    for k, v in data.model_dump().items():
        setattr(client, k, v)
    await db.commit()
    await db.refresh(client)
    return client

@router.patch("/download-clients/{client_id}/toggle")
async def toggle_download_client(client_id: int, db: AsyncSession = Depends(get_db_async)):
    client = await async_get_or_404(db, DownloadClient, client_id, "Client introuvable")
    client.enabled = not client.enabled
    await db.commit()
    return {"id": client.id, "enabled": client.enabled}

@router.delete("/download-clients/{client_id}")
async def delete_download_client(client_id: int, db: AsyncSession = Depends(get_db_async)):
    client = await async_get_or_404(db, DownloadClient, client_id, "Client introuvable")
    await db.delete(client)
    await db.commit()
    return {"status": "deleted"}

@router.post("/test/download-client")
async def test_download_client(body: TestDownloadClientBody):
    ok, msg = await check_client_connection(body.client_type, body.url, body.username, body.password)
    return {"success": ok, "message": msg}
