"""Utilitaires partagés entre les modules de l'application."""

from contextlib import contextmanager
from datetime import datetime
from typing import Any, Protocol, TypeVar

from fastapi import HTTPException
from sqlalchemy.orm import Session


class _HasId(Protocol):
    id: Any


_T = TypeVar("_T", bound=_HasId)


@contextmanager
def db_session(SessionLocal):
    """Context manager qui ouvre une session SQLAlchemy et garantit sa fermeture."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_or_404(db: Session, model: type[_T], obj_id: Any, detail: str = "Not found") -> _T:
    """Retourne l'objet ou lève HTTPException 404."""
    obj = db.query(model).filter(model.id == obj_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail=detail)
    return obj

async def async_get_or_404(db, model: type[_T], obj_id: Any, detail: str = "Not found") -> _T:
    from sqlalchemy.future import select
    obj = (await db.execute(select(model).filter(model.id == obj_id))).scalars().first()
    if not obj:
        raise HTTPException(status_code=404, detail=detail)
    return obj


def parse_email_list(raw: str | None) -> list[str]:
    """Parse une chaîne d'emails séparés par virgules en liste nettoyée.

    Retourne une liste vide si raw est None ou ne contient que des espaces.
    """
    if not raw:
        return []
    return [e.strip() for e in raw.split(",") if e.strip()]


def identity_keys(rec) -> list:
    """Clés d'identité d'un média (pour rapprocher demande ↔ élément de bibliothèque).

    Ordre de priorité au moment du rapprochement : GUID Plex, puis IDs externes
    (TMDB/TVDB/IMDB), puis titre+année+type en dernier recours. Partagé entre la vue
    Bibliothèque (rapprochement à l'affichage) et le scheduler (lien persistant
    MediaRequest.library_item_id) pour ne pas dupliquer cette logique à deux endroits.
    """
    keys: list[tuple] = []
    if getattr(rec, "plex_guid", None):
        keys.append(("guid", rec.plex_guid))
    if getattr(rec, "tmdb_id", None):
        keys.append(("tmdb", rec.tmdb_id))
    if getattr(rec, "tvdb_id", None):
        keys.append(("tvdb", rec.tvdb_id))
    if getattr(rec, "imdb_id", None):
        keys.append(("imdb", rec.imdb_id))
    keys.append(("title", (rec.title or "").lower().strip(), rec.year, rec.media_type))
    return keys


def now_utc() -> datetime:
    """Instant courant, aware UTC."""
    from datetime import timezone

    return datetime.now(timezone.utc)


def now_utc_naive() -> datetime:
    """Instant courant UTC sans tzinfo (colonnes DB stockées en naïf-UTC)."""
    from datetime import timezone

    return datetime.now(timezone.utc).replace(tzinfo=None)
