"""Tests unitaires pour les endpoints /api/settings et /api/test/*."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import Settings
from app.routers.api import require_auth


def _mock_db(settings=None):
    db = MagicMock()
    db.query.return_value.first.return_value = settings
    db.commit = MagicMock()
    return db


def _default_settings():
    s = MagicMock(spec=Settings)
    s.plex_url = "http://plex.local"
    s.plex_token = "token123"
    s.plex_rss_url = "http://rss.local"
    s.sonarr_url = "http://sonarr.local"
    s.sonarr_api_key = "key"
    s.radarr_url = "http://radarr.local"
    s.radarr_api_key = "key"
    s.poll_interval_minutes = 5
    s.smtp_password = "real_password"
    return s


def _client_with_db(db):
    """Client de test avec auth bypassée et db mockée."""
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app, raise_server_exceptions=False)
    return client


def _cleanup():
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# /api/test/* — null guard sur Settings manquant
# ---------------------------------------------------------------------------


def test_test_sonarr_no_settings_returns_error():
    """Si Settings absent → réponse JSON success=False, pas de 500."""
    db = _mock_db(settings=None)
    client = _client_with_db(db)
    try:
        resp = client.post("/api/test/sonarr")
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert "initialisés" in resp.json()["message"]
    finally:
        _cleanup()


def test_test_radarr_no_settings_returns_error():
    """Si Settings absent → réponse JSON success=False pour radarr."""
    db = _mock_db(settings=None)
    client = _client_with_db(db)
    try:
        resp = client.post("/api/test/radarr")
        assert resp.status_code == 200
        assert resp.json()["success"] is False
    finally:
        _cleanup()


def test_test_plex_api_no_settings_returns_error():
    """Si Settings absent → réponse JSON success=False pour plex-api."""
    db = _mock_db(settings=None)
    client = _client_with_db(db)
    try:
        resp = client.post("/api/test/plex-api")
        assert resp.status_code == 200
        assert resp.json()["success"] is False
    finally:
        _cleanup()


# ---------------------------------------------------------------------------
# /api/settings PUT
# ---------------------------------------------------------------------------


def test_update_settings_no_settings_row_returns_404():
    """PUT /api/settings sans ligne Settings → 404."""
    db = _mock_db(settings=None)
    client = _client_with_db(db)
    try:
        resp = client.put("/api/settings", json={"plex_url": "http://test.local"})
        assert resp.status_code == 404
    finally:
        _cleanup()


def test_update_settings_smtp_mask_not_overwritten():
    """Le mot de passe masqué '••••••••' ne doit pas écraser le vrai mot de passe."""
    settings = _default_settings()
    db = _mock_db(settings=settings)
    client = _client_with_db(db)
    try:
        with patch("app.routers.api.update_poll_interval"):
            resp = client.put("/api/settings", json={"smtp_password": "••••••••"})
        assert resp.status_code == 200
        assert settings.smtp_password == "real_password"
    finally:
        _cleanup()


def test_update_settings_updates_field():
    """PUT /api/settings met à jour un champ correctement."""
    settings = _default_settings()
    db = _mock_db(settings=settings)
    client = _client_with_db(db)
    try:
        with patch("app.routers.api.update_poll_interval"):
            resp = client.put("/api/settings", json={"plex_url": "http://new-plex.local"})
        assert resp.status_code == 200
        assert settings.plex_url == "http://new-plex.local"
    finally:
        _cleanup()
