"""Tests unitaires pour services/download_history.py."""

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, DownloadHistory, Settings
from app.services.download_history import purge_old_entries
from app.utils import now_utc_naive
from tests.async_support import TestSession


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = TestSession(Session())
    yield session
    session.close()


def _old_entry(days_ago):
    return DownloadHistory(
        title="Ancien film",
        year=2020,
        media_type="movie",
        source="radarr",
        completed_at=now_utc_naive() - timedelta(days=days_ago),
    )


@pytest.mark.asyncio
async def test_purge_old_entries_skips_when_retention_is_none(db):
    """None sur notification_log_retention_days doit signifier conservation indefinie,
    pas un repli silencieux sur un DEFAULT_RETENTION_DAYS code en dur — regression :
    cette fonction ignorait auparavant la valeur None/0 et purgeait quand meme apres
    90 jours, contredisant ce que l'UI (checkbox "Conserver indefiniment") annonce."""
    settings = Settings(notification_log_retention_days=None)
    db.sync_session.add(settings)
    db.sync_session.add(_old_entry(days_ago=400))
    db.sync_session.commit()

    deleted = await purge_old_entries(db)

    assert deleted == 0
    assert db.sync_session.query(DownloadHistory).count() == 1


@pytest.mark.asyncio
async def test_purge_old_entries_deletes_beyond_configured_retention(db):
    settings = Settings(notification_log_retention_days=30)
    db.sync_session.add(settings)
    db.sync_session.add(_old_entry(days_ago=60))
    db.sync_session.commit()

    deleted = await purge_old_entries(db)

    assert deleted == 1
    assert db.sync_session.query(DownloadHistory).count() == 0
