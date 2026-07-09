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
    requester_ids = [req.plex_user_id]
    extras = []
    try:
        extras = _json.loads(req.extra_requesters or "[]")
        for extra in extras:
            uid = extra.get("plex_user_id")
            if uid:
                requester_ids.append(uid)
                extra["display_name"] = users.get(uid, extra.get("display_name") or uid)
    except Exception:
        extras = []
    requesters = [users.get(uid, uid) for uid in requester_ids]
    return {
        "id": req.id,
        "title": req.title,
        "year": req.year,
        "media_type": req.media_type,
        "status": request_status_value(req.status),
        "source": req.source,
        "plex_user_id": req.plex_user_id,
        "plex_user": users.get(req.plex_user_id, req.plex_user or req.plex_user_id),
        "requester_ids": requester_ids,
        "requesters": requesters,
        "requested_by": ", ".join(requesters),
        "extra_requesters": _json.dumps(extras),
        "requested_at": format_datetime(req.requested_at),
        "available_at": format_datetime(req.available_at),
        "request_mail_sent": req.request_mail_sent,
        "available_mail_sent": req.available_mail_sent,
        "overview": req.overview,
        "has_vf": req.has_vf,
        "arr_id": req.arr_id,
        "arr_slug": req.arr_slug,
        "arr_instance_id": req.arr_instance_id,
        "library_item_id": req.library_item_id,
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
