import logging
from datetime import datetime

import sqlalchemy
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..models import LibraryItem, MediaRequest, RequestStatus, Settings
from ..utils import now_utc_naive
from .download_history import record_completed

logger = logging.getLogger(__name__)


async def find_plex_library_item(db: AsyncSession, req: MediaRequest) -> LibraryItem | None:
    """Return the Plex library item that proves this request is available."""
    if req.library_item_id:
        item = (await db.execute(select(LibraryItem).filter(LibraryItem.id == req.library_item_id))).scalars().first()
        if item:
            return item
        req.library_item_id = None

    conditions = []
    if req.tmdb_id:
        conditions.append(LibraryItem.tmdb_id == str(req.tmdb_id))
    if req.tvdb_id:
        conditions.append(LibraryItem.tvdb_id == str(req.tvdb_id))
    if req.imdb_id:
        conditions.append(LibraryItem.imdb_id == str(req.imdb_id))

    item = (await db.execute(select(LibraryItem).filter(or_(*conditions)))).scalars().first() if conditions else None
    if not item and req.title and req.year:
        item = (await db.execute(
            select(LibraryItem).filter(
                LibraryItem.media_type == req.media_type,
                LibraryItem.title.ilike(req.title),
                LibraryItem.year == req.year,
            )
        )).scalars().first()
    if item:
        req.library_item_id = item.id
    return item


async def has_plex_proof(db: AsyncSession, req: MediaRequest) -> bool:
    settings = (await db.execute(select(Settings))).scalars().first()
    if not settings or not settings.plex_url or not settings.plex_token:
        return True
    count = (await db.execute(select(sqlalchemy.func.count(LibraryItem.id)))).scalar()
    if not count:
        return True
    return await find_plex_library_item(db, req) is not None


def note_arr_processed(
    req: MediaRequest,
    *,
    arr_id: int | None = None,
    arr_slug: str | None = None,
    arr_instance_id: int | None = None,
) -> None:
    """Record that Sonarr/Radarr processed the request without confirming availability."""
    if arr_id and not req.arr_id:
        req.arr_id = int(arr_id)
    if arr_slug and not req.arr_slug:
        req.arr_slug = arr_slug
    if arr_instance_id and not req.arr_instance_id:
        req.arr_instance_id = arr_instance_id
    req.is_downloading = False


async def _set_available(
    db: AsyncSession,
    req: MediaRequest,
    *,
    source: str,
    instance_name: str | None = None,
    available_at: datetime | None = None,
    require_plex: bool = True,
) -> bool:
    if require_plex and not await has_plex_proof(db, req):
        logger.info(
            "Disponibilite refusee pour '%s': aucune preuve Plex associee a la demande.",
            req.title,
        )
        return False

    was_available = req.status == RequestStatus.available
    req.status = RequestStatus.available
    req.available_at = req.available_at or available_at or now_utc_naive()
    req.is_downloading = False
    req.next_release_at = None
    req.next_release_label = None
    await db.commit()

    if not was_available:
        await record_completed(
            db,
            title=req.title,
            year=req.year,
            media_type=req.media_type,
            source=source,
            instance_name=instance_name,
            poster_url=req.poster_url,
            request_id=req.id,
        )
    return not was_available


async def confirm_available_from_plex(
    settings: Settings | None,
    req: MediaRequest,
    db: AsyncSession,
    *,
    source: str = "plex",
    instance_name: str | None = None,
    available_at: datetime | None = None,
    notify: bool = True,
    require_library_item: bool = True,
) -> bool:
    """Confirm final availability from Plex proof, then notify if this is a new transition."""
    changed = await _set_available(
        db,
        req,
        source=source,
        instance_name=instance_name,
        available_at=available_at,
        require_plex=require_library_item,
    )
    if not changed or not settings or not notify:
        return changed

    handled = False
    if settings.vff_enabled:
        from .vff_scanner import scan_and_notify_availability

        handled = await scan_and_notify_availability(req, settings, db)

    if not handled and not settings.vff_enabled and not req.available_mail_sent:
        from . import notification_orchestrator

        await notification_orchestrator._notify("available", settings, req, db)
    return changed


async def force_available_by_admin(
    settings: Settings | None,
    req: MediaRequest,
    db: AsyncSession,
    *,
    source: str = "manual_admin",
) -> bool:
    """Admin override: manual action is allowed to be authoritative."""
    return await _set_available(db, req, source=source, require_plex=False)
