"""Tests unitaires pour app/routers/vff_api.py."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db_async as get_db
from app.dependencies import require_admin, require_auth
from app.main import app
from app.models import Base, LibraryItem, Settings
from app.routers.vff_api import _arr_image_url
from app.services.vff_scanner import vff_scan_state


@pytest.fixture()
def db(async_db):
    return async_db


@pytest.fixture()
def client(db):
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app, raise_server_exceptions=True)
    yield c
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# _arr_image_url
# ---------------------------------------------------------------------------


def test_arr_image_url_none_without_images():
    assert _arr_image_url(None) is None
    assert _arr_image_url([]) is None


def test_arr_image_url_prefers_requested_cover_type():
    images = [
        {"coverType": "fanart", "remoteUrl": "https://x/fanart.jpg"},
        {"coverType": "poster", "remoteUrl": "https://x/poster.jpg"},
    ]
    assert _arr_image_url(images, "poster", "fanart") == "https://x/poster.jpg"


def test_arr_image_url_falls_back_to_first_available():
    images = [{"coverType": "banner", "remoteUrl": "https://x/banner.jpg"}]
    assert _arr_image_url(images, "poster") == "https://x/banner.jpg"


def test_arr_image_url_prefers_remote_url_over_url():
    images = [{"coverType": "poster", "remoteUrl": "https://remote/p.jpg", "url": "https://local/p.jpg"}]
    assert _arr_image_url(images, "poster") == "https://remote/p.jpg"


def test_arr_image_url_uses_url_when_no_remote_url():
    images = [{"coverType": "poster", "url": "https://local/p.jpg"}]
    assert _arr_image_url(images, "poster") == "https://local/p.jpg"


# ---------------------------------------------------------------------------
# GET /api/vff/counts
# ---------------------------------------------------------------------------


def test_vff_counts_empty_library(client):
    resp = client.get("/api/vff/counts")
    assert resp.status_code == 200
    assert resp.json() == {"vo_pending": 0, "vf_available": 0, "unchecked": 0}


def test_vff_counts_reflects_library_state(db, client):
    db.add(LibraryItem(title="A", media_type="movie", has_vf=True))
    db.add(LibraryItem(title="B", media_type="movie", has_vf=False))
    db.add(LibraryItem(title="C", media_type="movie", has_vf=False))
    db.add(LibraryItem(title="D", media_type="movie", has_vf=None))
    db.commit()

    resp = client.get("/api/vff/counts")
    assert resp.status_code == 200
    assert resp.json() == {"vo_pending": 2, "vf_available": 1, "unchecked": 1}


# ---------------------------------------------------------------------------
# GET /api/vff/scan-status, /api/vff/sync-status
# ---------------------------------------------------------------------------


def test_vff_scan_status_returns_current_state(client):
    resp = client.get("/api/vff/scan-status")
    assert resp.status_code == 200
    assert resp.json() == vff_scan_state


def test_vff_sync_status_returns_current_state(client):
    resp = client.get("/api/vff/sync-status")
    assert resp.status_code == 200
    assert "status" in resp.json()


# ---------------------------------------------------------------------------
# POST /api/vff/scan (force flag)
# ---------------------------------------------------------------------------


def test_vff_scan_all_starts_without_force(client):
    with patch("app.scheduler.trigger_vff_scan_background") as trigger:
        resp = client.post("/api/vff/scan")
    assert resp.status_code == 200
    assert resp.json() == {"status": "started"}
    trigger.assert_called_once_with(force=False)


def test_vff_scan_all_with_force_invalidates_cache(db, client):
    from app.models import VfEpisodeStatus

    db.add(VfEpisodeStatus(source_type="request", source_id=1, season_number=1, episode_number=1, has_vf=True))
    db.commit()

    with patch("app.scheduler.trigger_vff_scan_background") as trigger:
        resp = client.post("/api/vff/scan?force=true")
    assert resp.status_code == 200
    assert db.query(VfEpisodeStatus).count() == 0
    trigger.assert_called_once_with(force=True)


# ---------------------------------------------------------------------------
# POST /api/requests/{id}/vff-scan — gating (settings requises)
# ---------------------------------------------------------------------------


def test_vff_scan_single_request_404_when_missing(client):
    resp = client.post("/api/requests/9999/vff-scan")
    assert resp.status_code == 404


def test_vff_scan_single_request_400_without_settings(db, client):
    from app.models import MediaRequest, RequestStatus

    req = MediaRequest(
        plex_user_id="alice", plex_user="Alice", title="Inception", media_type="movie", status=RequestStatus.available
    )
    db.add(req)
    db.commit()

    resp = client.post(f"/api/requests/{req.id}/vff-scan")
    assert resp.status_code == 400
    assert "Settings" in resp.json()["detail"]


def test_vff_scan_single_request_400_when_vff_disabled(db, client):
    from app.models import MediaRequest, RequestStatus

    db.add(Settings(vff_enabled=False))
    req = MediaRequest(
        plex_user_id="alice", plex_user="Alice", title="Inception", media_type="movie", status=RequestStatus.available
    )
    db.add(req)
    db.commit()

    resp = client.post(f"/api/requests/{req.id}/vff-scan")
    assert resp.status_code == 400
    assert "disabled" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /requests/{id}/episodes, /episodes-availability, /episodes-vf-status
# (chargement progressif de l'accordeon saisons/episodes, voir arr_orphans-style
# refactor: enveloppe TMDB / disponibilite Sonarr / statut VF sont 3 sources
# independantes, chacune testee separement)
# ---------------------------------------------------------------------------


def _show_request(db, **kwargs):
    from app.models import MediaRequest, RequestStatus

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


def test_episodes_envelope_uses_tmdb_only(db, client):
    """L'enveloppe vient uniquement de TMDB -- aucun appel Sonarr/Radarr necessaire,
    c'est ce qui la rend rapide."""
    req = _show_request(db)
    overview = [{"season_number": 1, "name": "Season 1", "episode_count": 2}]
    episodes = [
        {"episode_number": 1, "title": "Pilot", "air_date": "2020-01-01", "overview": "", "still_url": None},
        {"episode_number": 2, "title": "Ep 2", "air_date": "2020-01-08", "overview": "", "still_url": None},
    ]
    with (
        patch("app.routers.vff_api.tmdb.get_tv_seasons_overview", new=AsyncMock(return_value=overview)),
        patch("app.routers.vff_api.tmdb.get_tv_season_episodes", new=AsyncMock(return_value=episodes)),
        patch("app.routers.vff_api.lookup_series") as mock_sonarr,
    ):
        resp = client.get(f"/api/requests/{req.id}/episodes")
        mock_sonarr.assert_not_called()
    assert resp.status_code == 200
    data = resp.json()
    assert data["media_type"] == "show"
    assert data["seasons"] == [{"season_number": 1, "name": "Season 1", "episodes": episodes}]


def test_episodes_envelope_handles_multiple_seasons_sequentially(db, client):
    """Plusieurs saisons ne doivent pas etre recuperees en parallele (asyncio.gather) --
    elles partagent la meme AsyncSession (cache TMDB en DB), ce qui declenche
    'concurrent operations are not permitted' des que 2+ saisons existent."""
    req = _show_request(db)
    overview = [
        {"season_number": 1, "name": "Season 1", "episode_count": 1},
        {"season_number": 2, "name": "Season 2", "episode_count": 1},
        {"season_number": 3, "name": "Season 3", "episode_count": 1},
    ]

    async def fake_get_episodes(db_arg, tmdb_id, season_number):
        return [{"episode_number": 1, "title": f"S{season_number}E1", "air_date": None, "overview": "", "still_url": None}]

    with patch("app.routers.vff_api.tmdb.get_tv_seasons_overview", new=AsyncMock(return_value=overview)):
        with patch("app.routers.vff_api.tmdb.get_tv_season_episodes", new=AsyncMock(side_effect=fake_get_episodes)) as mock_ep:
            resp = client.get(f"/api/requests/{req.id}/episodes")
    assert resp.status_code == 200
    data = resp.json()
    assert [s["season_number"] for s in data["seasons"]] == [1, 2, 3]
    assert mock_ep.await_count == 3


def test_episodes_envelope_tmdb_failure_returns_502_not_empty(db, client):
    """Une panne TMDB (ou l'erreur de concurrence SQLAlchemy) doit remonter comme une
    vraie erreur -- pas un 200 avec seasons=[] qui ressemble a tort a 'aucune saison'."""
    req = _show_request(db)
    with patch("app.routers.vff_api.tmdb.get_tv_seasons_overview", new=AsyncMock(side_effect=Exception("boom"))):
        resp = client.get(f"/api/requests/{req.id}/episodes")
    assert resp.status_code == 502


def test_episodes_envelope_movie_returns_empty_seasons(db, client):
    from app.models import MediaRequest, RequestStatus

    req = MediaRequest(
        plex_user_id="alice", plex_user="Alice", title="Movie", media_type="movie", status=RequestStatus.sent_to_arr,
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    resp = client.get(f"/api/requests/{req.id}/episodes")
    assert resp.status_code == 200
    assert resp.json() == {"media_type": "movie", "seasons": []}


def test_episodes_availability_uses_sonarr_hasfile(db, client):
    from app.cache import cache

    req = _show_request(db)
    cache._memory.clear()
    sonarr_series = {"id": 42, "seasons": []}
    sonarr_episodes = [
        {"seasonNumber": 1, "episodeNumber": 1, "monitored": True, "hasFile": True},
        {"seasonNumber": 1, "episodeNumber": 2, "monitored": True, "hasFile": False},
        {"seasonNumber": 0, "episodeNumber": 1, "monitored": True, "hasFile": True},  # saison 0 exclue
    ]
    with (
        patch("app.routers.vff_api._resolve_arr_instance", new=AsyncMock(return_value=type("I", (), {"url": "http://sonarr", "api_key": "x"})())),
        patch("app.routers.vff_api.lookup_series", new=AsyncMock(return_value=sonarr_series)),
        patch("app.routers.vff_api.get_episodes", new=AsyncMock(return_value=sonarr_episodes)),
    ):
        resp = client.get(f"/api/requests/{req.id}/episodes-availability")
    assert resp.status_code == 200
    data = resp.json()
    assert data["seasons"] == [{"season_number": 1, "episodes": {"1": True, "2": False}}]


def test_episodes_vf_status_is_pure_db_read(db, client):
    """Aucun appel reseau : uniquement la lecture de VfEpisodeStatus, deja alimentee
    par le poller en tache de fond."""
    from app.models import VfEpisodeStatus

    req = _show_request(db)
    db.add(VfEpisodeStatus(source_type="request", source_id=req.id, season_number=1, episode_number=1, has_vf=True, fr_is_default=True))
    db.add(VfEpisodeStatus(source_type="request", source_id=req.id, season_number=1, episode_number=2, has_vf=False))
    db.commit()

    with patch("app.routers.vff_api.lookup_series") as mock_sonarr:
        resp = client.get(f"/api/requests/{req.id}/episodes-vf-status")
        mock_sonarr.assert_not_called()
    assert resp.status_code == 200
    data = resp.json()
    seasons = {s["season_number"]: s["episodes"] for s in data["seasons"]}
    assert seasons[1] == {"1": "vf", "2": "vo"}
