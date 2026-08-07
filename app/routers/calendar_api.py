import asyncio
import json as _json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..cache import cache
from ..database import AsyncSessionLocal, get_db_async
from ..dependencies import require_auth
from ..models import ArrInstance, LibraryItem, MediaRequest, RequestStatus, Settings
from ..services import radarr, sonarr
from ..utils import now_utc, now_utc_naive, wrap_image_proxy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["calendar"], dependencies=[Depends(require_auth)])


@router.get("/upcoming")
async def upcoming_releases(db: AsyncSession = Depends(get_db_async), limit: int = 8):
    """Retourne les prochaines sorties parmi les demandes transmises mais pas encore disponibles.

    Inclut aussi les séries `partially_available` (en cours de diffusion) : une série
    dont certains épisodes sont déjà disponibles a quand même un prochain épisode à
    venir, alimenté par `next_release_at` (voir `_refresh_next_release`). S'en tenir à
    `sent_to_arr` exclurait quasi toutes les séries suivies, qui quittent ce statut dès
    le premier épisode importé.
    """
    rows = (
        await db.execute(
            select(MediaRequest)
            .filter(
                MediaRequest.status.in_([RequestStatus.sent_to_arr, RequestStatus.partially_available]),
                MediaRequest.next_release_at.isnot(None),
                MediaRequest.next_release_at > now_utc_naive(),
            )
            .order_by(MediaRequest.next_release_at.asc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "media_type": r.media_type,
            "poster_url": wrap_image_proxy(r.poster_url),
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


def _arr_poster(entity: dict, inst_url: str) -> Optional[str]:
    """Extrait l'URL d'affiche (poster) d'une ressource Sonarr/Radarr."""
    for img in entity.get("images") or []:
        if str(img.get("coverType") or "").lower() == "poster":
            url = img.get("remoteUrl") or img.get("url")
            if url:
                if url.startswith("/"):
                    url = f"{inst_url.rstrip('/')}{url}"
                return wrap_image_proxy(url)
    return None


def _arr_fanart(entity: dict, inst_url: str) -> Optional[str]:
    """Extrait l'URL d'arrière-plan (fanart/backdrop) d'une ressource Sonarr/Radarr."""
    for img in entity.get("images") or []:
        if str(img.get("coverType") or "").lower() in ("fanart", "backdrop", "banner"):
            url = img.get("remoteUrl") or img.get("url")
            if url:
                if url.startswith("/"):
                    url = f"{inst_url.rstrip('/')}{url}"
                return wrap_image_proxy(url)
    return None


def _arr_rating(entity: dict) -> Optional[float]:
    """Extrait la note moyenne d'une ressource Sonarr/Radarr."""
    ratings = entity.get("ratings") or {}
    if isinstance(ratings, dict):
        val = ratings.get("value") or (ratings.get("imdb") or {}).get("value") or (ratings.get("tmdb") or {}).get("value")
        if val:
            try:
                return round(float(val), 1)
            except (ValueError, TypeError):
                pass
    return None


def _arr_genres(entity: dict) -> list[str]:
    """Extrait la liste des genres (max 3)."""
    genres = entity.get("genres") or []
    if isinstance(genres, list):
        return [str(g) for g in genres[:3]]
    return []


def _movie_release_events(movie: dict, start_dt: datetime, end_dt: datetime, now: datetime) -> list[tuple]:
    """Événements de sortie d'un film pour le calendrier : (date_iso, type, sous-titre)."""
    specs = (
        ("cinema", "Sortie cinéma", movie.get("inCinemas")),
        ("digital", "Sortie digitale", movie.get("digitalRelease")),
        ("physical", "Sortie physique", movie.get("physicalRelease")),
    )
    parsed = [
        (raw, rtype, label, dt) for rtype, label, raw in specs if raw and (dt := _parse_arr_date(raw)) is not None
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


_CALENDAR_SOFT_TTL = 45
_CALENDAR_HARD_TTL = 600


def _calendar_cache_key(start: Optional[str], end: Optional[str]) -> str:
    return f"plexarr:calendar:raw:v2:{start or ''}|{end or ''}"


def _filter_calendar_events(
    events: list[dict], tracked_only: bool, type: Optional[str], search: Optional[str],
    user: Optional[str], status: Optional[str], vf: Optional[str], source: Optional[str],
) -> list[dict]:
    filtered = []
    for event in events:
        tracking = event.get("_tracking") or {}
        if tracked_only and not tracking.get("originally_tracked"):
            continue
        if type == "movie" and event.get("type") != "movie":
            continue
        if type == "show" and event.get("type") != "episode":
            continue
        if _calendar_entry_excluded(
            tracking,
            search_text=search,
            search_target=event.get("title"),
            user=user,
            status=status,
            source=source,
            vf=vf,
        ):
            continue
        filtered.append({key: value for key, value in event.items() if key != "_tracking"})
    return filtered


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
    db: AsyncSession = Depends(get_db_async),
):
    """Calendrier unifié : épisodes Sonarr + sorties Radarr sur une plage de dates.

    Mis en cache (stale-while-revalidate, voir cache.py) : interroge Sonarr ET Radarr
    en direct pour chaque instance a chaque appel, sans quoi le calendrier bloquait
    derriere ces appels a chaque changement de mois/filtre.
    """
    key = _calendar_cache_key(start, end)

    async def _background():
        async with AsyncSessionLocal() as fresh_db:
            return await _compute_calendar(fresh_db, start, end, False, None, None, None, None, None, None)

    raw_events = await cache.get_or_refresh(
        key, _CALENDAR_SOFT_TTL, _CALENDAR_HARD_TTL,
        compute_sync=lambda: _compute_calendar(db, start, end, False, None, None, None, None, None, None),
        compute_background=_background,
    )
    return _filter_calendar_events(raw_events, tracked_only, type, search, user, status, vf, source)


async def _compute_calendar(
    db: AsyncSession,
    start: Optional[str], end: Optional[str], tracked_only: bool, type: Optional[str],
    search: Optional[str], user: Optional[str], status: Optional[str], vf: Optional[str], source: Optional[str],
) -> list[dict]:
    now = now_utc()
    start_dt = datetime.fromisoformat(start) if start else now - timedelta(days=7)
    end_dt = datetime.fromisoformat(end) if end else now + timedelta(days=21)

    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)

    shows_by_tvdb: dict[str, dict] = {}
    movies_by_tmdb: dict[str, dict] = {}
    library_items_by_id: dict[int, dict[str, Any]] = {}

    for li in (await db.execute(select(LibraryItem))).scalars().all():
        entry: dict[str, Any] = {
            "in_library": True,
            "library_item_id": li.id,
            "plex_guid": li.plex_guid,
            "request_id": None,
            "request_status": None,
            "requested_by_ids": [],
            "request_sources": [],
            "has_vf": li.has_vf,
            "poster_url": wrap_image_proxy(li.poster_url),
        }
        library_items_by_id[li.id] = entry
        if li.media_type == "show" and li.tvdb_id:
            shows_by_tvdb[li.tvdb_id] = entry
        elif li.media_type == "movie" and li.tmdb_id:
            movies_by_tmdb[li.tmdb_id] = entry

    for r in (await db.execute(select(MediaRequest))).scalars().all():
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
                "poster_url": wrap_image_proxy(r.poster_url),
            }
            if r.media_type == "show" and r.tvdb_id:
                shows_by_tvdb[r.tvdb_id] = entry
            elif r.media_type == "movie" and r.tmdb_id:
                movies_by_tmdb[r.tmdb_id] = entry

    instances = (await db.execute(select(ArrInstance).filter(ArrInstance.enabled, ArrInstance.arr_type.in_(["sonarr", "radarr"])))).scalars().all()
    remote_results = await asyncio.gather(*(
        sonarr.get_calendar(inst.url, inst.api_key, start_dt.isoformat(), end_dt.isoformat())
        if inst.arr_type == "sonarr"
        else radarr.get_calendar(inst.url, inst.api_key, start_dt.isoformat(), end_dt.isoformat())
        for inst in instances
    ), return_exceptions=True)
    events = []
    for inst, remote_result in zip(instances, remote_results):
        try:
            if isinstance(remote_result, Exception):
                raise remote_result
            if inst.arr_type == "sonarr":
                episodes = remote_result
                for ep in episodes:
                    date = ep.get("airDateUtc")
                    if not date:
                        continue
                    series = ep.get("series") or {}
                    tvdb_id = str(series.get("tvdbId")) if series.get("tvdbId") else None
                    tracked = shows_by_tvdb.get(tvdb_id) if tvdb_id else None
                    originally_tracked = bool(tracked)
                    if tracked_only and not tracked:
                        continue

                    if not tracked:
                        # Extract the added date if available
                        added_date = None
                        added_str = series.get("added")
                        if added_str:
                            try:
                                added_date = datetime.fromisoformat(added_str.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
                            except ValueError:
                                pass

                        # Auto-create MediaRequest for untracked series in database
                        new_req = MediaRequest(
                            title=series.get("title") or "Unknown Series",
                            year=series.get("year"),
                            media_type="show",
                            tvdb_id=tvdb_id,
                            imdb_id=series.get("imdbId"),
                            status=RequestStatus.sent_to_arr,
                            source="arr_sync",
                            plex_user_id="system",
                            requested_at=added_date,
                        )
                        db.add(new_req)
                        await db.flush()

                        entry = {
                            "in_library": False,
                            "library_item_id": None,
                            "request_id": new_req.id,
                            "request_status": "sent_to_arr",
                            "requested_by_ids": [],
                            "request_sources": ["arr_sync"],
                            "has_vf": None,
                            "poster_url": wrap_image_proxy(_arr_poster(series, inst.url)),
                        }
                        shows_by_tvdb[tvdb_id] = entry
                        tracked = entry

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

                    events.append(
                        {
                            "type": "episode",
                            "release_type": "episode",
                            "date": date,
                            "title": series.get("title") or "",
                            "subtitle": f"S{ep.get('seasonNumber', 0):02d}E{ep.get('episodeNumber', 0):02d}"
                            + (f" — {ep.get('title')}" if ep.get("title") else ""),
                            "poster_url": wrap_image_proxy((tracked or {}).get("poster_url")) or _arr_poster(series, inst.url),
                            "fanart_url": _arr_fanart(series, inst.url),
                            "rating": _arr_rating(series),
                            "genres": _arr_genres(series),
                            "has_file": bool(ep.get("hasFile")),
                            "tracked": bool(tracked),
                            "library_item_id": (tracked or {}).get("library_item_id"),
                            "request_id": (tracked or {}).get("request_id"),
                            "plex_guid": (tracked or {}).get("plex_guid"),
                            "tvdb_id": tvdb_id,
                            "tmdb_id": (tracked or {}).get("tmdb_id") or None,
                            "instance": inst.name,
                            "_tracking": {**(tracked or {}), "originally_tracked": originally_tracked},
                        }
                    )
            else:
                movies = remote_result
                for m in movies:
                    release_events = _movie_release_events(m, start_dt, end_dt, now)
                    if not release_events:
                        continue
                    tmdb_id = str(m.get("tmdbId")) if m.get("tmdbId") else None
                    tracked = movies_by_tmdb.get(tmdb_id) if tmdb_id else None
                    originally_tracked = bool(tracked)
                    if tracked_only and not tracked:
                        continue

                    if not tracked:
                        # Extract the added date if available
                        added_date = None
                        added_str = m.get("added")
                        if added_str:
                            try:
                                added_date = datetime.fromisoformat(added_str.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
                            except ValueError:
                                pass

                        # Auto-create MediaRequest for untracked movie in database
                        new_req = MediaRequest(
                            title=m.get("title") or "Unknown Movie",
                            year=m.get("year"),
                            media_type="movie",
                            tmdb_id=tmdb_id,
                            imdb_id=m.get("imdbId"),
                            status=RequestStatus.sent_to_arr,
                            source="arr_sync",
                            plex_user_id="system",
                            requested_at=added_date,
                        )
                        db.add(new_req)
                        await db.flush()

                        entry = {
                            "in_library": False,
                            "library_item_id": None,
                            "request_id": new_req.id,
                            "request_status": "sent_to_arr",
                            "requested_by_ids": [],
                            "request_sources": ["arr_sync"],
                            "has_vf": None,
                            "poster_url": wrap_image_proxy(_arr_poster(m, inst.url)),
                        }
                        movies_by_tmdb[tmdb_id] = entry
                        tracked = entry

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

                    poster = wrap_image_proxy((tracked or {}).get("poster_url")) or _arr_poster(m, inst.url)
                    fanart = _arr_fanart(m, inst.url)
                    rating = _arr_rating(m)
                    genres = _arr_genres(m)
                    for rdate, rtype, rlabel in release_events:
                        events.append(
                            {
                                "type": "movie",
                                "release_type": rtype,
                                "date": rdate,
                                "title": title,
                                "subtitle": rlabel,
                                "poster_url": poster,
                                "fanart_url": fanart,
                                "rating": rating,
                                "genres": genres,
                                "has_file": bool(m.get("hasFile")),
                                "tracked": bool(tracked),
                                "library_item_id": (tracked or {}).get("library_item_id"),
                                "request_id": (tracked or {}).get("request_id"),
                                "plex_guid": (tracked or {}).get("plex_guid"),
                                "tmdb_id": tmdb_id,
                                "instance": inst.name,
                                "_tracking": {**(tracked or {}), "originally_tracked": originally_tracked},
                            }
                        )
        except Exception as e:
            logger.warning(f"Calendar fetch failed for '{inst.name}': {e}")

    await db.commit()
    events.sort(key=lambda e: e["date"])
    return events
