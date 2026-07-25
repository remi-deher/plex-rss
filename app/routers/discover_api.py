"""Catalogue de découverte TMDB (façon Overseerr).

Endpoints sous /api/discover/*. Chaque média renvoyé est annoté selon l'état
local (déjà dans la bibliothèque Plex, déjà demandé, disponible) en recoupant
les tmdb_id avec LibraryItem et MediaRequest.
"""

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import get_db_async
from ..dependencies import current_user, require_auth
from ..models import LibraryItem, MediaRequest, PlexUser, Settings
from ..serializers import request_status_value, serialize_media_request
from ..services import tmdb

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/discover", tags=["discover"], dependencies=[Depends(require_auth)])


async def _annotate(db: AsyncSession, items: list[dict]) -> list[dict]:
    """Ajoute l'état local (bibliothèque/demande/VF) à chaque item, pour badge + lien
    vers la fiche Library (qui porte déjà tout le reste : recherche interactive, ajout
    de demandeur, relance, anomalie Plex, suppression — pas de duplication ici)."""
    ids_by_type: dict[str, set[str]] = {"movie": set(), "show": set()}
    for it in items:
        if it.get("tmdb_id") is not None and it.get("media_type") in ids_by_type:
            ids_by_type[it["media_type"]].add(str(it["tmdb_id"]))

    lib: dict[tuple[str, str], LibraryItem] = {}
    reqs: dict[tuple[str, str], MediaRequest] = {}
    for mt, ids in ids_by_type.items():
        if not ids:
            continue
        for li in (await db.execute(select(LibraryItem).filter(LibraryItem.media_type == mt, LibraryItem.tmdb_id.in_(ids)))).scalars().all():
            if li.tmdb_id:
                lib[(mt, li.tmdb_id)] = li
        request_rows = (await db.execute(
            select(MediaRequest)
            .filter(MediaRequest.media_type == mt, MediaRequest.tmdb_id.in_(ids))
            .order_by(MediaRequest.requested_at.desc(), MediaRequest.id.desc())
        )).scalars().all()
        status_priority = {
            "available": 6,
            "partially_available": 5,
            "sent_to_arr": 4,
            "pending": 3,
            "pending_approval": 2,
            "failed": 1,
        }
        for req in request_rows:
            if req.tmdb_id:
                key = (mt, req.tmdb_id)
                current = reqs.get(key)
                if current is None or status_priority.get(request_status_value(req.status), 0) > status_priority.get(
                    request_status_value(current.status), 0
                ):
                    reqs[key] = req

    for it in items:
        k = (it.get("media_type"), str(it.get("tmdb_id")))
        li = lib.get(k)
        req = reqs.get(k)
        it["in_library"] = li is not None
        it["library_id"] = li.id if li else None
        it["request_id"] = req.id if req else None
        st = request_status_value(req.status) if req else None
        it["requested"] = st is not None
        it["request_status"] = st
        # Une serie "partiellement disponible" (au moins un episode deja regardable) compte
        # comme "dans Plex" au meme titre qu'une demande pleinement disponible -- coherent
        # avec le filtre "Dans Plex" de la Bibliotheque (voir LibraryView.matchesStatusFilter).
        it["available"] = it["in_library"] or st in ("available", "partially_available")
        it["has_vf"] = li.has_vf if li else (req.has_vf if req else None)
        it["vf_granularity"] = (li.vf_granularity if li else None) or (req.vf_granularity if req else None)
        # En cours de téléchargement (prioritaire sur l'anomalie) : cf. commentaire équivalent
        # dans app/routers/pages.py.
        it["is_downloading"] = bool(req and req.is_downloading)
        # Anomalie : *arr dit "disponible" mais absent de la bibliothèque Plex synchronisée,
        # à condition qu'il ne soit pas encore en cours de téléchargement/import.
        it["plex_anomaly"] = bool(req and st == "available" and not li and not req.is_downloading)
    return items


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
    if caller and not (caller.get("is_owner") or caller.get("role") == "admin"):
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


async def _annotate_page(db: AsyncSession, payload: dict) -> dict:
    payload["items"] = await _annotate(db, payload.get("items", []))
    return payload


@router.get("/trending")
async def get_trending(
    media_type: Literal["all", "movie", "show"] = "all",
    window: Literal["day", "week"] = "week",
    page: int = Query(1, ge=1, le=500),
    db: AsyncSession = Depends(get_db_async),
):
    try:
        return await _annotate_page(db, await tmdb.trending(db, media_type, window, page))
    except Exception as e:
        _guard(e)


@router.get("/popular")
async def get_popular(
    media_type: Literal["all", "movie", "show"] = "movie",
    page: int = Query(1, ge=1, le=500),
    db: AsyncSession = Depends(get_db_async),
):
    try:
        return await _annotate_page(db, await tmdb.popular(db, media_type, page))
    except Exception as e:
        _guard(e)


@router.get("/coming-soon")
async def get_coming_soon(
    media_type: Literal["all", "movie", "show"] = "movie",
    page: int = Query(1, ge=1, le=500),
    db: AsyncSession = Depends(get_db_async),
):
    try:
        return await _annotate_page(db, await tmdb.coming_soon(db, media_type, page))
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
    db: AsyncSession = Depends(get_db_async),
):
    try:
        return await _annotate_page(db, await tmdb.discover(db, media_type, genre, sort_by, page))
    except Exception as e:
        _guard(e)


@router.get("/search")
async def get_search(
    query: str = Query(..., min_length=1, max_length=200),
    media_type: Literal["all", "movie", "show"] = "all",
    page: int = Query(1, ge=1, le=500),
    db: AsyncSession = Depends(get_db_async),
):
    try:
        return await _annotate_page(db, await tmdb.search(db, query, page, media_type))
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
                d["requesters"] = serialize_media_request(req, users)["requesters"]
        d["recommendations"] = await _annotate(db, d.get("recommendations", []))
        d["similar"] = await _annotate(db, d.get("similar", []))
        return d
    except Exception as e:
        _guard(e)
