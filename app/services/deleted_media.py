"""Garde-fou contre le retour silencieux d'un média volontairement supprimé par un
admin (voir DeletedMediaLog dans app/models.py pour le raisonnement complet).
"""

from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..models import DeletedMediaLog
from ..utils import now_utc_naive


async def record_deletion(
    db: AsyncSession,
    media_type: str,
    title: str,
    tmdb_id: str | None = None,
    tvdb_id: str | None = None,
    imdb_id: str | None = None,
    deleted_by: str | None = None,
) -> None:
    """Enregistre une suppression volontaire. Sans identifiant stable, ne fait rien
    (on ne peut pas la retrouver plus tard de toute façon)."""
    if not (tmdb_id or tvdb_id or imdb_id):
        return
    existing = await _find(db, media_type, tmdb_id, tvdb_id, imdb_id)
    if existing:
        existing.deleted_at = now_utc_naive()
        existing.deleted_by = deleted_by
        existing.title = title
        return
    db.add(DeletedMediaLog(
        media_type=media_type,
        title=title,
        tmdb_id=tmdb_id,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
        deleted_by=deleted_by,
    ))


async def is_tombstoned(
    db: AsyncSession,
    media_type: str,
    tmdb_id: str | None = None,
    tvdb_id: str | None = None,
    imdb_id: str | None = None,
) -> bool:
    return await _find(db, media_type, tmdb_id, tvdb_id, imdb_id) is not None


async def _find(
    db: AsyncSession,
    media_type: str,
    tmdb_id: str | None,
    tvdb_id: str | None,
    imdb_id: str | None,
) -> DeletedMediaLog | None:
    if not (tmdb_id or tvdb_id or imdb_id):
        return None
    conditions = []
    if tmdb_id:
        conditions.append(DeletedMediaLog.tmdb_id == str(tmdb_id))
    if tvdb_id:
        conditions.append(DeletedMediaLog.tvdb_id == str(tvdb_id))
    if imdb_id:
        conditions.append(DeletedMediaLog.imdb_id == str(imdb_id))
    return (await db.execute(
        select(DeletedMediaLog).filter(DeletedMediaLog.media_type == media_type, or_(*conditions))
    )).scalars().first()
