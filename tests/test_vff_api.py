"""Tests unitaires pour app/routers/vff_api.py."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.dependencies import require_admin, require_auth
from app.main import app
from app.models import Base, LibraryItem, Settings
from app.routers.vff_api import _arr_image_url
from app.services.vff_scanner import vff_scan_state


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


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
    resp = client.post("/api/vff/scan")
    assert resp.status_code == 200
    assert resp.json() == {"status": "started"}


def test_vff_scan_all_with_force_invalidates_cache(db, client):
    from app.models import VfEpisodeStatus

    db.add(VfEpisodeStatus(source_type="request", source_id=1, season_number=1, episode_number=1, has_vf=True))
    db.commit()

    resp = client.post("/api/vff/scan?force=true")
    assert resp.status_code == 200
    assert db.query(VfEpisodeStatus).count() == 0


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
