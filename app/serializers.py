import json as _json
from datetime import datetime, timezone
from typing import Any, Optional

from .models import LibraryItem, MediaRequest, PlexUser


def format_datetime(dt: Optional[datetime]) -> Optional[str]:
    """Force timezone info to UTC for serialization, resolving timezone offset issues in client-side JS."""
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat()
    return dt.isoformat()


def request_status_value(status: Any) -> str:
    return status.value if hasattr(status, "value") else str(status)


def serialize_media_request(req: MediaRequest, users: dict[str, str]) -> dict:
    from .services.operational_projection import request_operational_projection

    # Deduplique par plex_user_id : quelques lignes historiques ont le demandeur
    # principal redondant dans extra_requesters (donnee corrompue anterieure a la
    # garde de _add_co_requester), ce qui produisait des requester_ids en double —
    # cassant le :key du v-for cote frontend (MediaDetailDrawer.vue) et empechant le
    # rendu de la fiche detail pour ces demandes.
    seen_ids: set[str] = {req.plex_user_id}
    requester_ids = [req.plex_user_id]
    extras = []
    try:
        for extra in _json.loads(req.extra_requesters or "[]"):
            uid = extra.get("plex_user_id")
            if uid and uid not in seen_ids:
                seen_ids.add(uid)
                extra["display_name"] = users.get(uid, extra.get("display_name") or uid)
                extras.append(extra)
                requester_ids.append(uid)
    except Exception:
        extras = []
    requesters = [users.get(uid, uid) for uid in requester_ids]
    return {
        "id": req.id,
        "title": req.title,
        "year": req.year,
        "media_type": req.media_type,
        "status": request_status_value(req.status),
        "fulfillment_status": request_status_value(req.fulfillment_status),
        "fulfillment_updated_at": format_datetime(req.fulfillment_updated_at),
        "fulfillment_error": req.fulfillment_error,
        "source": req.source,
        "plex_user_id": req.plex_user_id,
        "plex_user": users.get(req.plex_user_id, req.plex_user or req.plex_user_id),
        "requester_ids": requester_ids,
        "requesters": requesters,
        "requested_by": ", ".join(requesters),
        "extra_requesters": _json.dumps(extras),
        "requested_at": format_datetime(req.requested_at),
        "arr_processed_at": format_datetime(req.arr_processed_at),
        "available_at": format_datetime(req.available_at),
        "request_mail_sent": req.request_mail_sent,
        "available_mail_sent": req.available_mail_sent,
        "overview": req.overview,
        "has_vf": req.has_vf,
        "vf_tracking_disabled": req.vf_tracking_disabled,
        "arr_id": req.arr_id,
        "arr_slug": req.arr_slug,
        "arr_instance_id": req.arr_instance_id,
        "library_item_id": req.library_item_id,
        "is_downloading": req.is_downloading,
        "torrent_name": req.torrent_name,
        "torrent_content_path": req.torrent_content_path,
        "torrent_completed_at": format_datetime(req.torrent_completed_at),
        "torrent_import_verified_at": format_datetime(req.torrent_import_verified_at),
        **request_operational_projection(req),
    }


def serialize_library_item(item: LibraryItem) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "year": item.year,
        "media_type": item.media_type,
        "has_vf": item.has_vf,
        "arr_id": item.arr_id,
        "arr_instance_id": item.arr_instance_id,
        "arr_slug": item.arr_slug,
    }


def serialize_plex_user(user: PlexUser, stats: dict) -> dict:
    data = {c.name: getattr(user, c.name) for c in user.__table__.columns}
    data.pop("password_hash", None)
    data.pop("totp_secret", None)
    data["has_local_password"] = bool(user.password_hash)
    data["last_requested_at"] = format_datetime(stats.pop("last_requested_at", None))
    data["stats"] = stats
    return data
