"""Tests unitaires pour les endpoints /api/settings et /api/test/*."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_db_async as get_db
from app.dependencies import require_admin, require_auth
from app.main import app
from app.models import Settings


def _mock_db(settings=None):
    db = MagicMock()
    db.query.return_value.first.return_value = settings
    db.commit = MagicMock()
    return db


def _default_settings():
    return Settings(
        plex_url="http://plex.local",
        plex_token="token123",
        plex_rss_url="http://rss.local",
        sonarr_url="http://sonarr.local",
        sonarr_api_key="key",
        radarr_url="http://radarr.local",
        radarr_api_key="key",
        poll_interval_minutes=5,
        smtp_password="real_password",
    )


def _client_with_db(db):
    """Client de test avec auth bypassée et db mockée."""
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app, raise_server_exceptions=False)
    return client


def _cleanup():
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# /api/test/* — null guard sur Settings manquant
# ---------------------------------------------------------------------------


def test_test_sonarr_no_settings_returns_error(async_db):
    """Si Settings absent → réponse JSON success=False, pas de 500."""
    client = _client_with_db(async_db)
    try:
        resp = client.post("/api/test/sonarr")
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert "initialisés" in resp.json()["message"]
    finally:
        _cleanup()


def test_test_radarr_no_settings_returns_error(async_db):
    """Si Settings absent → réponse JSON success=False pour radarr."""
    client = _client_with_db(async_db)
    try:
        resp = client.post("/api/test/radarr")
        assert resp.status_code == 200
        assert resp.json()["success"] is False
    finally:
        _cleanup()


def test_test_plex_api_no_settings_returns_error(async_db):
    """Si Settings absent → réponse JSON success=False pour plex-api."""
    client = _client_with_db(async_db)
    try:
        resp = client.post("/api/test/plex-api")
        assert resp.status_code == 200
        assert resp.json()["success"] is False
    finally:
        _cleanup()


# ---------------------------------------------------------------------------
# /api/settings PUT
# ---------------------------------------------------------------------------


def test_update_settings_no_settings_row_returns_404(async_db):
    """PUT /api/settings sans ligne Settings → 404."""
    client = _client_with_db(async_db)
    try:
        resp = client.put("/api/settings", json={"plex_url": "http://test.local"})
        assert resp.status_code == 404
    finally:
        _cleanup()


def test_update_settings_smtp_mask_not_overwritten(async_db):
    """Le mot de passe masqué '••••••••' ne doit pas écraser le vrai mot de passe."""
    settings = _default_settings()
    async_db.add(settings)
    async_db.commit()
    client = _client_with_db(async_db)
    try:
        with patch("app.routers.settings_api.update_poll_interval"):
            resp = client.put("/api/settings", json={"smtp_password": "••••••••"})
        assert resp.status_code == 200
        assert settings.smtp_password == "real_password"
    finally:
        _cleanup()


def test_update_settings_updates_field(async_db):
    """PUT /api/settings met à jour un champ correctement."""
    settings = _default_settings()
    async_db.add(settings)
    async_db.commit()
    client = _client_with_db(async_db)
    try:
        with patch("app.routers.settings_api.update_poll_interval"):
            resp = client.put("/api/settings", json={"plex_url": "http://new-plex.local"})
        assert resp.status_code == 200
        assert settings.plex_url == "http://new-plex.local"
    finally:
        _cleanup()


def test_update_settings_retention_zero_means_unlimited(async_db):
    """0 pour les retentions journaux/polling doit se traduire par None (illimite)."""
    settings = _default_settings()
    settings.notification_log_retention_days = 30
    settings.poll_history_retention_days = 30
    async_db.add(settings)
    async_db.commit()
    client = _client_with_db(async_db)
    try:
        with patch("app.routers.settings_api.update_poll_interval"):
            resp = client.put(
                "/api/settings",
                json={"notification_log_retention_days": 0, "poll_history_retention_days": 0},
            )
        assert resp.status_code == 200
        assert settings.notification_log_retention_days is None
        assert settings.poll_history_retention_days is None
    finally:
        _cleanup()


def test_update_settings_retention_clear_to_empty_means_unlimited(async_db):
    """Régression : vider le champ dans l'UI (envoie null) doit aussi persister comme
    illimité — avant l'ajout aux _nullable_fields, un null pour ces deux champs était
    silencieusement ignoré et l'ancienne valeur numérique restait en base pour toujours."""
    settings = _default_settings()
    settings.notification_log_retention_days = 30
    settings.poll_history_retention_days = 30
    async_db.add(settings)
    async_db.commit()
    client = _client_with_db(async_db)
    try:
        with patch("app.routers.settings_api.update_poll_interval"):
            resp = client.put(
                "/api/settings",
                json={"notification_log_retention_days": None, "poll_history_retention_days": None},
            )
        assert resp.status_code == 200
        assert settings.notification_log_retention_days is None
        assert settings.poll_history_retention_days is None
    finally:
        _cleanup()


def test_update_settings_does_not_wipe_email_templates(async_db):
    """Régression : email_request_template/subject (et les autres modèles/sujets) sont
    gérés par /api/email-templates, pas par ce formulaire général — ils sont absents du
    payload envoyé par settingsForm.js. Pydantic les redéfaut donc à None à chaque
    sauvegarde d'un AUTRE onglet (ex: Connexions). Avant le fix, ces champs étaient dans
    _nullable_fields et se retrouvaient donc effacés en base à chaque save non lié."""
    settings = _default_settings()
    settings.email_request_template = "<p>Bonjour {nom_utilisateur}</p>"
    settings.email_request_subject = "Nouvelle demande : {titre}"
    settings.email_templates_backup = '{"email_request_template": "old"}'
    async_db.add(settings)
    async_db.commit()
    client = _client_with_db(async_db)
    try:
        with patch("app.routers.settings_api.update_poll_interval"):
            resp = client.put("/api/settings", json={"plex_url": "http://new-plex.local"})
        assert resp.status_code == 200
        assert settings.plex_url == "http://new-plex.local"
        assert settings.email_request_template == "<p>Bonjour {nom_utilisateur}</p>"
        assert settings.email_request_subject == "Nouvelle demande : {titre}"
        assert settings.email_templates_backup == '{"email_request_template": "old"}'
    finally:
        _cleanup()
