"""Tests unitaires pour app.services.deleted_media (garde-fou anti-resurrection)."""

import pytest

from app.services import deleted_media


@pytest.mark.asyncio
async def test_record_and_check_by_tmdb_id(async_db):
    db = async_db
    await deleted_media.record_deletion(db, "movie", "Inception", tmdb_id="27205")
    db.commit()

    assert await deleted_media.is_tombstoned(db, "movie", tmdb_id="27205") is True
    assert await deleted_media.is_tombstoned(db, "movie", tmdb_id="999999") is False


@pytest.mark.asyncio
async def test_record_and_check_by_tvdb_id(async_db):
    db = async_db
    await deleted_media.record_deletion(db, "show", "Breaking Bad", tvdb_id="81189")
    db.commit()

    assert await deleted_media.is_tombstoned(db, "show", tvdb_id="81189") is True
    # Un media_type different ne matche jamais, meme meme id (pas de collision cross-type).
    assert await deleted_media.is_tombstoned(db, "movie", tvdb_id="81189") is False


@pytest.mark.asyncio
async def test_record_without_any_stable_id_is_noop(async_db):
    """Sans tmdb/tvdb/imdb_id, impossible de retrouver l'entree plus tard -- ne rien
    ecrire plutot que polluer le journal avec des lignes inutilisables."""
    db = async_db
    await deleted_media.record_deletion(db, "movie", "Titre Sans Identifiant")
    db.commit()

    from sqlalchemy.future import select

    from app.models import DeletedMediaLog

    rows = (await db.execute(select(DeletedMediaLog))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_record_deletion_is_idempotent(async_db):
    """Supprimer deux fois le meme media (ex: re-supprime apres etre revenu) met a jour
    l'entree existante au lieu d'en creer une seconde."""
    db = async_db
    await deleted_media.record_deletion(db, "movie", "Dune", tmdb_id="438631", deleted_by="alice")
    db.commit()
    await deleted_media.record_deletion(db, "movie", "Dune", tmdb_id="438631", deleted_by="bob")
    db.commit()

    from sqlalchemy.future import select

    from app.models import DeletedMediaLog

    rows = (await db.execute(select(DeletedMediaLog).filter(DeletedMediaLog.tmdb_id == "438631"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].deleted_by == "bob"


@pytest.mark.asyncio
async def test_is_tombstoned_false_when_no_entries(async_db):
    db = async_db
    assert await deleted_media.is_tombstoned(db, "movie", tmdb_id="1") is False
