import json as _json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_auth
from ..models import ArrInstance, LibraryItem, MediaRequest, RequestStatus, Settings
from ..services import radarr, sonarr
from ..utils import now_utc, now_utc_naive

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["calendar"], dependencies=[Depends(require_auth)])


@router.get("/upcoming")
def upcoming_releases(db: Session = Depends(get_db), limit: int = 8):
    """Retourne les prochaines sorties parmi les demandes transmises mais pas encore disponibles."""
    rows = (
        db.query(MediaRequest)
        .filter(
            MediaRequest.status == RequestStatus.sent_to_arr,
            MediaRequest.next_release_at.isnot(None),
            MediaRequest.next_release_at > now_utc_naive(),
        )
        .order_by(MediaRequest.next_release_at.asc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "title": r.title,
            "media_type": r.media_type,
            "poster_url": r.poster_url,
            "release_date": r.next_release_at.isoformat(),
            "label": r.next_release_label,
        }
        for r in rows
    ]


def _parse_arr_date(value: str):
    """Parse une date ISO renvoyée par Sonarr/Radarr (gère le suffixe 'Z') en datetime aware."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None


def _arr_poster(entity: dict) -> Optional[str]:
    """Extrait l'URL d'affiche (poster) d'une ressource Sonarr/Radarr."""
    for img in entity.get("images") or []:
        if img.get("coverType") == "poster":
            return img.get("remoteUrl") or img.get("url")
    return None


def _movie_release_events(movie: dict, start_dt: datetime, end_dt: datetime, now: datetime) -> list[tuple]:
    """Événements de sortie d'un film pour le calendrier : (date_iso, type, sous-titre)."""
    specs = (
        ("cinema", "Sortie cinéma", movie.get("inCinemas")),
        ("digital", "Sortie digitale", movie.get("digitalRelease")),
        ("physical", "Sortie physique", movie.get("physicalRelease")),
    )
    parsed = [
        (raw, rtype, label, dt)
        for rtype, label, raw in specs
        if raw and (dt := _parse_arr_date(raw)) is not None
    ]
    if not parsed:
        return []
    in_window = sorted(
        ((raw, rtype, label) for raw, rtype, label, dt in parsed if start_dt <= dt <= end_dt),
        key=lambda x: x[0],
    )
    if in_window:
        return in_window
    future = [(raw, rtype, label, dt) for raw, rtype, label, dt in parsed if dt >= now]
    raw, rtype, label, _ = min(future, key=lambda x: x[3]) if future else max(parsed, key=lambda x: x[3])
    return [(raw, rtype, label)]


def _calendar_entry_excluded(tracked, *, search_text, search_target, user, status, source, vf) -> bool:
    """True si l'entrée doit être exclue selon les filtres avancés (hors type/tracked_only)."""
    if search_text and search_text.lower() not in (search_target or "").lower():
        return True
    if user and (not tracked or user not in tracked.get("requested_by_ids", [])):
        return True
    if status and (not tracked or tracked.get("request_status") != status):
        return True
    if source and (not tracked or source not in tracked.get("request_sources", [])):
        return True
    if vf:
        if not tracked:
            return True
        if vf == "vf" and not (tracked.get("in_library") and tracked.get("has_vf") is True):
            return True
        if vf == "vo" and not (tracked.get("in_library") and tracked.get("has_vf") is False):
            return True
        if vf == "unchecked" and not (tracked.get("in_library") and tracked.get("has_vf") is None):
            return True
        if vf == "requested" and tracked.get("in_library"):
            return True
    return False


@router.get("/calendar")
async def unified_calendar(
    start: Optional[str] = None,
    end: Optional[str] = None,
    tracked_only: bool = False,
    type: Optional[str] = None,
    search: Optional[str] = None,
    user: Optional[str] = None,
    status: Optional[str] = None,
    vf: Optional[str] = None,
    source: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Calendrier unifié : épisodes Sonarr + sorties Radarr sur une plage de dates."""
    now = now_utc()
    start_dt = datetime.fromisoformat(start) if start else now - timedelta(days=7)
    end_dt = datetime.fromisoformat(end) if end else now + timedelta(days=21)

    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)

    shows_by_tvdb: dict[str, dict] = {}
    movies_by_tmdb: dict[str, dict] = {}
    library_items_by_id = {}

    for li in db.query(LibraryItem).all():
        entry = {
            "in_library": True,
            "library_item_id": li.id,
            "request_id": None,
            "request_status": None,
            "requested_by_ids": [],
            "request_sources": [],
            "has_vf": li.has_vf,
            "poster_url": li.poster_url,
        }
        library_items_by_id[li.id] = entry
        if li.media_type == "show" and li.tvdb_id:
            shows_by_tvdb[li.tvdb_id] = entry
        elif li.media_type == "movie" and li.tmdb_id:
            movies_by_tmdb[li.tmdb_id] = entry

    for r in db.query(MediaRequest).all():
        matched = library_items_by_id.get(r.library_item_id) if r.library_item_id else None
        if not matched:
            if r.media_type == "show" and r.tvdb_id:
                matched = shows_by_tvdb.get(r.tvdb_id)
            elif r.media_type == "movie" and r.tmdb_id:
                matched = movies_by_tmdb.get(r.tmdb_id)

        status_val = r.status.value if hasattr(r.status, "value") else str(r.status)
        requester_ids = [r.plex_user_id] if r.plex_user_id else []
        try:
            for extra in _json.loads(r.extra_requesters or "[]"):
                uid = extra.get("plex_user_id")
                if uid and uid not in requester_ids:
                    requester_ids.append(uid)
        except Exception:
            pass

        if matched:
            matched["request_id"] = r.id
            matched["request_status"] = status_val
            matched["requested_by_ids"] = list(set(matched["requested_by_ids"] + requester_ids))
            if r.source and r.source not in matched["request_sources"]:
                matched["request_sources"].append(r.source)
        else:
            entry = {
                "in_library": False,
                "library_item_id": None,
                "request_id": r.id,
                "request_status": status_val,
                "requested_by_ids": requester_ids,
                "request_sources": [r.source] if r.source else [],
                "has_vf": r.has_vf,
                "poster_url": r.poster_url,
            }
            if r.media_type == "show" and r.tvdb_id:
                shows_by_tvdb[r.tvdb_id] = entry
            elif r.media_type == "movie" and r.tmdb_id:
                movies_by_tmdb[r.tmdb_id] = entry

    instances = db.query(ArrInstance).filter(ArrInstance.enabled, ArrInstance.arr_type.in_(["sonarr", "radarr"])).all()
    events = []
    for inst in instances:
        try:
            if inst.arr_type == "sonarr":
                episodes = await sonarr.get_calendar(inst.url, inst.api_key, start_dt.isoformat(), end_dt.isoformat())
                for ep in episodes:
                    date = ep.get("airDateUtc")
                    if not date:
                        continue
                    series = ep.get("series") or {}
                    tvdb_id = str(series.get("tvdbId")) if series.get("tvdbId") else None
                    tracked = shows_by_tvdb.get(tvdb_id) if tvdb_id else None
                    if tracked_only and not tracked:
                        continue

                    # Filtres
                    if type == "movie":
                        continue
                    if _calendar_entry_excluded(
                        tracked,
                        search_text=search,
                        search_target=series.get("title"),
                        user=user,
                        status=status,
                        source=source,
                        vf=vf,
                    ):
                        continue

                    events.append({
                        "type": "episode",
                        "release_type": "episode",
                        "date": date,
                        "title": series.get("title") or "",
                        "subtitle": f"S{ep.get('seasonNumber', 0):02d}E{ep.get('episodeNumber', 0):02d}"
                        + (f" — {ep.get('title')}" if ep.get("title") else ""),
                        "poster_url": (tracked or {}).get("poster_url") or _arr_poster(series),
                        "has_file": bool(ep.get("hasFile")),
                        "tracked": bool(tracked),
                        "library_item_id": (tracked or {}).get("library_item_id"),
                        "request_id": (tracked or {}).get("request_id"),
                        "instance": inst.name,
                    })
            else:
                movies = await radarr.get_calendar(inst.url, inst.api_key, start_dt.isoformat(), end_dt.isoformat())
                for m in movies:
                    release_events = _movie_release_events(m, start_dt, end_dt, now)
                    if not release_events:
                        continue
                    tmdb_id = str(m.get("tmdbId")) if m.get("tmdbId") else None
                    tracked = movies_by_tmdb.get(tmdb_id) if tmdb_id else None
                    if tracked_only and not tracked:
                        continue

                    # Filtres
                    if type == "show":
                        continue
                    title = m.get("title") or ""
                    if _calendar_entry_excluded(
                        tracked,
                        search_text=search,
                        search_target=title,
                        user=user,
                        status=status,
                        source=source,
                        vf=vf,
                    ):
                        continue

                    poster = (tracked or {}).get("poster_url") or _arr_poster(m)
                    for rdate, rtype, rlabel in release_events:
                        events.append({
                            "type": "movie",
                            "release_type": rtype,
                            "date": rdate,
                            "title": title,
                            "subtitle": rlabel,
                            "poster_url": poster,
                            "has_file": bool(m.get("hasFile")),
                            "tracked": bool(tracked),
                            "library_item_id": (tracked or {}).get("library_item_id"),
                            "request_id": (tracked or {}).get("request_id"),
                            "instance": inst.name,
                        })
        except Exception as e:
            logger.warning(f"Calendar fetch failed for '{inst.name}': {e}")

    events.sort(key=lambda e: e["date"])
    return events
