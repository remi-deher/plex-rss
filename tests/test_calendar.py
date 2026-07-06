"""Tests pour l'endpoint /api/calendar (agrégation Sonarr/Radarr + croisement suivi)."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import ArrInstance, Base, LibraryItem, MediaRequest, RequestStatus
from app.routers.api import unified_calendar


def _make_db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


@pytest.mark.asyncio
async def test_calendar_marks_tracked_show_and_reuses_poster():
    db = _make_db()
    db.add(ArrInstance(id=1, name="Sonarr", arr_type="sonarr", url="http://sonarr", api_key="key", enabled=True))
    db.add(LibraryItem(title="Breaking Bad", media_type="show", tvdb_id="81189", poster_url="http://poster/bb.jpg"))
    db.commit()

    episodes = [{
        "seasonNumber": 1, "episodeNumber": 1, "airDateUtc": "2026-07-10T00:00:00Z",
        "title": "Pilot", "hasFile": False,
        "series": {"title": "Breaking Bad", "tvdbId": 81189},
    }]
    with patch("app.routers.api.sonarr.get_calendar", new=AsyncMock(return_value=episodes)):
        events = await unified_calendar(start=None, end=None, tracked_only=False, db=db)

    assert len(events) == 1
    e = events[0]
    assert e["type"] == "episode"
    assert e["tracked"] is True
    assert e["poster_url"] == "http://poster/bb.jpg"
    assert e["subtitle"] == "S01E01 — Pilot"


@pytest.mark.asyncio
async def test_calendar_untracked_movie_marked_not_tracked():
    db = _make_db()
    db.add(ArrInstance(id=2, name="Radarr", arr_type="radarr", url="http://radarr", api_key="key", enabled=True))
    db.commit()

    movies = [{"title": "Unknown Movie", "tmdbId": 99999, "hasFile": False, "inCinemas": "2026-07-12T00:00:00Z"}]
    with patch("app.routers.api.radarr.get_calendar", new=AsyncMock(return_value=movies)):
        events = await unified_calendar(start=None, end=None, tracked_only=False, db=db)

    assert len(events) == 1
    assert events[0]["tracked"] is False
    assert events[0]["poster_url"] is None


@pytest.mark.asyncio
async def test_calendar_tracked_only_filters_out_untracked():
    db = _make_db()
    db.add(ArrInstance(id=2, name="Radarr", arr_type="radarr", url="http://radarr", api_key="key", enabled=True))
    db.commit()

    movies = [{"title": "Untracked Movie", "tmdbId": 12345, "hasFile": False, "inCinemas": "2026-07-12T00:00:00Z"}]
    with patch("app.routers.api.radarr.get_calendar", new=AsyncMock(return_value=movies)):
        events = await unified_calendar(start=None, end=None, tracked_only=True, db=db)

    assert events == []


@pytest.mark.asyncio
async def test_calendar_falls_back_to_request_when_no_library_item():
    db = _make_db()
    db.add(ArrInstance(id=2, name="Radarr", arr_type="radarr", url="http://radarr", api_key="key", enabled=True))
    db.add(
        MediaRequest(
            plex_user_id="alice", title="Dune", media_type="movie", tmdb_id="438631",
            status=RequestStatus.sent_to_arr, poster_url="http://poster/dune.jpg",
        )
    )
    db.commit()

    movies = [{"title": "Dune", "tmdbId": 438631, "hasFile": False, "inCinemas": "2026-07-20T00:00:00Z"}]
    with patch("app.routers.api.radarr.get_calendar", new=AsyncMock(return_value=movies)):
        events = await unified_calendar(start=None, end=None, tracked_only=False, db=db)

    assert len(events) == 1
    assert events[0]["tracked"] is True
    assert events[0]["poster_url"] == "http://poster/dune.jpg"
    assert events[0]["request_id"] is not None


@pytest.mark.asyncio
async def test_calendar_ignores_disabled_instances():
    db = _make_db()
    db.add(ArrInstance(id=1, name="Sonarr", arr_type="sonarr", url="http://sonarr", api_key="key", enabled=False))
    db.commit()

    with patch("app.routers.api.sonarr.get_calendar", new=AsyncMock(return_value=[{"foo": "bar"}])) as mock_cal:
        events = await unified_calendar(start=None, end=None, tracked_only=False, db=db)

    mock_cal.assert_not_called()
    assert events == []


@pytest.mark.asyncio
async def test_calendar_advanced_filtering():
    db = _make_db()
    db.add(ArrInstance(id=1, name="Sonarr", arr_type="sonarr", url="http://sonarr", api_key="key", enabled=True))
    db.add(ArrInstance(id=2, name="Radarr", arr_type="radarr", url="http://radarr", api_key="key", enabled=True))
    db.add(LibraryItem(id=10, title="Breaking Bad", media_type="show", tvdb_id="81189", has_vf=True, poster_url="http://poster/bb.jpg"))
    db.add(
        MediaRequest(
            id=50, plex_user_id="alice", title="Dune", media_type="movie", tmdb_id="438631",
            status=RequestStatus.sent_to_arr, has_vf=False, poster_url="http://poster/dune.jpg"
        )
    )
    db.commit()

    episodes = [{
        "seasonNumber": 1, "episodeNumber": 1, "airDateUtc": "2026-07-10T00:00:00Z",
        "title": "Pilot", "hasFile": False,
        "series": {"title": "Breaking Bad", "tvdbId": 81189},
    }]
    movies = [{"title": "Dune", "tmdbId": 438631, "hasFile": False, "inCinemas": "2026-07-20T00:00:00Z"}]

    with patch("app.routers.api.sonarr.get_calendar", new=AsyncMock(return_value=episodes)), \
         patch("app.routers.api.radarr.get_calendar", new=AsyncMock(return_value=movies)):

        # 1. Filtre par type=movie
        evs = await unified_calendar(type="movie", db=db)
        assert len(evs) == 1
        assert evs[0]["title"] == "Dune"

        # 2. Filtre par type=show
        evs = await unified_calendar(type="show", db=db)
        assert len(evs) == 1
        assert evs[0]["title"] == "Breaking Bad"

        # 3. Filtre par search=bad
        evs = await unified_calendar(search="bad", db=db)
        assert len(evs) == 1
        assert evs[0]["title"] == "Breaking Bad"

        # 4. Filtre par user=alice
        evs = await unified_calendar(user="alice", db=db)
        assert len(evs) == 1
        assert evs[0]["title"] == "Dune"

        # 5. Filtre par status=sent_to_arr
        evs = await unified_calendar(status="sent_to_arr", db=db)
        assert len(evs) == 1
        assert evs[0]["title"] == "Dune"

        # 6. Filtre par vf=vf (devrait renvoyer Breaking Bad car has_vf=True et in_library=True)
        evs = await unified_calendar(vf="vf", db=db)
        assert len(evs) == 1
        assert evs[0]["title"] == "Breaking Bad"

        # 7. Filtre par vf=requested (devrait renvoyer Dune car in_library=False)
        evs = await unified_calendar(vf="requested", db=db)
        assert len(evs) == 1
        assert evs[0]["title"] == "Dune"

