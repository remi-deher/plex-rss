"""Catalogue de découverte TMDB (façon Overseerr).

Endpoints sous /api/discover/*. Chaque média renvoyé est annoté selon l'état
local (déjà dans la bibliothèque Plex, déjà demandé, disponible) en recoupant
les tmdb_id avec LibraryItem et MediaRequest.
"""

import json
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..cache import cache
from ..database import get_db_async
from ..dependencies import _is_moderator, current_user, require_auth
from ..models import LibraryItem, MediaRequest, PlaybackSession, PlexUser, RequestSeasonStatus, Settings
from ..serializers import request_status_value, serialize_media_request
from ..services import tmdb
from ..services.media_annotate import annotate_media_items as _annotate
from ..services.media_annotate import annotate_page as _annotate_page

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/discover", tags=["discover"], dependencies=[Depends(require_auth)])

HOME_SECTIONS = (
    "hero",
    "trending",
    "popular_movies",
    "popular_tv",
    "upcoming",
    "recent_plex",
    "most_requested",
)
HOME_DEFAULT_SECTIONS = ",".join(HOME_SECTIONS)
HOME_CACHE_TTL_SECONDS = 30 * 60
PERSONALIZATION_SEED_LIMIT = 3


@router.get("/status")
async def discover_status(db: AsyncSession = Depends(get_db_async)):
    """Indique si TMDB est configuré (pour l'affichage conditionnel de la page)."""
    s = (await db.execute(select(Settings))).scalars().first()
    return {"configured": bool(s and (s.tmdb_api_key or "").strip())}


@router.get("/requesters")
async def discover_requesters(request: Request, db: AsyncSession = Depends(get_db_async)):
    caller = current_user(request, db)
    if not caller:
        raise HTTPException(403, "Une session utilisateur est requise.")
    if not _is_moderator(caller):
        uid = caller.get("plex_user_id")
        user = (await db.execute(select(PlexUser).filter(PlexUser.plex_user_id == uid, PlexUser.enabled))).scalars().first()
        users = [user] if user else []
    else:
        users = (await db.execute(select(PlexUser).filter(PlexUser.enabled).order_by(PlexUser.display_name))).scalars().all()
    return [
        {
            "id": user.id,
            "plex_user_id": user.plex_user_id,
            "display_name": user.display_name,
            "custom_name": user.custom_name,
        }
        for user in users
    ]


def _guard(exc: Exception):
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, tmdb.TmdbNotConfigured):
        raise HTTPException(400, "Clé API TMDB non configurée (Paramètres → Connexions).")
    logger.warning("Erreur TMDB : %s", exc)
    raise HTTPException(502, "Le catalogue TMDB est temporairement indisponible.")


def _page_response(payload: dict, paginated: bool):
    """Garde les anciens bundles compatibles pendant un déploiement progressif."""
    return payload if paginated else payload["items"]


async def _discovery_region(db: AsyncSession) -> str:
    settings = (await db.execute(select(Settings))).scalars().first()
    region = ((settings.tmdb_region if settings else None) or tmdb.REGION).strip().upper()
    return region if len(region) == 2 and region.isalpha() else tmdb.REGION


async def _fetch_home_section(db: AsyncSession, section: str, region: str) -> dict:
    """Charge une section TMDB brute et la partage via Redis (avec repli mémoire).

    Les annotations locales ne sont volontairement pas mises en cache : une demande ou
    un import Plex doit changer le badge dès la requête suivante.
    """
    cache_key = f"plexarr:discover:home:v2:{region}:{section}"
    cached = await cache.get_json(cache_key)
    if cached and isinstance(cached.get("payload"), dict):
        return cached["payload"]

    if section == "trending":
        payload = await tmdb.trending(db, "all", "day", 1)
    elif section == "popular_movies":
        payload = await tmdb.popular(db, "movie", 1, region)
    elif section == "popular_tv":
        payload = await tmdb.popular(db, "show", 1, region)
    elif section == "upcoming":
        payload = await tmdb.coming_soon(db, "all", 1, region)
    else:  # pragma: no cover - garde interne, la validation HTTP filtre déjà ces valeurs
        raise ValueError(f"Section d'accueil inconnue: {section}")

    await cache.set_json(cache_key, {"payload": payload}, ttl_seconds=HOME_CACHE_TTL_SECONDS)
    return payload


async def _recent_plex_section(db: AsyncSession, limit: int = 20) -> dict:
    rows = (
        await db.execute(
            select(LibraryItem)
            .order_by(LibraryItem.added_at.desc(), LibraryItem.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "tmdb_id": row.tmdb_id,
                "media_type": row.media_type,
                "title": row.title,
                "year": row.year,
                "overview": row.overview or "",
                "poster_url": (
                    f"/api/image-proxy/library/{row.id}?width=500&quality=82&format=webp"
                    if row.poster_url
                    else None
                ),
                "library_id": row.id,
                "in_library": True,
                "available": True,
                "requested": False,
                "request_id": None,
            }
            for row in rows
        ],
        "page": 1,
        "total_pages": 1,
        "total_results": len(rows),
    }


async def _most_requested_section(db: AsyncSession, limit: int = 20) -> dict:
    rows = (
        await db.execute(
            select(MediaRequest).filter(
                MediaRequest.extra_requesters.isnot(None),
                MediaRequest.extra_requesters != "[]",
            )
        )
    ).scalars().all()
    ranked = []
    for row in rows:
        try:
            requester_count = 1 + len(json.loads(row.extra_requesters or "[]"))
        except (TypeError, ValueError):
            requester_count = 1
        if requester_count < 2:
            continue
        status = request_status_value(row.status)
        ranked.append(
            {
                "tmdb_id": row.tmdb_id,
                "media_type": row.media_type,
                "title": row.title,
                "year": row.year,
                "overview": row.overview or "",
                "poster_url": (
                    f"/api/image-proxy/request/{row.id}?width=500&quality=82&format=webp"
                    if row.poster_url
                    else None
                ),
                "library_id": row.library_item_id,
                "request_id": row.id,
                "in_library": row.library_item_id is not None,
                "available": row.library_item_id is not None or status in ("available", "partially_available"),
                "requested": True,
                "request_status": status,
                "is_downloading": bool(row.is_downloading),
                "requester_count": requester_count,
            }
        )
    ranked.sort(key=lambda item: (item["requester_count"], item["request_id"]), reverse=True)
    items = ranked[:limit]
    return {"items": items, "page": 1, "total_pages": 1, "total_results": len(items)}


def _media_key(item: dict) -> tuple[str, str]:
    return item.get("media_type") or "", str(item.get("tmdb_id") or "")


def _merge_unique_media(groups: list[list[dict]], excluded: set[tuple[str, str]], limit: int = 20) -> list[dict]:
    merged: list[dict] = []
    seen = set(excluded)
    for group in groups:
        for item in group:
            key = _media_key(item)
            if not key[1] or key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= limit:
                return merged
    return merged


async def _personalization_seeds(db: AsyncSession, plex_user_id: str, limit: int = PERSONALIZATION_SEED_LIMIT):
    sessions = (
        await db.execute(
            select(PlaybackSession)
            .filter(
                PlaybackSession.plex_user_id == plex_user_id,
                PlaybackSession.ended_at.isnot(None),
            )
            .order_by(PlaybackSession.started_at.desc(), PlaybackSession.id.desc())
            .limit(60)
        )
    ).scalars().all()
    if not sessions:
        return [], set()

    library_rows = (await db.execute(select(LibraryItem).filter(LibraryItem.tmdb_id.isnot(None)))).scalars().all()
    library_by_identity = {
        (row.media_type, row.title.casefold().strip(), row.year): row
        for row in library_rows
        if row.title and row.tmdb_id
    }
    library_by_title = {
        (row.media_type, row.title.casefold().strip()): row
        for row in library_rows
        if row.title and row.tmdb_id
    }
    seeds = []
    seed_keys: set[tuple[str, str]] = set()
    watched: set[tuple[str, str]] = set()
    for session in sessions:
        media_type = "show" if session.media_type in ("show", "episode") else "movie"
        title = session.grandparent_title if media_type == "show" else session.title
        if not title:
            continue
        row = library_by_identity.get((media_type, title.casefold().strip(), session.year))
        if not row:
            # Les imports Tautulli ne fournissent pas toujours l'année : le titre reste
            # un repli raisonnable, limité aux médias déjà identifiés dans Plex.
            row = library_by_title.get((media_type, title.casefold().strip()))
        if not row:
            continue
        key = (row.media_type, str(row.tmdb_id))
        watched.add(key)
        if key not in seed_keys and len(seeds) < limit:
            seeds.append(
                {
                    "tmdb_id": row.tmdb_id,
                    "media_type": row.media_type,
                    "title": row.title,
                    "year": row.year,
                    "library_id": row.id,
                }
            )
            seed_keys.add(key)
    return seeds, watched


async def _personalized_sections(
    db: AsyncSession,
    plex_user_id: str,
    *,
    hide_available: bool = False,
    hide_watched: bool = False,
) -> dict:
    seeds, watched = await _personalization_seeds(db, plex_user_id)
    if not seeds:
        return {"available": False, "seeds": [], "sections": {}}
    excluded = watched if hide_watched else {_media_key(seed) for seed in seeds}

    recommendation_groups: list[list[dict]] = []
    series_groups: list[list[dict]] = []
    genre_counts: dict[int, int] = {}
    for seed in seeds:
        try:
            detail = await tmdb.detail(db, seed["media_type"], int(seed["tmdb_id"]))
        except Exception as exc:
            logger.warning("Recommandations TMDB indisponibles pour %s: %s", seed["tmdb_id"], exc)
            continue
        recommendations = detail.get("recommendations") or detail.get("similar") or []
        recommendation_groups.append(recommendations)
        if seed["media_type"] == "show" and detail.get("next_episode_to_air"):
            series_groups.append([detail])
        for item in recommendations:
            for genre_id in item.get("genre_ids") or []:
                genre_counts[int(genre_id)] = genre_counts.get(int(genre_id), 0) + 1

    recommended = _merge_unique_media(recommendation_groups, excluded)
    # Cette rangée conserve volontairement la série déjà présente : elle signale
    # précisément son prochain épisode, même quand les contenus vus sont masqués.
    followed_series = _merge_unique_media(series_groups, set(), 12)
    preferred_genre = max(genre_counts, key=genre_counts.get) if genre_counts else None
    preferred = []
    if preferred_genre:
        try:
            payload = await tmdb.discover(db, "all", preferred_genre, "popularity.desc", 1, await _discovery_region(db))
            preferred = _merge_unique_media([payload.get("items", [])], excluded)
        except Exception as exc:
            logger.warning("Section genres préférés indisponible: %s", exc)

    popular = []
    try:
        payload = await tmdb.popular(db, "all", 1, await _discovery_region(db))
        popular = _merge_unique_media([payload.get("items", [])], excluded)
    except Exception as exc:
        logger.warning("Section jamais vus indisponible: %s", exc)

    all_items = [*recommended, *preferred, *popular, *followed_series]
    await _annotate(db, all_items)
    if hide_available:
        for items in (recommended, preferred, popular):
            items[:] = [item for item in items if not item.get("available") and not item.get("in_library")]
    return {
        "available": True,
        "seeds": seeds,
        "sections": {
            "recommended": {"items": recommended},
            "preferred_genres": {"items": preferred},
            "unwatched_popular": {"items": popular},
            "followed_series": {"items": followed_series},
        },
    }


@router.get("/personalized")
async def get_personalized(
    request: Request,
    hide_available: bool = False,
    hide_watched: bool = False,
    db: AsyncSession = Depends(get_db_async),
):
    caller = current_user(request, db)
    plex_user_id = caller.get("plex_user_id") if caller else None
    if not plex_user_id:
        return {"available": False, "seeds": [], "sections": {}}
    try:
        return await _personalized_sections(
            db,
            plex_user_id,
            hide_available=hide_available,
            hide_watched=hide_watched,
        )
    except Exception as exc:
        logger.warning("Personnalisation Découvrir indisponible: %s", exc)
        return {
            "available": True,
            "seeds": [],
            "sections": {},
            "error": "Les recommandations personnalisées sont temporairement indisponibles.",
        }


def _home_error(exc: Exception) -> str:
    if isinstance(exc, tmdb.TmdbNotConfigured):
        return "Clé API TMDB non configurée."
    logger.warning("Section Découvrir indisponible: %s", exc)
    return "Section temporairement indisponible."


@router.get("/home")
async def get_home(
    sections: str = Query(HOME_DEFAULT_SECTIONS, min_length=1),
    db: AsyncSession = Depends(get_db_async),
):
    """Retourne les blocs de l'accueil, sans coupler leur disponibilité.

    `hero` réutilise les 5 premiers résultats de `trending` (carrousel "à la une") : le
    demander avec la rangée Tendances ne provoque donc aucun second appel externe.
    """
    requested = list(dict.fromkeys(part.strip() for part in sections.split(",") if part.strip()))
    invalid = [section for section in requested if section not in HOME_SECTIONS]
    if not requested or invalid:
        allowed = ", ".join(HOME_SECTIONS)
        raise HTTPException(422, f"Sections invalides. Valeurs acceptées : {allowed}.")

    region = await _discovery_region(db)
    external_sections = {"trending", "popular_movies", "popular_tv", "upcoming"}
    source_names = list(
        dict.fromkeys(
            "trending" if section == "hero" else section
            for section in requested
            if section == "hero" or section in external_sections
        )
    )
    payloads: dict[str, dict] = {}
    errors: dict[str, str] = {}
    for source in source_names:
        try:
            payloads[source] = await _fetch_home_section(db, source, region)
        except Exception as exc:
            errors[source] = _home_error(exc)

    if "recent_plex" in requested:
        payloads["recent_plex"] = await _recent_plex_section(db)
    if "most_requested" in requested:
        payloads["most_requested"] = await _most_requested_section(db)

    all_items = [
        item
        for source, payload in payloads.items()
        if source in external_sections
        for item in payload.get("items", [])
    ]
    await _annotate(db, all_items)

    result: dict[str, dict] = {}
    for section in requested:
        source = "trending" if section == "hero" else section
        if source in errors:
            result[section] = {"error": errors[source], "items": []}
            continue
        payload = payloads[source]
        result[section] = (
            {"items": payload.get("items", [])[:5]}
            if section == "hero"
            else payload
        )

    return {"sections": result}


@router.get("/sources")
async def get_sources(db: AsyncSession = Depends(get_db_async)):
    region = await _discovery_region(db)
    cache_key = f"plexarr:discover:sources:v1:{region}"
    cached = await cache.get_json(cache_key)
    if cached and isinstance(cached.get("items"), list):
        return {"region": region, "items": cached["items"]}
    try:
        items = await tmdb.discovery_sources(db, region)
        await cache.set_json(cache_key, {"items": items}, ttl_seconds=HOME_CACHE_TTL_SECONDS)
        return {"region": region, "items": items}
    except Exception as exc:
        _guard(exc)


@router.get("/source/{kind}/{source_id}")
async def get_source_media(
    kind: Literal["provider", "network", "company"],
    source_id: int,
    media_type: Literal["all", "movie", "show"] = "all",
    page: int = Query(1, ge=1, le=500),
    db: AsyncSession = Depends(get_db_async),
):
    region = await _discovery_region(db)
    cache_key = f"plexarr:discover:source:v1:{region}:{kind}:{source_id}:{media_type}:{page}"
    try:
        cached = await cache.get_json(cache_key)
        if cached and isinstance(cached.get("payload"), dict):
            payload = cached["payload"]
        else:
            payload = await tmdb.discover_by_source(db, kind, source_id, media_type, page, region)
            await cache.set_json(cache_key, {"payload": payload}, ttl_seconds=HOME_CACHE_TTL_SECONDS)
        return await _annotate_page(db, payload)
    except Exception as exc:
        _guard(exc)


@router.get("/trending")
async def get_trending(
    media_type: Literal["all", "movie", "show"] = "all",
    window: Literal["day", "week"] = "week",
    page: int = Query(1, ge=1, le=500),
    paginated: bool = False,
    db: AsyncSession = Depends(get_db_async),
):
    try:
        payload = await _annotate_page(db, await tmdb.trending(db, media_type, window, page))
        return _page_response(payload, paginated)
    except Exception as e:
        _guard(e)


@router.get("/popular")
async def get_popular(
    media_type: Literal["all", "movie", "show"] = "movie",
    page: int = Query(1, ge=1, le=500),
    paginated: bool = False,
    db: AsyncSession = Depends(get_db_async),
):
    try:
        payload = await _annotate_page(db, await tmdb.popular(db, media_type, page, await _discovery_region(db)))
        return _page_response(payload, paginated)
    except Exception as e:
        _guard(e)


@router.get("/coming-soon")
async def get_coming_soon(
    media_type: Literal["all", "movie", "show"] = "movie",
    page: int = Query(1, ge=1, le=500),
    paginated: bool = False,
    db: AsyncSession = Depends(get_db_async),
):
    try:
        payload = await _annotate_page(
            db,
            await tmdb.coming_soon(db, media_type, page, await _discovery_region(db)),
        )
        return _page_response(payload, paginated)
    except Exception as e:
        _guard(e)


@router.get("/genres")
async def get_genres(media_type: Literal["all", "movie", "show"] = "movie", db: AsyncSession = Depends(get_db_async)):
    try:
        return await tmdb.genres(db, media_type)
    except Exception as e:
        _guard(e)


@router.get("/discover")
async def get_discover(
    media_type: Literal["all", "movie", "show"] = "movie",
    genre: Optional[int] = None,
    sort_by: Literal["popularity.desc", "vote_average.desc", "primary_release_date.desc"] = "popularity.desc",
    page: int = Query(1, ge=1, le=500),
    paginated: bool = False,
    db: AsyncSession = Depends(get_db_async),
):
    try:
        payload = await _annotate_page(
            db,
            await tmdb.discover(db, media_type, genre, sort_by, page, await _discovery_region(db)),
        )
        return _page_response(payload, paginated)
    except Exception as e:
        _guard(e)


@router.get("/search")
async def get_search(
    query: str = Query(..., min_length=1, max_length=200),
    media_type: Literal["all", "movie", "show"] = "all",
    page: int = Query(1, ge=1, le=500),
    paginated: bool = False,
    db: AsyncSession = Depends(get_db_async),
):
    try:
        payload = await _annotate_page(db, await tmdb.search(db, query, page, media_type))
        return _page_response(payload, paginated)
    except Exception as e:
        _guard(e)


@router.get("/detail")
async def get_detail(
    media_type: Literal["movie", "show"],
    tmdb_id: Optional[int] = None,
    tvdb_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db_async),
):
    try:
        if not tmdb_id and tvdb_id:
            resolved_tmdb = await tmdb.find_by_external_id(db, "tvdb_id", tvdb_id)
            if resolved_tmdb:
                tmdb_id = resolved_tmdb
            else:
                raise HTTPException(404, "Identifiant TVDB non trouve sur TMDB.")

        if not tmdb_id:
            raise HTTPException(400, "tmdb_id ou tvdb_id requis.")

        d = await tmdb.detail(db, media_type, tmdb_id)
        await _annotate(db, [d])
        if d.get("request_id"):
            req = (await db.execute(select(MediaRequest).filter(MediaRequest.id == d["request_id"]))).scalars().first()
            if req:
                users = {
                    u.plex_user_id: (u.custom_name or u.display_name or u.plex_user_id)
                    for u in (await db.execute(select(PlexUser))).scalars().all()
                }
                serialized = serialize_media_request(req, users)
                d["requesters"] = serialized["requesters"]
                d["requester_ids"] = serialized["requester_ids"]
                d["episodes_available_count"] = serialized["episodes_available_count"]
                d["episodes_aired_count"] = serialized["episodes_aired_count"]
                d["episodes_total_count"] = serialized["episodes_total_count"]
                if req.media_type == "show":
                    season_rows = (
                        await db.execute(
                            select(RequestSeasonStatus)
                            .filter(RequestSeasonStatus.request_id == req.id)
                            .order_by(RequestSeasonStatus.season_number)
                        )
                    ).scalars().all()
                    d["seasons"] = [
                        {
                            "season_number": row.season_number,
                            "episodes_available_count": row.episodes_available_count,
                            "episodes_total_count": row.episodes_total_count,
                            "status": row.status,
                        }
                        for row in season_rows
                    ]
        d["recommendations"] = await _annotate(db, d.get("recommendations", []))
        d["similar"] = await _annotate(db, d.get("similar", []))
        if d.get("saga"):
            d["saga"]["items"] = await _annotate(db, d["saga"].get("items", []))
        return d
    except Exception as e:
        _guard(e)


@router.get("/person/{person_id}")
async def get_person(person_id: int, db: AsyncSession = Depends(get_db_async)):
    try:
        payload = await tmdb.person_detail(db, person_id)
        payload["credits"] = await _annotate(db, payload.get("credits", []))
        return payload
    except Exception as e:
        _guard(e)
