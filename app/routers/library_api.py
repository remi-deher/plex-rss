import logging
from datetime import datetime
from html import escape
from typing import Optional

import httpx
import sqlalchemy
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import get_db_async
from ..dependencies import current_user, require_admin, require_auth
from ..models import (
    ArrInstance,
    LibraryItem,
    MediaIssue,
    MediaRequest,
    NotificationLog,
    PlexUser,
    RequestSeasonStatus,
    RequestStatus,
    Settings,
    VfEpisodeStatus,
)
from ..services import radarr, sonarr, tmdb
from ..services import seer as seer_service
from ..services.email_service import build_correction_email, send_correction_notification
from ..services.diagnostics import record_event, update_request_context
from ..services.notification_orchestrator import _notify
from ..utils import async_get_or_404, identity_keys, now_utc_naive, wrap_image_proxy
from .arr_api import _resolve_arr_instance

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["library"], dependencies=[Depends(require_auth)])


class MediaAddRequest(BaseModel):
    title: str
    year: Optional[int] = None
    media_type: str  # "movie" | "show"
    tmdb_id: Optional[int] = None
    tvdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    poster_url: Optional[str] = None
    overview: Optional[str] = None
    quality_profile_id: Optional[int] = None
    root_folder: Optional[str] = None
    tag_ids: list[int] = Field(default_factory=list)
    seasons: Optional[list[int]] = None
    plex_user_id: Optional[str] = None
    instance_id: Optional[int] = None  # None = Seer ou instance par défaut
    use_seer: bool = False
    bypass_seer: bool = False
    auto_search: bool = False












async def _media_identity_filter(db: AsyncSession, item) -> list[MediaRequest]:
    """Retourne les demandes qui représentent le même média qu'un LibraryItem ou une demande."""
    matches: dict[int, MediaRequest] = {}
    if isinstance(item, LibraryItem):
        for req in (await db.execute(select(MediaRequest).filter(MediaRequest.library_item_id == item.id))).scalars().all():
            matches[req.id] = req
    for key in identity_keys(item):
        kind = key[0]
        value = key[1] if len(key) > 1 else None
        col = {
            "guid": MediaRequest.plex_guid,
            "tmdb": MediaRequest.tmdb_id,
            "tvdb": MediaRequest.tvdb_id,
            "imdb": MediaRequest.imdb_id,
        }.get(kind)
        if col is not None:
            for req in (await db.execute(select(MediaRequest).filter(col == value))).scalars().all():
                matches[req.id] = req
    if getattr(item, "title", None) and getattr(item, "media_type", None):
        q = select(MediaRequest).filter(
            MediaRequest.title.ilike(item.title),
            MediaRequest.media_type == item.media_type,
        )
        if getattr(item, "year", None):
            q = q.filter(MediaRequest.year == item.year)
        for req in (await db.execute(q)).scalars().all():
            matches[req.id] = req
    return sorted(matches.values(), key=lambda r: r.requested_at or datetime.min, reverse=True)










async def _media_schedule_payload(db: AsyncSession, item) -> dict:
    timeline = {
        "first_aired": None,
        "next_episode_at": None,
        "last_aired_at": None,
        "ended_at": None,
        "series_status": None,
        "in_cinemas": None,
        "digital_release": None,
        "physical_release": None,
        "release_date": None,
    }
    events: list[dict] = []

    if item.media_type == "show":
        try:
            inst = await _resolve_arr_instance(db, item.arr_instance_id, "sonarr")
            data = None
            series_id = None
            if item.tvdb_id:
                data = await sonarr.lookup_series(
                    inst.url,
                    inst.api_key,
                    tvdb_id=item.tvdb_id,
                    tmdb_id=item.tmdb_id,
                    imdb_id=item.imdb_id,
                )
                series_id = data.get("id") if data else None
            if not series_id and getattr(item, "source", None) != "seer" and item.arr_id:
                series_id = item.arr_id
                data = data or await sonarr.lookup_series(
                    inst.url,
                    inst.api_key,
                    arr_id=series_id,
                    tvdb_id=item.tvdb_id,
                    tmdb_id=item.tmdb_id,
                    imdb_id=item.imdb_id,
                )
            if data:
                timeline["first_aired"] = data.get("firstAired")
                timeline["next_episode_at"] = data.get("nextAiring")
                timeline["series_status"] = data.get("status")
                series_id = series_id or data.get("id")
            if series_id:
                episodes = await sonarr.get_episodes(inst.url, inst.api_key, series_id)
                dated = []
                for ep in episodes:
                    air = ep.get("airDateUtc") or ep.get("airDate")
                    if not air or ep.get("seasonNumber") == 0:
                        continue
                    dated.append(air)
                    events.append(
                        {
                            "type": "episode",
                            "date": air,
                            "title": item.title,
                            "subtitle": f"S{ep.get('seasonNumber', 0):02d}E{ep.get('episodeNumber', 0):02d}"
                            + (f" — {ep.get('title')}" if ep.get("title") else ""),
                            "has_file": bool(ep.get("hasFile")),
                            "instance": inst.name,
                        }
                    )
                if dated:
                    timeline["last_aired_at"] = max(dated)
                    if timeline["series_status"] == "ended":
                        timeline["ended_at"] = max(dated)
        except Exception as e:
            logger.debug(f"media detail: calendrier Sonarr indisponible pour '{item.title}': {e}")
    else:
        try:
            inst = await _resolve_arr_instance(db, item.arr_instance_id, "radarr")
            data = await radarr.lookup_movie(
                inst.url, inst.api_key, arr_id=item.arr_id, tmdb_id=item.tmdb_id, imdb_id=item.imdb_id
            )
            if data:
                date_fields = [
                    ("in_cinemas", "Cinema", data.get("inCinemas")),
                    ("digital_release", "Digital", data.get("digitalRelease")),
                    ("physical_release", "Physique", data.get("physicalRelease")),
                ]
                for key, label, value in date_fields:
                    timeline[key] = value
                    if value:
                        events.append(
                            {
                                "type": "movie",
                                "date": value,
                                "title": item.title,
                                "subtitle": label,
                                "has_file": bool(data.get("hasFile")),
                                "instance": inst.name,
                            }
                        )
                timeline["release_date"] = (
                    timeline["in_cinemas"] or timeline["digital_release"] or timeline["physical_release"]
                )
        except Exception as e:
            logger.debug(f"media detail: calendrier Radarr indisponible pour '{item.title}': {e}")

    events.sort(key=lambda e: e["date"])
    return {"timeline": timeline, "events": events}


@router.get("/plex/sections")
async def plex_sections(db: AsyncSession = Depends(get_db_async)):
    """Liste les bibliothèques Plex locales (nom + type) pour la configuration VFF."""
    s = (await db.execute(select(Settings))).scalars().first()
    if not s or not s.plex_url or not s.plex_token:
        return []
    try:
        async with httpx.AsyncClient(timeout=10, verify=s.plex_verify_ssl) as client:
            r = await client.get(
                f"{s.plex_url.rstrip('/')}/library/sections",
                params={"X-Plex-Token": s.plex_token},
                headers={"Accept": "application/json"},
            )
            r.raise_for_status()
            dirs = r.json().get("MediaContainer", {}).get("Directory", [])
            return [{"name": d.get("title", ""), "type": d.get("type", "")} for d in dirs]
    except Exception as e:
        logger.warning(f"Plex sections fetch failed: {e}")
        return []


@router.get("/library")
async def list_library(
    query: Optional[str] = None,
    media_type: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    db: AsyncSession = Depends(get_db_async),
):
    """Return Plex library items for the SPA library browser (paginee via limit/offset).

    `limit` est plafonne a 500 par appel ; le client pagine avec des appels successifs
    en incrementant `offset` (voir LibraryView.vue) plutot que de tout charger d'un coup —
    necessaire des que la bibliotheque depasse quelques centaines de medias.
    """
    stmt = (
        select(LibraryItem, sqlalchemy.func.max(PlexUser.custom_name), sqlalchemy.func.max(MediaRequest.plex_user), sqlalchemy.func.max(MediaRequest.plex_user_id))
        .outerjoin(MediaRequest, MediaRequest.library_item_id == LibraryItem.id)
        .outerjoin(PlexUser, PlexUser.plex_user_id == MediaRequest.plex_user_id)
        .group_by(LibraryItem.id)
    )
    if query:
        stmt = stmt.filter(LibraryItem.title.ilike(f"%{query.strip()}%"))
    if media_type in ("movie", "show"):
        stmt = stmt.filter(LibraryItem.media_type == media_type)
    items = (
        await db.execute(
            stmt.order_by(LibraryItem.added_at.desc(), LibraryItem.title, LibraryItem.id)
            .offset(max(offset, 0))
            .limit(min(limit, 500))
        )
    ).all()
    return [
        {
            "id": row[0].id,
            "title": row[0].title,
            "year": row[0].year,
            "media_type": row[0].media_type,
            "poster_url": wrap_image_proxy(row[0].poster_url),
            "overview": row[0].overview,
            "has_vf": row[0].has_vf,
            "vf_granularity": row[0].vf_granularity,
            "arr_instance_id": row[0].arr_instance_id,
            "arr_id": row[0].arr_id,
            "added_at": row[0].added_at.isoformat() if row[0].added_at else None,
            "custom_name": row[1],
            "plex_user": row[2],
            "plex_user_id": row[3],
        }
        for row in items
    ]


@router.get("/library/{item_id}")
async def get_library_item(item_id: int, db: AsyncSession = Depends(get_db_async)):
    """Détail d'un élément de bibliothèque (pour la modale : identité + lien *arr)."""
    item = await async_get_or_404(db, LibraryItem, item_id, "Library item not found")
    from ..serializers import serialize_library_item

    return serialize_library_item(item)


@router.get("/media/detail")
async def media_detail(
    library_id: Optional[int] = None,
    request_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db_async),
):
    """Détail média unifié pour la modale Bibliothèque."""
    if not library_id and not request_id:
        raise HTTPException(400, "library_id or request_id is required")

    selected_request: Optional[MediaRequest] = None
    library_item: Optional[LibraryItem] = None
    media_obj: LibraryItem | MediaRequest
    if library_id:
        library_item = await async_get_or_404(db, LibraryItem, library_id, "Library item not found")
        media_obj = library_item
    else:
        selected_request = await async_get_or_404(db, MediaRequest, request_id, "Request not found")
        if selected_request.library_item_id:
            library_item = (await db.execute(select(LibraryItem).filter(LibraryItem.id == selected_request.library_item_id))).scalars().first()
        media_obj = library_item or selected_request

    related_requests = await _media_identity_filter(db, media_obj)
    if selected_request and selected_request.id not in {r.id for r in related_requests}:
        related_requests.insert(0, selected_request)

    all_users = (await db.execute(select(PlexUser))).scalars().all()
    users = {u.plex_user_id: (u.custom_name or u.display_name or u.plex_user_id) for u in all_users}
    user_by_id = {u.plex_user_id: u for u in all_users}
    from ..serializers import format_datetime, serialize_media_request

    request_ids_for_mail = [req.id for req in related_requests]
    last_mail_by_req: dict[int, dict] = {}
    # (req_id, event) -> adresses ayant reçu ce mail avec succès — sert à savoir, PAR
    # PERSONNE (pas juste globalement), si un demandeur/co-demandeur a déjà été notifié
    # (voir "Rattraper tout le monde" et l'indicateur par ligne dans MediaDetailDrawer).
    mail_recipients_by_req: dict[tuple[int, str], set[str]] = {}
    if request_ids_for_mail:
        mail_logs = (await db.execute(
            select(NotificationLog)
            .filter(
                NotificationLog.req_id.in_(request_ids_for_mail),
                NotificationLog.channel == "email",
                NotificationLog.event.in_(("request", "available")),
            )
            .order_by(NotificationLog.sent_at.desc())
        )).scalars().all()
        for log in mail_logs:
            key = (log.req_id, log.event)
            if key not in last_mail_by_req:
                last_mail_by_req[key] = {
                    "sent_at": format_datetime(log.sent_at),
                    "triggered_by": log.triggered_by,
                    "success": log.success,
                }
            if log.success:
                mail_recipients_by_req.setdefault(key, set()).add((log.recipient or "").strip().lower())

    def _requester_emails(plex_user_id: str) -> set[str]:
        u = user_by_id.get(plex_user_id)
        raw = (u.notification_email if u else None) or ""
        return {addr.strip().lower() for addr in raw.split(",") if addr.strip()}

    show_request_ids = [req.id for req in related_requests if req.media_type == "show"]
    seasons_by_req: dict[int, list[dict]] = {}
    if show_request_ids:
        season_rows = (await db.execute(
            select(RequestSeasonStatus).filter(RequestSeasonStatus.request_id.in_(show_request_ids))
        )).scalars().all()
        for row in season_rows:
            seasons_by_req.setdefault(row.request_id, []).append({
                "season_number": row.season_number,
                "episodes_available_count": row.episodes_available_count,
                "episodes_total_count": row.episodes_total_count,
                "status": row.status,
            })
        for rows in seasons_by_req.values():
            rows.sort(key=lambda r: r["season_number"])

    request_payloads = [serialize_media_request(req, users) for req in related_requests]
    for payload, req in zip(request_payloads, related_requests):
        payload["seasons"] = seasons_by_req.get(req.id, [])
        payload["last_request_mail"] = last_mail_by_req.get((req.id, "request"))
        payload["last_available_mail"] = last_mail_by_req.get((req.id, "available"))
        request_recipients = mail_recipients_by_req.get((req.id, "request"), set())
        available_recipients = mail_recipients_by_req.get((req.id, "available"), set())
        payload["requester_notifications"] = {
            uid: {
                "request": bool(_requester_emails(uid) & request_recipients) if _requester_emails(uid) else None,
                "available": bool(_requester_emails(uid) & available_recipients) if _requester_emails(uid) else None,
            }
            for uid in payload.get("requester_ids", [])
        }
    schedule = await _media_schedule_payload(db, media_obj)
    request_ids = [req.id for req in related_requests]
    issue_q = select(MediaIssue).filter(MediaIssue.status != "closed")
    if library_item and request_ids:
        issue_q = issue_q.filter(
            (MediaIssue.library_item_id == library_item.id) | (MediaIssue.request_id.in_(request_ids))
        )
    elif library_item:
        issue_q = issue_q.filter(MediaIssue.library_item_id == library_item.id)
    elif selected_request:
        issue_q = issue_q.filter(MediaIssue.request_id == selected_request.id)
    open_issues = (await db.execute(issue_q.order_by(MediaIssue.created_at.desc()))).scalars().all()

    backdrop_url = None
    if media_obj.tmdb_id:
        try:
            tmdb_detail = await tmdb.detail(db, media_obj.media_type, int(media_obj.tmdb_id))
            backdrop_url = tmdb_detail.get("backdrop_url")
        except Exception as e:
            logger.debug("Failed to fetch backdrop from TMDB: %s", e)

    arr_url = None
    if media_obj.arr_instance_id and media_obj.arr_slug:
        try:
            from app.models import ArrInstance
            arr_inst = (await db.execute(select(ArrInstance).filter(ArrInstance.id == media_obj.arr_instance_id))).scalars().first()
            if arr_inst:
                base_url = arr_inst.url.rstrip('/')
                if media_obj.media_type == "movie":
                    arr_url = f"{base_url}/movie/{media_obj.arr_slug}"
                else:
                    arr_url = f"{base_url}/series/{media_obj.arr_slug}"
        except Exception as e:
            logger.debug(f"Failed to build arr_url: {e}")

    return {
        "media": {
            "kind": "library" if library_item else "request",
            "library_id": library_item.id if library_item else None,
            "request_id": selected_request.id
            if selected_request
            else (related_requests[0].id if related_requests else None),
            "vf_source_type": "library" if library_item else "request",
            "vf_source_id": library_item.id if library_item else (selected_request.id if selected_request else None),
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
        },
        "requests": request_payloads,
        "issues": [_serialize_issue(issue) for issue in open_issues],
        "timeline": schedule["timeline"],
        "calendar": schedule["events"],
    }


@router.get("/library-metrics")
async def library_metrics(media_type: Optional[str] = None, db: AsyncSession = Depends(get_db_async)):
    """Compteurs rapides de la bibliotheque, exploitables par une UI ou un dashboard."""
    lib_q = select(LibraryItem)
    req_q = select(MediaRequest)
    if media_type in ("movie", "show"):
        lib_q = lib_q.filter(LibraryItem.media_type == media_type)
        req_q = req_q.filter(MediaRequest.media_type == media_type)

    library_items = (await db.execute(lib_q)).scalars().all()
    requests = (await db.execute(req_q)).scalars().all()

    def _lib_count(predicate) -> int:
        return sum(1 for item in library_items if predicate(item))

    library_ids = [item.id for item in library_items]
    secondary_rows = []
    if library_ids:
        secondary_rows = (
            await db.execute(
                select(VfEpisodeStatus).filter(
                    VfEpisodeStatus.source_type == "library_item",
                    VfEpisodeStatus.source_id.in_(library_ids),
                    VfEpisodeStatus.has_vf.is_(True),
                    VfEpisodeStatus.fr_is_default.is_(False),
                )
            )
        ).scalars().all()
    secondary_media_ids = {row.source_id for row in secondary_rows}

    status_counts = {"failed": 0, "pending": 0, "sent_to_arr": 0, "available": 0}
    for req in requests:
        status = req.status.value if hasattr(req.status, "value") else req.status
        if status in status_counts:
            status_counts[status] += 1

    plex_anomaly = sum(
        1
        for req in requests
        if (req.status.value if hasattr(req.status, "value") else req.status) == "available"
        and not req.library_item_id
        and not req.is_downloading
    )

    return {
        "media_type": media_type if media_type in ("movie", "show") else "all",
        "total": len(library_items),
        "by_type": {
            "movie": _lib_count(lambda item: item.media_type == "movie"),
            "show": _lib_count(lambda item: item.media_type == "show"),
        },
        "vf": {
            "complete": _lib_count(lambda item: item.has_vf is True),
            "pending": _lib_count(lambda item: item.has_vf is False),
            "unchecked": _lib_count(lambda item: item.has_vf is None),
            "season_partial": _lib_count(lambda item: item.has_vf is False and item.vf_granularity == "season_partial"),
            "episode_partial": _lib_count(
                lambda item: item.has_vf is False and item.vf_granularity == "episode_partial"
            ),
            "secondary_default": {
                "media": len(secondary_media_ids),
                "episodes": len(secondary_rows),
            },
        },
        "requests": {
            "total": len(requests),
            "by_status": status_counts,
        },
        "plex_anomaly": plex_anomaly,
    }














@router.post("/media/recheck-plex")
async def recheck_plex(
    request_id: Optional[int] = None,
    library_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db_async),
    _: None = Depends(require_admin),
):
    """Revérifie si un média (souvent une « anomalie Plex ») est désormais indexé par Plex.

    Cas d'usage : Sonarr/Radarr a bien importé le fichier (demande « disponible »)
    mais Plex ne le trouvait pas. On relance une recherche ciblée (GUID > IDs
    externes > titre) dans les bibliothèques configurées ; si le média est trouvé,
    on crée le LibraryItem correspondant et on y rattache les demandes — il cesse
    alors d'être une anomalie.
    """
    import asyncio

    from ..services.plex_sync import _find_library_item_by_ids
    from ..services.plex_finder import connect, find_item_in_libraries
    from ..services.vff_scanner import _parse_vff_libraries
    from ..utils import now_utc_naive

    if not request_id and not library_id:
        raise HTTPException(400, "request_id or library_id is required")

    if library_id:
        await async_get_or_404(db, LibraryItem, library_id, "Library item not found")
        return {"found": True, "already_in_library": True, "library_id": library_id}
    media = await async_get_or_404(db, MediaRequest, request_id, "Request not found")

    settings = (await db.execute(select(Settings))).scalars().first()
    if not settings or not settings.plex_url or not settings.plex_token:
        raise HTTPException(400, "Plex non configuré")
    libs = _parse_vff_libraries(settings)
    if not libs:
        raise HTTPException(400, "Aucune bibliothèque Plex configurée")

    if media.media_type == "movie":
        lib_names = [lib["name"] for lib in libs if lib["kind"] == "movie"]
    else:
        lib_names = [lib["name"] for lib in libs if lib["kind"] in ("series", "anime")]

    def _search():
        plex = connect(settings.plex_url, settings.plex_token)
        return find_item_in_libraries(
            plex,
            lib_names,
            media.title,
            media.year,
            media.tmdb_id,
            media.tvdb_id,
            media.imdb_id,
            plex_guid=media.plex_guid,
        )

    try:
        found = await asyncio.to_thread(_search)
    except Exception as e:
        logger.warning(f"Recheck Plex échoué pour {media.title!r}: {e}")
        raise HTTPException(502, f"Erreur de connexion Plex : {e}")

    if not found:
        return {"found": False}

    # Extraire les identifiants externes du média Plex trouvé
    tmdb_id = tvdb_id = imdb_id = None
    for g in getattr(found, "guids", []) or []:
        gid = g.id or ""
        if gid.startswith("tmdb://"):
            tmdb_id = gid.split("tmdb://")[-1]
        elif gid.startswith("tvdb://"):
            tvdb_id = gid.split("tvdb://")[-1]
        elif gid.startswith("imdb://"):
            imdb_id = gid.split("imdb://")[-1]
    plex_guid = getattr(found, "guid", None)
    now = now_utc_naive()

    lib_item = await _find_library_item_by_ids(
        db, plex_guid, tmdb_id, tvdb_id, imdb_id, found.title, getattr(found, "year", None), media.media_type
    )
    if not lib_item:
        thumb = getattr(found, "thumb", None)
        added = getattr(found, "addedAt", None)
        if added and added.tzinfo:
            added = added.replace(tzinfo=None)
        lib_item = LibraryItem(
            title=found.title,
            year=getattr(found, "year", None),
            media_type=media.media_type,
            tmdb_id=tmdb_id,
            tvdb_id=tvdb_id,
            imdb_id=imdb_id,
            plex_guid=plex_guid,
            poster_url=(
                f"{settings.plex_url.rstrip('/')}{thumb}?X-Plex-Token={settings.plex_token}"
                if thumb
                else media.poster_url
            ),
            overview=getattr(found, "summary", None) or media.overview,
            added_at=added,
            arr_instance_id=media.arr_instance_id,
            arr_id=media.arr_id,
            arr_slug=media.arr_slug,
            has_vf=None,
            created_at=now,
            updated_at=now,
        )
        db.add(lib_item)
        await db.flush()

    # Rattacher toutes les demandes qui représentent ce média
    for req in await _media_identity_filter(db, lib_item):
        req.library_item_id = lib_item.id
    if media.library_item_id != lib_item.id:
        media.library_item_id = lib_item.id
    await db.commit()

    return {"found": True, "library_id": lib_item.id}


@router.get("/media/capabilities")
async def media_capabilities(db: AsyncSession = Depends(get_db_async)):
    """Retourne les services disponibles pour orienter le flux de recherche côté frontend."""
    s = (await db.execute(select(Settings))).scalars().first()
    instances = (await db.execute(select(ArrInstance).filter(ArrInstance.enabled))).scalars().all()
    arr_types = {i.arr_type for i in instances}
    return {
        "has_sonarr": "sonarr" in arr_types,
        "has_radarr": "radarr" in arr_types,
        "has_prowlarr": "prowlarr" in arr_types,
        "has_seer": bool(s and s.seer_send_requests and s.seer_url and s.seer_api_key),
        "seer_fallback_arr": bool(s and s.seer_fallback_arr),
    }


@router.get("/media/lookup")
async def media_lookup(query: str, type: str = "movie", db: AsyncSession = Depends(get_db_async)):
    """Cherche un titre via l'API Sonarr ou Radarr et retourne les métadonnées enrichies."""
    instances = (await db.execute(select(ArrInstance).filter(ArrInstance.enabled))).scalars().all()
    arr_type = "sonarr" if type == "show" else "radarr"
    inst = next((i for i in instances if i.arr_type == arr_type and i.is_default), None)
    if not inst:
        inst = next((i for i in instances if i.arr_type == arr_type), None)

    if not inst:
        return []

    base = inst.url.rstrip("/")
    headers = {"X-Api-Key": inst.api_key}
    endpoint = "/api/v3/series/lookup" if arr_type == "sonarr" else "/api/v3/movie/lookup"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{base}{endpoint}", params={"term": query}, headers=headers)
            r.raise_for_status()
            results = r.json()
    except Exception as e:
        logger.warning(f"Media lookup failed ({arr_type}): {e}")
        return []

    def _poster(item: dict) -> Optional[str]:
        for img in item.get("images", []):
            if img.get("coverType") == "poster":
                remote = img.get("remoteUrl") or img.get("url", "")
                if remote:
                    return remote
        return None

    normalized = []
    for item in results[:10]:
        if arr_type == "sonarr":
            normalized.append(
                {
                    "title": item.get("title", ""),
                    "year": item.get("year"),
                    "overview": item.get("overview", ""),
                    "poster": _poster(item),
                    "tvdb_id": item.get("tvdbId"),
                    "tmdb_id": None,
                    "media_type": "show",
                    "already_added": item.get("id") is not None,
                    "arr_id": item.get("id"),
                    "arr_instance_id": inst.id,
                    "status": item.get("status", ""),
                }
            )
        else:
            normalized.append(
                {
                    "title": item.get("title", ""),
                    "year": item.get("year"),
                    "overview": item.get("overview", ""),
                    "poster": _poster(item),
                    "tmdb_id": item.get("tmdbId"),
                    "tvdb_id": None,
                    "media_type": "movie",
                    "already_added": item.get("id") is not None,
                    "arr_id": item.get("id"),
                    "arr_instance_id": inst.id,
                    "status": item.get("status", ""),
                }
            )
    return normalized


async def _needs_approval(
    db: AsyncSession, settings: Optional[Settings], caller: Optional[dict], plex_user_id: Optional[str]
) -> bool:
    """Détermine si une demande doit passer par la file de validation admin.

    Jamais pour un admin/owner (ni un appel token API). Sinon uniquement si
    l'approbation est activée globalement ET que l'utilisateur n'est pas auto-approuvé.
    """
    if not caller or caller.get("is_owner") or caller.get("role") == "admin":
        return False
    if not (settings and settings.require_approval):
        return False
    if plex_user_id:
        pu = (await db.execute(select(PlexUser).filter(PlexUser.plex_user_id == plex_user_id))).scalars().first()
        if pu and pu.auto_approve:
            return False
    return True


async def _create_pending_request(db: AsyncSession, body: "MediaAddRequest") -> dict:
    """Enregistre une demande en attente de validation (aucune soumission à *arr)."""
    tmdb_str = str(body.tmdb_id) if body.tmdb_id else None
    tvdb_str = str(body.tvdb_id) if body.tvdb_id else None

    existing = None
    if tmdb_str:
        existing = (await db.execute(select(MediaRequest).filter(MediaRequest.tmdb_id == tmdb_str))).scalars().first()
    if not existing and tvdb_str:
        existing = (await db.execute(select(MediaRequest).filter(MediaRequest.tvdb_id == tvdb_str))).scalars().first()
    if not existing and not tmdb_str and not tvdb_str:
        existing = (
            await db.execute(
                select(MediaRequest).filter(
                    MediaRequest.title == body.title, MediaRequest.media_type == body.media_type
                )
            )
        ).scalars().first()
    if existing:
        # Média déjà connu : on ne recrée pas de doublon en attente.
        return {"ok": True, "pending_approval": True, "already_existed": True, "id": existing.id}

    user_id = body.plex_user_id or "manual"
    user_label = user_id
    pu = (await db.execute(select(PlexUser).filter(PlexUser.plex_user_id == user_id))).scalars().first()
    if pu:
        user_label = pu.custom_name or pu.display_name or pu.plex_user_id

    req = MediaRequest(
        plex_user_id=user_id,
        plex_user=user_label,
        title=body.title,
        year=body.year,
        media_type=body.media_type,
        tmdb_id=tmdb_str,
        tvdb_id=tvdb_str,
        imdb_id=body.imdb_id,
        status=RequestStatus.pending_approval,
        source="user_request",
        poster_url=body.poster_url,
        overview=body.overview,
        requested_at=now_utc_naive(),
    )
    db.add(req)
    await db.commit()
    return {"ok": True, "pending_approval": True, "already_existed": False, "id": req.id}


@router.post("/media/add")
async def media_add(body: MediaAddRequest, request: Request, db: AsyncSession = Depends(get_db_async)):
    """Ajoute un média via Seer (prioritaire) ou directement dans Sonarr/Radarr.

    Contrôle d'accès : un utilisateur 'user' ne peut demander que pour lui-même
    (le plex_user_id de la session prime sur le corps de requête). Si l'approbation
    est activée et que cet utilisateur n'est pas auto-approuvé, la demande est mise
    en file d'attente (pending_approval) sans être envoyée à *arr.
    """
    s = (await db.execute(select(Settings))).scalars().first()
    item = body.model_dump()

    caller = current_user(request, db)
    caller_is_admin = bool(caller and (caller.get("is_owner") or caller.get("role") == "admin"))
    if not caller_is_admin and caller and caller.get("plex_user_id"):
        # Un 'user' demande forcément pour lui-même : on ignore body.plex_user_id.
        body.plex_user_id = caller["plex_user_id"]
        item["plex_user_id"] = caller["plex_user_id"]

    pending = await _needs_approval(db, s, caller, body.plex_user_id)
    if pending:
        return await _create_pending_request(db, body)

    arr_id = None
    already = False
    via = None
    chosen_instance_id = None  # instance *arr choisie (pour le suivi de statut)
    chosen_slug = None

    seer_eligible = s and s.seer_send_requests and s.seer_url and s.seer_api_key
    if not body.bypass_seer and (body.use_seer or (not body.instance_id and seer_eligible)):
        if not seer_eligible:
            raise HTTPException(400, "Seer n'est pas configuré.")
        try:
            seer_id, already, _ = await seer_service.request_media(s.seer_url, s.seer_api_key, item)
            arr_id = seer_id
            via = "seer"
        except Exception as e:
            if body.use_seer or not s.seer_fallback_arr:
                raise HTTPException(502, f"Erreur Seer : {e}")
            logger.warning(f"Seer failed, falling back to arr: {e}")

    if via is None:
        instances = (await db.execute(select(ArrInstance).filter(ArrInstance.enabled))).scalars().all()
        arr_type = "sonarr" if body.media_type == "show" else "radarr"

        if body.instance_id:
            inst = next((i for i in instances if i.id == body.instance_id and i.arr_type == arr_type), None)
            if not inst:
                raise HTTPException(400, f"Instance {body.instance_id} introuvable ou désactivée.")
        else:
            inst = next((i for i in instances if i.arr_type == arr_type and i.is_default), None)
            if not inst:
                inst = next((i for i in instances if i.arr_type == arr_type), None)

        if not inst:
            raise HTTPException(400, "Aucune instance Sonarr/Radarr configurée et Seer non activé.")

        base = inst.url.rstrip("/")
        headers = {"X-Api-Key": inst.api_key}

        qp_id = body.quality_profile_id
        rf = body.root_folder
        if not qp_id or not rf:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    if not qp_id:
                        qp_resp = await client.get(f"{base}/api/v3/qualityprofile", headers=headers)
                        profiles = qp_resp.json()
                        qp_id = profiles[0]["id"] if profiles else 1
                    if not rf:
                        rf_resp = await client.get(f"{base}/api/v3/rootfolder", headers=headers)
                        folders = rf_resp.json()
                        rf = folders[0]["path"] if folders else "/"
            except Exception as e:
                raise HTTPException(502, f"Impossible de récupérer la config {arr_type}: {e}")

        search_triggered = False
        try:
            if arr_type == "sonarr":
                item["seasons"] = body.seasons
                arr_id, already, chosen_slug = await sonarr.add_series(
                    inst.url, inst.api_key, qp_id, rf, item, tag_ids=body.tag_ids
                )
                if already and body.auto_search and isinstance(arr_id, int):
                    search_triggered = await sonarr.search_series(inst.url, inst.api_key, arr_id)
                elif body.auto_search and not already:
                    search_triggered = True
            else:
                arr_id, already, chosen_slug = await radarr.add_movie(
                    inst.url, inst.api_key, qp_id, rf, item, tag_ids=body.tag_ids
                )
                if already and body.auto_search and isinstance(arr_id, int):
                    search_triggered = await radarr.search_movie(inst.url, inst.api_key, arr_id)
                elif body.auto_search and not already:
                    search_triggered = True
            via = arr_type
            chosen_instance_id = inst.id
        except Exception as e:
            raise HTTPException(502, f"Erreur {arr_type} : {e}")
    else:
        search_triggered = False

    tmdb_str = str(body.tmdb_id) if body.tmdb_id else None
    tvdb_str = str(body.tvdb_id) if body.tvdb_id else None
    # Priorité aux identifiants certains (tmdb/tvdb) ; le titre n'est utilisé qu'en
    # dernier recours, quand aucun identifiant n'est disponible.
    existing = None
    if tmdb_str:
        existing = (await db.execute(select(MediaRequest).filter(MediaRequest.tmdb_id == tmdb_str))).scalars().first()
    if tvdb_str and not existing:
        existing = (await db.execute(select(MediaRequest).filter(MediaRequest.tvdb_id == tvdb_str))).scalars().first()
    if not existing and not tmdb_str and not tvdb_str:
        existing = (
            await db.execute(
                select(MediaRequest).filter(
                    MediaRequest.title == body.title,
                    MediaRequest.media_type == body.media_type,
                )
            )
        ).scalars().first()

    # Source de suivi : "seer" → suivi par seer_sync (interroge Overseerr) ;
    # sinon → suivi par check_arr_statuses via l'instance *arr enregistrée.
    source_val = "seer" if via == "seer" else "manual_search"

    if not existing:
        user_id = body.plex_user_id or "manual"
        user_label = "Recherche manuelle"
        if body.plex_user_id:
            pu = (await db.execute(select(PlexUser).filter(PlexUser.plex_user_id == body.plex_user_id))).scalars().first()
            if pu:
                user_label = pu.display_name or pu.plex_user_id
        req = MediaRequest(
            plex_user_id=user_id,
            plex_user=user_label,
            title=body.title,
            year=body.year,
            media_type=body.media_type,
            tmdb_id=tmdb_str,
            tvdb_id=tvdb_str,
            imdb_id=body.imdb_id,
            status=RequestStatus.sent_to_arr,
            source=source_val,
            arr_id=arr_id if isinstance(arr_id, int) else None,
            arr_slug=chosen_slug,
            arr_instance_id=chosen_instance_id,
            poster_url=body.poster_url,
            overview=body.overview,
        )
        db.add(req)
        await db.commit()
        update_request_context(req, request_source=source_val)
        await record_event(
            db,
            category="request",
            action="created",
            request=req,
            message="Demande créée.",
            details={"source": source_val, "tmdb_id": tmdb_str, "tvdb_id": tvdb_str, "imdb_id": body.imdb_id},
        )
        await db.commit()
        if s:
            await _notify("request", s, req, db)
    else:
        # Ré-attache le contexte de suivi à une demande existante qui n'en avait pas
        # (ancienne demande manuelle, ou média re-demandé), pour que le statut repasse.
        if chosen_instance_id and not existing.arr_instance_id:
            existing.arr_instance_id = chosen_instance_id
        if chosen_slug and not existing.arr_slug:
            existing.arr_slug = chosen_slug
        if isinstance(arr_id, int) and not existing.arr_id:
            existing.arr_id = arr_id
        if via == "seer" and existing.source != "seer":
            existing.source = "seer"
        if body.poster_url and not existing.poster_url:
            existing.poster_url = body.poster_url
        if body.overview and not existing.overview:
            existing.overview = body.overview
        # Ré-attribue un demandeur réel si la demande était orpheline ("manual")
        if body.plex_user_id and existing.plex_user_id == "manual":
            existing.plex_user_id = body.plex_user_id
            pu = (await db.execute(select(PlexUser).filter(PlexUser.plex_user_id == body.plex_user_id))).scalars().first()
            existing.plex_user = (pu.display_name or pu.plex_user_id) if pu else body.plex_user_id
        if existing.status in (RequestStatus.failed, RequestStatus.pending):
            existing.status = RequestStatus.sent_to_arr
        await db.commit()
        if s:
            await _notify("request", s, existing, db)

    return {"ok": True, "via": via, "already_existed": already, "id": arr_id, "search_triggered": search_triggered}
