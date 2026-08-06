"""Agrégation métier de la fiche média unifiée."""

import logging
from typing import Awaitable, Callable, Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..models import (
    ArrInstance,
    LibraryItem,
    MediaIssue,
    MediaRequest,
    NotificationLog,
    PlexUser,
    RequestSeasonStatus,
)
from ..serializers import format_datetime, serialize_media_request
from ..utils import async_get_or_404, wrap_image_proxy
from . import tmdb
from .media_annotate import annotate_media_items
from .operational_projection import plex_library_projection

logger = logging.getLogger(__name__)


def _media_payload(
    media_obj,
    library_item: LibraryItem | None,
    selected_request: MediaRequest | None,
    operational: dict,
    *,
    arr_url: str | None,
    backdrop_url: str | None = None,
) -> dict:
    return {
        "kind": "library" if library_item else "request",
        "library_id": library_item.id if library_item else None,
        "request_id": selected_request.id if selected_request else None,
        "vf_source_type": "library" if library_item else "request",
        "vf_source_id": library_item.id if library_item else (
            selected_request.id if selected_request else None
        ),
        "title": media_obj.title,
        "year": media_obj.year,
        "media_type": media_obj.media_type,
        "poster_url": wrap_image_proxy(media_obj.poster_url),
        "backdrop_url": wrap_image_proxy(backdrop_url),
        "overview": media_obj.overview,
        "has_vf": media_obj.has_vf,
        "vf_granularity": media_obj.vf_granularity,
        "arr_id": media_obj.arr_id,
        "arr_slug": media_obj.arr_slug,
        "arr_instance_id": media_obj.arr_instance_id,
        "arr_url": arr_url,
        "tmdb_id": media_obj.tmdb_id,
        "tvdb_id": media_obj.tvdb_id,
        "imdb_id": media_obj.imdb_id,
        "plex_guid": media_obj.plex_guid,
        "in_library": library_item is not None,
        "added_at": format_datetime(library_item.added_at) if library_item else None,
        "origin_kind": operational.get("origin_kind"),
        "origin_label": operational.get("origin_label"),
        "operational_status": operational.get("operational_status"),
        "operational_status_label": operational.get("operational_status_label"),
        "waiting_reason": operational.get("waiting_reason"),
        "workflow_timeline": operational.get("workflow_timeline", []),
    }


async def build_media_detail(
    db: AsyncSession,
    *,
    library_id: Optional[int],
    request_id: Optional[int],
    identity_filter: Callable[[AsyncSession, object], Awaitable[list[MediaRequest]]],
    schedule_payload: Callable[[AsyncSession, object], Awaitable[dict]],
    issue_serializer: Callable[[MediaIssue], dict],
    core_only: bool = False,
) -> dict:
    """Fusionne DB, calendrier *arr et enrichissement TMDB pour l'endpoint de détail."""
    if not library_id and not request_id:
        raise HTTPException(400, "library_id or request_id is required")

    selected_request = None
    library_item = None
    if library_id:
        library_item = await async_get_or_404(
            db, LibraryItem, library_id, "Library item not found"
        )
        media_obj = library_item
    else:
        selected_request = await async_get_or_404(
            db, MediaRequest, request_id, "Request not found"
        )
        if selected_request.library_item_id:
            library_item = await db.get(LibraryItem, selected_request.library_item_id)
        media_obj = library_item or selected_request

    arr_url = None
    if media_obj.arr_instance_id and media_obj.arr_slug:
        instance = await db.get(ArrInstance, media_obj.arr_instance_id)
        if instance:
            entity = "movie" if media_obj.media_type == "movie" else "series"
            arr_url = f"{instance.url.rstrip('/')}/{entity}/{media_obj.arr_slug}"

    if core_only:
        operational = (
            serialize_media_request(selected_request, {})
            if selected_request
            else plex_library_projection()
        )
        return {
            "media": _media_payload(
                media_obj,
                library_item,
                selected_request,
                operational,
                arr_url=arr_url,
            )
        }

    related_requests = await identity_filter(db, media_obj)
    if selected_request and selected_request.id not in {row.id for row in related_requests}:
        related_requests.insert(0, selected_request)

    all_users = (await db.execute(select(PlexUser))).scalars().all()
    users = {
        user.plex_user_id: user.custom_name or user.display_name or user.plex_user_id
        for user in all_users
    }
    user_by_id = {user.plex_user_id: user for user in all_users}
    request_ids = [row.id for row in related_requests]
    last_mail: dict[tuple[int, str], dict] = {}
    recipients: dict[tuple[int, str], set[str]] = {}
    history = []
    if request_ids:
        logs = (await db.execute(
            select(NotificationLog)
            .filter(NotificationLog.req_id.in_(request_ids))
            .order_by(NotificationLog.sent_at.desc())
            .limit(50)
        )).scalars().all()
        history = [{
            "id": log.id, "event": log.event, "channel": log.channel,
            "recipient": log.recipient, "sent_at": format_datetime(log.sent_at),
            "success": log.success, "error_msg": log.error_msg,
            "triggered_by": log.triggered_by, "scope": log.scope,
            "language": log.language, "season_number": log.season_number,
            "episode_number": log.episode_number,
        } for log in logs]
        for log in logs:
            if log.channel != "email" or log.event not in ("request", "available"):
                continue
            key = (log.req_id, log.event)
            last_mail.setdefault(key, {
                "sent_at": format_datetime(log.sent_at),
                "triggered_by": log.triggered_by,
                "success": log.success,
            })
            if log.success:
                recipients.setdefault(key, set()).add((log.recipient or "").strip().lower())

    seasons: dict[int, list[dict]] = {}
    show_ids = [row.id for row in related_requests if row.media_type == "show"]
    if show_ids:
        rows = (await db.execute(
            select(RequestSeasonStatus).filter(RequestSeasonStatus.request_id.in_(show_ids))
        )).scalars().all()
        for row in rows:
            seasons.setdefault(row.request_id, []).append({
                "season_number": row.season_number,
                "episodes_available_count": row.episodes_available_count,
                "episodes_total_count": row.episodes_total_count,
                "status": row.status,
            })
        for values in seasons.values():
            values.sort(key=lambda value: value["season_number"])

    def requester_emails(user_id: str) -> set[str]:
        user = user_by_id.get(user_id)
        raw = (user.notification_email if user else None) or ""
        return {address.strip().lower() for address in raw.split(",") if address.strip()}

    request_payloads = [serialize_media_request(row, users) for row in related_requests]
    for payload, row in zip(request_payloads, related_requests):
        payload["seasons"] = seasons.get(row.id, [])
        payload["last_request_mail"] = last_mail.get((row.id, "request"))
        payload["last_available_mail"] = last_mail.get((row.id, "available"))
        request_recipients = recipients.get((row.id, "request"), set())
        available_recipients = recipients.get((row.id, "available"), set())
        payload["requester_notifications"] = {}
        for user_id in payload.get("requester_ids", []):
            addresses = requester_emails(user_id)
            payload["requester_notifications"][user_id] = {
                "request": bool(addresses & request_recipients) if addresses else None,
                "available": bool(addresses & available_recipients) if addresses else None,
            }

    schedule = await schedule_payload(db, media_obj)
    issue_query = select(MediaIssue).filter(MediaIssue.status != "closed")
    if library_item and request_ids:
        issue_query = issue_query.filter(
            (MediaIssue.library_item_id == library_item.id)
            | (MediaIssue.request_id.in_(request_ids))
        )
    elif library_item:
        issue_query = issue_query.filter(MediaIssue.library_item_id == library_item.id)
    else:
        issue_query = issue_query.filter(MediaIssue.request_id == selected_request.id)
    issues = (await db.execute(
        issue_query.order_by(MediaIssue.created_at.desc())
    )).scalars().all()

    backdrop_url = None
    saga = None
    recommendations = []
    similar = []
    cast = []
    if media_obj.tmdb_id:
        try:
            detail = await tmdb.detail(db, media_obj.media_type, int(media_obj.tmdb_id))
            backdrop_url = detail.get("backdrop_url")
            saga = detail.get("saga")
            recommendations = await annotate_media_items(db, detail.get("recommendations", []))
            similar = await annotate_media_items(db, detail.get("similar", []))
            cast = detail.get("cast", [])
            if saga:
                saga["items"] = await annotate_media_items(db, saga.get("items", []))
        except Exception as exc:
            logger.debug("TMDB backdrop unavailable: %s", exc)

    operational = request_payloads[0] if request_payloads else (
        plex_library_projection() if library_item else {}
    )
    return {
        "media": _media_payload(
            media_obj,
            library_item,
            selected_request or (related_requests[0] if related_requests else None),
            operational,
            arr_url=arr_url,
            backdrop_url=backdrop_url,
        ),
        "requests": request_payloads,
        "issues": [issue_serializer(issue) for issue in issues],
        "timeline": schedule["timeline"],
        "calendar": schedule["events"],
        "notification_history": history,
        "saga": saga,
        "recommendations": recommendations,
        "similar": similar,
        "cast": cast,
    }
