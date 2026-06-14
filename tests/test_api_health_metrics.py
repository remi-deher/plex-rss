"""Tests unitaires pour GET /api/health et GET /api/metrics."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base, MediaRequest, RequestStatus, Settings
from app.routers.api import require_auth

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def client(db):
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(get_db, None)


def _settings(**kwargs) -> Settings:
    defaults = dict(
        sonarr_url="http://sonarr.local",
        sonarr_api_key="key",
        radarr_url="http://radarr.local",
        radarr_api_key="key",
        overseerr_enabled=False,
        plex_url="http://plex.local",
        plex_token="token",
        smtp_host="smtp.example.com",
        plex_rss_url="http://rss.local",
    )
    defaults.update(kwargs)
    return Settings(**defaults)


# ---------------------------------------------------------------------------
# /api/health — structure de la réponse
# ---------------------------------------------------------------------------


def test_health_returns_top_level_fields(client, db):
    """/health retourne status, checked_at et services."""
    db.add(_settings())
    db.commit()

    with (
        patch("app.routers.api.sonarr.check_connection", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.routers.api.radarr.check_connection", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.routers.api.plex_test", new=AsyncMock(return_value=(True, "OK"))),
    ):
        resp = client.get("/api/health")

    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "checked_at" in data
    assert "services" in data
    assert set(data["services"].keys()) >= {"sonarr", "radarr", "plex", "smtp", "rss", "overseerr"}


def test_health_all_ok_returns_healthy(client, db):
    """Tous les services up → status = healthy."""
    db.add(_settings())
    db.commit()

    with (
        patch("app.routers.api.sonarr.check_connection", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.routers.api.radarr.check_connection", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.routers.api.plex_test", new=AsyncMock(return_value=(True, "OK"))),
    ):
        resp = client.get("/api/health")

    assert resp.json()["status"] == "healthy"


def test_health_sonarr_down_returns_down(client, db):
    """Sonarr KO → status = down."""
    db.add(_settings())
    db.commit()

    with (
        patch("app.routers.api.sonarr.check_connection", new=AsyncMock(return_value=(False, "refused"))),
        patch("app.routers.api.radarr.check_connection", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.routers.api.plex_test", new=AsyncMock(return_value=(True, "OK"))),
    ):
        resp = client.get("/api/health")

    data = resp.json()
    assert data["status"] == "down"
    assert data["services"]["sonarr"]["ok"] is False


def test_health_overseerr_down_returns_degraded(client, db):
    """Sonarr+Radarr+Plex OK mais Overseerr KO → status = degraded."""
    db.add(
        _settings(
            overseerr_enabled=True,
            overseerr_url="http://overseerr.local",
            overseerr_api_key="key",
        )
    )
    db.commit()

    with (
        patch("app.routers.api.sonarr.check_connection", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.routers.api.radarr.check_connection", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.routers.api.plex_test", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.routers.api.overseerr_test", new=AsyncMock(return_value=(False, "refused"))),
    ):
        resp = client.get("/api/health")

    assert resp.json()["status"] == "degraded"


def test_health_unconfigured_service_has_null_ok(client, db):
    """Service non configuré → ok = null, response_ms = null."""
    db.add(Settings())  # aucune URL configurée
    db.commit()

    resp = client.get("/api/health")
    data = resp.json()
    assert data["services"]["sonarr"]["ok"] is None
    assert data["services"]["sonarr"]["response_ms"] is None


def test_health_services_include_response_ms(client, db):
    """Les services checkés inclus response_ms (float ou int)."""
    db.add(_settings())
    db.commit()

    with (
        patch("app.routers.api.sonarr.check_connection", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.routers.api.radarr.check_connection", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.routers.api.plex_test", new=AsyncMock(return_value=(True, "OK"))),
    ):
        resp = client.get("/api/health")

    sonarr = resp.json()["services"]["sonarr"]
    assert sonarr["response_ms"] is not None
    assert isinstance(sonarr["response_ms"], (int, float))


def test_health_no_settings_returns_healthy_unconfigured(client, db):
    """Aucun Settings en DB → healthy (rien à tester = pas d'échec)."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


# ---------------------------------------------------------------------------
# /api/metrics — agrégats DB
# ---------------------------------------------------------------------------


def test_metrics_empty_db(client, db):
    """/metrics sur DB vide → total=0, success_rate=null."""
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["db"]["total_requests"] == 0
    assert data["db"]["success_rate_pct"] is None
    assert data["db"]["notifications"]["failure_rate_pct"] is None


def test_metrics_counts_by_status(client, db):
    """/metrics compte correctement available et failed."""
    db.add(
        MediaRequest(
            plex_user_id="u",
            plex_user="u",
            title="A",
            media_type="movie",
            status=RequestStatus.available,
            available_mail_sent=True,
        )
    )
    db.add(
        MediaRequest(
            plex_user_id="u",
            plex_user="u",
            title="B",
            media_type="movie",
            status=RequestStatus.available,
            available_mail_sent=True,
        )
    )
    db.add(MediaRequest(plex_user_id="u", plex_user="u", title="C", media_type="movie", status=RequestStatus.failed))
    db.commit()

    resp = client.get("/api/metrics")
    data = resp.json()["db"]
    assert data["total_requests"] == 3
    assert data["available"] == 2
    assert data["failed"] == 1
    assert data["success_rate_pct"] == round(2 / 3 * 100, 1)


def test_metrics_notification_failure_rate(client, db):
    """Taux d'échec notification calculé depuis available_mail_sent."""
    # 2 available avec mail envoyé, 1 available sans mail → 33.3%
    db.add(
        MediaRequest(
            plex_user_id="u",
            plex_user="u",
            title="A",
            media_type="movie",
            status=RequestStatus.available,
            available_mail_sent=True,
        )
    )
    db.add(
        MediaRequest(
            plex_user_id="u",
            plex_user="u",
            title="B",
            media_type="movie",
            status=RequestStatus.available,
            available_mail_sent=True,
        )
    )
    db.add(
        MediaRequest(
            plex_user_id="u",
            plex_user="u",
            title="C",
            media_type="movie",
            status=RequestStatus.available,
            available_mail_sent=False,
        )
    )
    db.commit()

    resp = client.get("/api/metrics")
    notif = resp.json()["db"]["notifications"]
    assert notif["sent"] == 2
    assert notif["missed"] == 1
    assert notif["failure_rate_pct"] == round(1 / 3 * 100, 1)


def test_metrics_runtime_section_present(client, db):
    """/metrics inclut une section runtime avec les clés attendues."""
    resp = client.get("/api/metrics")
    runtime = resp.json()["runtime"]
    assert "poll" in runtime
    assert "arr" in runtime
    assert "notifications" in runtime


# ---------------------------------------------------------------------------
# /api/stats/counts
# ---------------------------------------------------------------------------


def test_stats_counts_empty(client, db):
    """/stats/counts retourne 0 pour tous les statuts sur DB vide."""
    resp = client.get("/api/stats/counts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["failed"] == 0
    assert data["available"] == 0


def test_stats_counts_correct_values(client, db):
    """/stats/counts reflète les vraies données DB."""
    db.add(MediaRequest(plex_user_id="u", plex_user="u", title="A", media_type="movie", status=RequestStatus.available))
    db.add(MediaRequest(plex_user_id="u", plex_user="u", title="B", media_type="movie", status=RequestStatus.failed))
    db.add(
        MediaRequest(plex_user_id="u", plex_user="u", title="C", media_type="movie", status=RequestStatus.sent_to_arr)
    )
    db.commit()

    resp = client.get("/api/stats/counts")
    data = resp.json()
    assert data["available"] == 1
    assert data["failed"] == 1
    assert data["sent_to_arr"] == 1
    assert data["total"] == 3
