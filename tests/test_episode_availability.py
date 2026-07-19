"""Tests pour la synchronisation en arriere-plan de la disponibilite Sonarr par
episode (voir app/services/episode_availability.py)."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import ArrInstance, Base, EpisodeAvailability, LibraryItem, MediaRequest, RequestStatus
from app.services.episode_availability import check_episode_availability, sync_episode_availability_for_show
from tests.async_support import TestSession


def _make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return TestSession(sessionmaker(bind=engine)())


def _show_request(db, **kwargs):
    defaults = dict(
        plex_user_id="alice", plex_user="Alice", title="Show", media_type="show",
        status=RequestStatus.sent_to_arr, tmdb_id="123", tvdb_id="456", arr_id=42, arr_instance_id=1,
    )
    defaults.update(kwargs)
    req = MediaRequest(**defaults)
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


@pytest.mark.asyncio
async def test_sync_episode_availability_for_show_persists_rows():
    db = _make_db()
    req = _show_request(db)
    inst = ArrInstance(id=1, name="Sonarr", arr_type="sonarr", url="http://sonarr", api_key="x", enabled=True)
    sonarr_episodes = [
        {"seasonNumber": 1, "episodeNumber": 1, "monitored": True, "hasFile": True, "airDateUtc": "2020-01-01T01:00:00Z"},
        {"seasonNumber": 1, "episodeNumber": 2, "monitored": True, "hasFile": False, "airDateUtc": "2099-01-01T01:00:00Z"},
        {"seasonNumber": 0, "episodeNumber": 1, "monitored": True, "hasFile": True},  # saison 0 exclue
        {"seasonNumber": 1, "episodeNumber": 3, "monitored": False, "hasFile": True},  # non surveille, exclu
    ]
    with (
        patch("app.services.episode_availability.lookup_series", new=AsyncMock(return_value={"id": 42})),
        patch("app.services.episode_availability.get_episodes", new=AsyncMock(return_value=sonarr_episodes)),
    ):
        await sync_episode_availability_for_show(db, inst, req)
    db.commit()

    rows = db.query(EpisodeAvailability).filter(EpisodeAvailability.source_id == req.id).all()
    by_ep = {r.episode_number: r for r in rows}
    assert set(by_ep) == {1, 2}
    assert by_ep[1].has_file is True
    assert by_ep[1].air_date_utc == "2020-01-01T01:00:00Z"
    assert by_ep[2].has_file is False


@pytest.mark.asyncio
async def test_sync_episode_availability_for_show_updates_existing_row():
    db = _make_db()
    req = _show_request(db)
    db.add(EpisodeAvailability(source_type="request", source_id=req.id, season_number=1, episode_number=1, has_file=False, air_date_utc=None))
    db.commit()

    inst = ArrInstance(id=1, name="Sonarr", arr_type="sonarr", url="http://sonarr", api_key="x", enabled=True)
    sonarr_episodes = [
        {"seasonNumber": 1, "episodeNumber": 1, "monitored": True, "hasFile": True, "airDateUtc": "2020-01-01T01:00:00Z"},
    ]
    with (
        patch("app.services.episode_availability.lookup_series", new=AsyncMock(return_value={"id": 42})),
        patch("app.services.episode_availability.get_episodes", new=AsyncMock(return_value=sonarr_episodes)),
    ):
        await sync_episode_availability_for_show(db, inst, req)
    db.commit()

    assert db.query(EpisodeAvailability).count() == 1
    row = db.query(EpisodeAvailability).first()
    assert row.has_file is True
    assert row.air_date_utc == "2020-01-01T01:00:00Z"


@pytest.mark.asyncio
async def test_check_episode_availability_covers_requests_and_library_items():
    """Le job planifie doit couvrir a la fois les MediaRequest et les LibraryItem
    (series) -- un LibraryItem materialise depuis 'Suivi Sonarr' doit beneficier du
    meme rafraichissement en arriere-plan qu'une demande classique."""
    db = _make_db()
    req = _show_request(db, title="Requested Show")
    lib = LibraryItem(title="Library Show", media_type="show", tvdb_id="789", arr_id=99, arr_instance_id=1)
    db.add(lib)
    db.add(ArrInstance(id=1, name="Sonarr", arr_type="sonarr", url="http://sonarr", api_key="x", enabled=True, is_default=True))
    db.commit()
    db.refresh(lib)
    req_id, lib_id = req.id, lib.id

    sonarr_episodes = [
        {"seasonNumber": 1, "episodeNumber": 1, "monitored": True, "hasFile": True, "airDateUtc": "2020-01-01T01:00:00Z"},
    ]
    with (
        patch("app.services.episode_availability.AsyncSessionLocal", return_value=db),
        patch("app.services.episode_availability.lookup_series", new=AsyncMock(return_value={"id": 1})),
        patch("app.services.episode_availability.get_episodes", new=AsyncMock(return_value=sonarr_episodes)),
    ):
        await check_episode_availability()

    req_rows = db.query(EpisodeAvailability).filter(EpisodeAvailability.source_type == "request", EpisodeAvailability.source_id == req_id).all()
    lib_rows = db.query(EpisodeAvailability).filter(EpisodeAvailability.source_type == "library_item", EpisodeAvailability.source_id == lib_id).all()
    assert len(req_rows) == 1
    assert len(lib_rows) == 1


@pytest.mark.asyncio
async def test_check_episode_availability_skips_when_already_running():
    from app.services import episode_availability as mod

    db = _make_db()
    mod.episode_availability_state["status"] = "running"
    try:
        with patch("app.services.episode_availability.AsyncSessionLocal", return_value=db) as mock_session:
            await check_episode_availability()
            mock_session.assert_not_called()
    finally:
        mod.episode_availability_state["status"] = "idle"
