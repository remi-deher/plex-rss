"""Tests unitaires pour GET /api/health, GET /api/metrics et authentification API token."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db_async as get_db
from app.dependencies import require_admin, require_auth
from app.main import app
from app.models import ArrInstance, Base, MediaRequest, RequestStatus, Settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(async_db):
    return async_db


@pytest.fixture()
def client(db):
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def client_real_auth(db):
    """Client sans bypass d'auth — teste la vraie logique require_auth."""
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    app.dependency_overrides.pop(get_db, None)


def _settings(**kwargs) -> Settings:
    defaults = dict(
        sonarr_url="http://sonarr.local",
        sonarr_api_key="key",
        radarr_url="http://radarr.local",
        radarr_api_key="key",
        seer_enabled=False,
        plex_url="http://plex.local",
        plex_token="token",
        smtp_host="smtp.example.com",
        plex_rss_url="http://rss.local",
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _arr_instances() -> list[ArrInstance]:
    """Instances Sonarr/Radarr par défaut : /api/health résout via ArrInstance,
    pas directement via Settings.sonarr_url/radarr_url."""
    return [
        ArrInstance(
            name="Sonarr", arr_type="sonarr", url="http://sonarr.local", api_key="key", enabled=True, is_default=True
        ),
        ArrInstance(
            name="Radarr", arr_type="radarr", url="http://radarr.local", api_key="key", enabled=True, is_default=True
        ),
    ]


# ---------------------------------------------------------------------------
# /api/health — structure de la réponse
# ---------------------------------------------------------------------------


def test_health_returns_top_level_fields(client, db):
    """/health retourne status, checked_at et services."""
    db.add(_settings())
    db.commit()

    with (
        patch("app.routers.metrics_api.sonarr.check_connection", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.routers.metrics_api.radarr.check_connection", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.routers.metrics_api.plex_test", new=AsyncMock(return_value=(True, "OK"))),
    ):
        resp = client.get("/api/health")

    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "checked_at" in data
    assert "services" in data
    assert set(data["services"].keys()) >= {"sonarr", "radarr", "plex", "smtp", "rss", "seer"}


def test_health_all_ok_returns_healthy(client, db):
    """Tous les services up → status = healthy."""
    db.add(_settings())
    db.commit()

    with (
        patch("app.routers.metrics_api.sonarr.check_connection", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.routers.metrics_api.radarr.check_connection", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.routers.metrics_api.plex_test", new=AsyncMock(return_value=(True, "OK"))),
    ):
        resp = client.get("/api/health")

    assert resp.json()["status"] == "healthy"


def test_health_sonarr_down_returns_down(client, db):
    """Sonarr KO → status = down."""
    db.add(_settings())
    db.add_all(_arr_instances())
    db.commit()

    with (
        patch("app.routers.metrics_api.sonarr.check_connection", new=AsyncMock(return_value=(False, "refused"))),
        patch("app.routers.metrics_api.radarr.check_connection", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.routers.metrics_api.plex_test", new=AsyncMock(return_value=(True, "OK"))),
    ):
        resp = client.get("/api/health")

    data = resp.json()
    assert data["status"] == "down"
    assert data["services"]["sonarr"]["ok"] is False


def test_health_seer_down_returns_degraded(client, db):
    """Sonarr+Radarr+Plex OK mais Seer KO → status = degraded."""
    db.add(
        _settings(
            seer_enabled=True,
            seer_url="http://seer.local",
            seer_api_key="key",
            seer_send_requests=True,
        )
    )
    db.add_all(_arr_instances())
    db.commit()

    with (
        patch("app.routers.metrics_api.sonarr.check_connection", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.routers.metrics_api.radarr.check_connection", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.routers.metrics_api.plex_test", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.routers.metrics_api.seer_test", new=AsyncMock(return_value=(False, "refused"))),
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
    db.add_all(_arr_instances())
    db.commit()

    with (
        patch("app.routers.metrics_api.sonarr.check_connection", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.routers.metrics_api.radarr.check_connection", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.routers.metrics_api.plex_test", new=AsyncMock(return_value=(True, "OK"))),
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


# ---------------------------------------------------------------------------
# API token — gestion
# ---------------------------------------------------------------------------


def test_generate_token_returns_token(client, db):
    """POST /api/settings/token génère et retourne un token."""
    db.add(Settings(auth_username="admin", auth_password_hash="hash"))
    db.commit()

    resp = client.post("/api/settings/token")
    assert resp.status_code == 200
    data = resp.json()
    assert "api_token" in data
    assert len(data["api_token"]) > 20


def test_generate_token_stores_in_db(client, db):
    """Le token généré est persisté dans Settings."""
    db.add(Settings(auth_username="admin", auth_password_hash="hash"))
    db.commit()

    resp = client.post("/api/settings/token")
    token = resp.json()["api_token"]

    s = db.query(Settings).first()
    assert s.api_token == token


def test_token_status_active(client, db):
    """GET /api/settings/token indique active=True quand un token existe."""
    db.add(Settings(auth_username="admin", auth_password_hash="hash", api_token="mytoken"))
    db.commit()

    resp = client.get("/api/settings/token")
    assert resp.status_code == 200
    assert resp.json()["active"] is True


def test_token_status_inactive(client, db):
    """GET /api/settings/token indique active=False sans token."""
    db.add(Settings(auth_username="admin", auth_password_hash="hash"))
    db.commit()

    resp = client.get("/api/settings/token")
    assert resp.json()["active"] is False


def test_revoke_token(client, db):
    """DELETE /api/settings/token supprime le token."""
    db.add(Settings(auth_username="admin", auth_password_hash="hash", api_token="mytoken"))
    db.commit()

    resp = client.delete("/api/settings/token")
    assert resp.status_code == 200

    s = db.query(Settings).first()
    assert s.api_token is None


def test_generate_token_regenerates(client, db):
    """Deux appels successifs génèrent deux tokens différents."""
    db.add(Settings(auth_username="admin", auth_password_hash="hash"))
    db.commit()

    t1 = client.post("/api/settings/token").json()["api_token"]
    t2 = client.post("/api/settings/token").json()["api_token"]
    assert t1 != t2


# ---------------------------------------------------------------------------
# API token — authentification
# ---------------------------------------------------------------------------


def test_api_key_header_authenticates(client_real_auth, db):
    """X-Api-Key valide → 200 sans session cookie sur les routes /api/v1."""
    db.add(Settings(auth_username="admin", auth_password_hash="hash", api_token="secret-token"))
    db.commit()

    resp = client_real_auth.get("/api/v1/requests", headers={"X-Api-Key": "secret-token"})
    assert resp.status_code == 200


def test_wrong_api_key_returns_401(client_real_auth, db):
    """X-Api-Key invalide → 401."""
    db.add(Settings(auth_username="admin", auth_password_hash="hash", api_token="correct"))
    db.commit()

    resp = client_real_auth.get("/api/v1/requests", headers={"X-Api-Key": "wrong"})
    assert resp.status_code == 401


def test_no_auth_returns_401(client_real_auth, db):
    """Ni session ni header → 401."""
    db.add(Settings(auth_username="admin", auth_password_hash="hash"))
    db.commit()

    resp = client_real_auth.get("/api/v1/requests")
    assert resp.status_code == 401


def test_no_token_configured_rejects_any_key(client_real_auth, db):
    """Pas de token en DB → header X-Api-Key refusé."""
    db.add(Settings(auth_username="admin", auth_password_hash="hash"))
    db.commit()

    resp = client_real_auth.get("/api/v1/requests", headers={"X-Api-Key": "some-key"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/metrics/prometheus
# ---------------------------------------------------------------------------


def test_prometheus_returns_plain_text(client, db):
    """/api/metrics/prometheus retourne du text/plain."""
    resp = client.get("/api/metrics/prometheus")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]


def test_prometheus_contains_expected_metrics(client, db):
    """Le corps contient les noms de métriques Prometheus attendus."""
    resp = client.get("/api/metrics/prometheus")
    body = resp.text
    assert "plex_rss_poll_total" in body
    assert "plex_rss_arr_submissions_total" in body
    assert "plex_rss_notifications_sent_total" in body
    assert "plex_rss_requests_total" in body
    assert "plex_rss_requests_by_status" in body


def test_prometheus_reflects_db_counts(client, db):
    """Les gauges de statut reflètent les données DB."""
    db.add(MediaRequest(plex_user_id="u", plex_user="u", title="A", media_type="movie", status=RequestStatus.available))
    db.add(MediaRequest(plex_user_id="u", plex_user="u", title="B", media_type="movie", status=RequestStatus.failed))
    db.commit()

    body = client.get("/api/metrics/prometheus").text
    assert 'plex_rss_requests_by_status{status="available"} 1' in body
    assert 'plex_rss_requests_by_status{status="failed"} 1' in body
    assert "plex_rss_requests_total 2" in body


def test_prometheus_help_and_type_lines(client, db):
    """Chaque métrique a une ligne # HELP et # TYPE."""
    body = client.get("/api/metrics/prometheus").text
    assert "# HELP plex_rss_poll_total" in body
    assert "# TYPE plex_rss_poll_total counter" in body
    assert "# TYPE plex_rss_requests_by_status gauge" in body
