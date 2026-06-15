"""Utilitaires partagés entre les modules de l'application."""

from contextlib import contextmanager
from typing import Any, TypeVar

from fastapi import HTTPException
from sqlalchemy.orm import Session

_T = TypeVar("_T")


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


def parse_email_list(raw: str | None) -> list[str]:
    """Parse une chaîne d'emails séparés par virgules en liste nettoyée.

    Retourne une liste vide si raw est None ou ne contient que des espaces.
    """
    if not raw:
        return []
    return [e.strip() for e in raw.split(",") if e.strip()]
