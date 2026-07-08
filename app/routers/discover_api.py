"""Catalogue de découverte TMDB (façon Overseerr).

Endpoints sous /api/discover/*. Chaque média renvoyé est annoté selon l'état
local (déjà dans la bibliothèque Plex, déjà demandé, disponible) en recoupant
les tmdb_id avec LibraryItem et MediaRequest.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_auth
from ..models import LibraryItem, MediaRequest, Settings
from ..services import tmdb

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/discover", tags=["discover"], dependencies=[Depends(require_auth)])


def _annotate(db: Session, items: list[dict]) -> list[dict]:
    """Ajoute in_library / requested / available à chaque item selon l'état local."""
    ids_by_type: dict[str, set[str]] = {"movie": set(), "show": set()}
    for it in items:
        if it.get("tmdb_id") is not None and it.get("media_type") in ids_by_type:
            ids_by_type[it["media_type"]].add(str(it["tmdb_id"]))

    lib: set[tuple[str, str]] = set()
    reqs: dict[tuple[str, str], str] = {}
    for mt, ids in ids_by_type.items():
        if not ids:
            continue
        for (tid,) in db.query(LibraryItem.tmdb_id).filter(
            LibraryItem.media_type == mt, LibraryItem.tmdb_id.in_(ids)
        ).all():
            if tid:
                lib.add((mt, tid))
        for tid, status in db.query(MediaRequest.tmdb_id, MediaRequest.status).filter(
            MediaRequest.media_type == mt, MediaRequest.tmdb_id.in_(ids)
        ).all():
            if tid:
                sval = status.value if hasattr(status, "value") else str(status)
                reqs[(mt, tid)] = sval

    for it in items:
        k = (it.get("media_type"), str(it.get("tmdb_id")))
        it["in_library"] = k in lib
        st = reqs.get(k)
        it["requested"] = st is not None
        it["request_status"] = st
        it["available"] = it["in_library"] or st == "available"
    return items


@router.get("/status")
def discover_status(db: Session = Depends(get_db)):
    """Indique si TMDB est configuré (pour l'affichage conditionnel de la page)."""
    s = db.query(Settings).first()
    return {"configured": bool(s and (s.tmdb_api_key or "").strip())}


def _guard(exc: Exception):
    if isinstance(exc, tmdb.TmdbNotConfigured):
        raise HTTPException(400, "Clé API TMDB non configurée (Paramètres → Connexions).")
    logger.warning("Erreur TMDB : %s", exc)
    raise HTTPException(502, f"Erreur TMDB : {exc}")


@router.get("/trending")
async def get_trending(media_type: str = "all", window: str = "week", db: Session = Depends(get_db)):
    try:
        return _annotate(db, await tmdb.trending(db, media_type, window))
    except Exception as e:
        _guard(e)


@router.get("/popular")
async def get_popular(media_type: str = "movie", page: int = 1, db: Session = Depends(get_db)):
    try:
        return _annotate(db, await tmdb.popular(db, media_type, page))
    except Exception as e:
        _guard(e)


@router.get("/coming-soon")
async def get_coming_soon(media_type: str = "movie", page: int = 1, db: Session = Depends(get_db)):
    try:
        return _annotate(db, await tmdb.coming_soon(db, media_type, page))
    except Exception as e:
        _guard(e)


@router.get("/genres")
async def get_genres(media_type: str = "movie", db: Session = Depends(get_db)):
    try:
        return await tmdb.genres(db, media_type)
    except Exception as e:
        _guard(e)


@router.get("/discover")
async def get_discover(
    media_type: str = "movie",
    genre: Optional[int] = None,
    sort_by: str = "popularity.desc",
    page: int = 1,
    db: Session = Depends(get_db),
):
    try:
        return _annotate(db, await tmdb.discover(db, media_type, genre, sort_by, page))
    except Exception as e:
        _guard(e)


@router.get("/search")
async def get_search(query: str = Query(..., min_length=1), page: int = 1, db: Session = Depends(get_db)):
    try:
        return _annotate(db, await tmdb.search(db, query, page))
    except Exception as e:
        _guard(e)


@router.get("/detail")
async def get_detail(media_type: str, tmdb_id: int, db: Session = Depends(get_db)):
    try:
        d = await tmdb.detail(db, media_type, tmdb_id)
        _annotate(db, [d])
        d["recommendations"] = _annotate(db, d.get("recommendations", []))
        d["similar"] = _annotate(db, d.get("similar", []))
        return d
    except Exception as e:
        _guard(e)
