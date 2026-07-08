"""Tests unitaires pour les endpoints de notification :
GET  /api/notifications/log
POST /api/notifications/{id}/resend
POST /api/users/{id}/test-email
GET  /api/email/preview
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.dependencies import require_auth

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client_with_db(db):
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, raise_server_exceptions=False)


def _cleanup():
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(get_db, None)


def _make_log(
    log_id=1,
    event="request",
    recipient="user@example.com",
    is_admin=False,
    media_title="Inception",
    media_type="movie",
    success=True,
    error_msg=None,
    req_id=42,
    sent_at=None,
):
    from datetime import datetime, timezone

    log = MagicMock()
    log.id = log_id
    log.event = event
    log.recipient = recipient
    log.is_admin = is_admin
    log.media_title = media_title
    log.media_type = media_type
    log.success = success
    log.error_msg = error_msg
    log.req_id = req_id
    log.sent_at = sent_at or datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    return log


def _make_user(
    user_id=1, notification_email="user@example.com", plex_email=None, display_name="Alice", custom_name=None
):
    u = MagicMock()
    u.id = user_id
    u.notification_email = notification_email
    u.plex_email = plex_email
    u.display_name = display_name
    u.custom_name = custom_name
    u.plex_user_id = "alice"
    return u


def _make_settings():
    s = MagicMock()
    s.smtp_host = "smtp.example.com"
    s.smtp_port = 587
    s.smtp_user = "user@example.com"
    s.smtp_password = "pass"
    s.smtp_from = "noreply@example.com"
    s.smtp_tls = True
    s.email_request_template = None
    s.email_available_template = None
    return s


def _make_req(req_id=42, title="Inception", media_type="movie"):
    r = MagicMock()
    r.id = req_id
    r.title = title
    r.media_type = media_type
    return r


# ---------------------------------------------------------------------------
# GET /api/notifications/log
# ---------------------------------------------------------------------------


def test_list_logs_returns_paginated_structure():
    """La réponse contient total, offset, limit, items."""
    log = _make_log()
    db = MagicMock()
    q = db.query.return_value.order_by.return_value
    q.count.return_value = 1
    q.offset.return_value.limit.return_value.all.return_value = [log]

    client = _client_with_db(db)
    try:
        r = client.get("/api/notifications/log")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["offset"] == 0
        assert data["limit"] == 50
        assert len(data["items"]) == 1
    finally:
        _cleanup()


def test_list_logs_item_fields():
    """Chaque item contient tous les champs attendus."""
    log = _make_log(
        log_id=7,
        event="available",
        recipient="admin@b.com",
        is_admin=True,
        media_title="Dune",
        media_type="movie",
        success=False,
        error_msg="SMTP down",
        req_id=10,
    )
    db = MagicMock()
    q = db.query.return_value.order_by.return_value
    q.count.return_value = 1
    q.offset.return_value.limit.return_value.all.return_value = [log]

    client = _client_with_db(db)
    try:
        r = client.get("/api/notifications/log")
        item = r.json()["items"][0]
        assert item["id"] == 7
        assert item["event"] == "available"
        assert item["recipient"] == "admin@b.com"
        assert item["is_admin"] is True
        assert item["media_title"] == "Dune"
        assert item["success"] is False
        assert item["error_msg"] == "SMTP down"
        assert item["req_id"] == 10
    finally:
        _cleanup()


def test_list_logs_pagination_offset():
    """Le paramètre offset est transmis à la query."""
    db = MagicMock()
    q = db.query.return_value.order_by.return_value
    q.count.return_value = 100
    q.offset.return_value.limit.return_value.all.return_value = []

    client = _client_with_db(db)
    try:
        r = client.get("/api/notifications/log?offset=20&limit=10")
        assert r.status_code == 200
        data = r.json()
        assert data["offset"] == 20
        assert data["limit"] == 10
        # Vérifie que offset a bien été utilisé sur la query
        q.offset.assert_called_with(20)
    finally:
        _cleanup()


def test_list_logs_limit_capped_at_200():
    """Le limit est plafonné à 200 même si le client demande plus."""
    db = MagicMock()
    q = db.query.return_value.order_by.return_value
    q.count.return_value = 0
    q.offset.return_value.limit.return_value.all.return_value = []

    client = _client_with_db(db)
    try:
        client.get("/api/notifications/log?limit=999")
        # min(999, 200) = 200 doit être passé à .limit()
        q.offset.return_value.limit.assert_called_with(200)
    finally:
        _cleanup()


def test_list_logs_empty():
    """Aucun log → items=[], total=0."""
    db = MagicMock()
    q = db.query.return_value.order_by.return_value
    q.count.return_value = 0
    q.offset.return_value.limit.return_value.all.return_value = []

    client = _client_with_db(db)
    try:
        r = client.get("/api/notifications/log")
        assert r.status_code == 200
        assert r.json()["total"] == 0
        assert r.json()["items"] == []
    finally:
        _cleanup()


# ---------------------------------------------------------------------------
# POST /api/notifications/{id}/resend
# ---------------------------------------------------------------------------


def test_resend_queues_notification():
    """Resend valide → statut 200 + queued."""
    log = _make_log(log_id=1, req_id=42, event="request", recipient="u@b.com")
    req = _make_req(req_id=42)

    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [log, req]

    mock_enqueue = MagicMock()
    client = _client_with_db(db)
    try:
        with patch("app.routers.notifications_api.enqueue_notification", mock_enqueue):
            r = client.post("/api/notifications/1/resend")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "queued"
        assert data["recipient"] == "u@b.com"
        assert data["event"] == "request"
        mock_enqueue.assert_called_once_with("request", 42, ["u@b.com"])
    finally:
        _cleanup()


def test_resend_404_when_log_not_found():
    """Log introuvable → 404."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    client = _client_with_db(db)
    try:
        r = client.post("/api/notifications/999/resend")
        assert r.status_code == 404
    finally:
        _cleanup()


def test_resend_400_when_no_req_id():
    """Log sans req_id (ancien format) → 400."""
    log = _make_log(log_id=1, req_id=None)

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = log

    client = _client_with_db(db)
    try:
        r = client.post("/api/notifications/1/resend")
        assert r.status_code == 400
    finally:
        _cleanup()


def test_resend_404_when_original_request_not_found():
    """Log avec req_id, mais MediaRequest supprimée → 404."""
    log = _make_log(log_id=1, req_id=42)

    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [log, None]

    client = _client_with_db(db)
    try:
        r = client.post("/api/notifications/1/resend")
        assert r.status_code == 404
    finally:
        _cleanup()


# ---------------------------------------------------------------------------
# POST /api/users/{id}/test-email
# ---------------------------------------------------------------------------


def test_test_email_sends_and_returns_200():
    """Email de test envoyé avec succès → 200 avec {"status": "sent", "recipient": ...}."""
    user = _make_user(notification_email="alice@example.com")
    settings = _make_settings()

    db = MagicMock()
    # Premier appel filter().first() → user ; deuxième .first() → settings
    db.query.return_value.filter.return_value.first.return_value = user
    db.query.return_value.first.return_value = settings

    mock_smtp = AsyncMock()
    client = _client_with_db(db)
    try:
        with patch("app.routers.users_api.smtp_send", mock_smtp):
            r = client.post("/api/users/1/test-email")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "sent"
        assert data["recipient"] == "alice@example.com"
        mock_smtp.assert_called_once()
    finally:
        _cleanup()


def test_test_email_404_when_user_not_found():
    """Utilisateur introuvable → 404."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    client = _client_with_db(db)
    try:
        r = client.post("/api/users/999/test-email")
        assert r.status_code == 404
    finally:
        _cleanup()


def test_test_email_400_when_no_email():
    """Utilisateur sans email (ni notif ni plex) → 400."""
    user = _make_user(notification_email=None, plex_email=None)
    settings = _make_settings()

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = user
    db.query.return_value.first.return_value = settings

    client = _client_with_db(db)
    try:
        r = client.post("/api/users/1/test-email")
        assert r.status_code == 400
    finally:
        _cleanup()


def test_test_email_uses_plex_email_as_fallback():
    """Si notification_email est None, utilise plex_email."""
    user = _make_user(notification_email=None, plex_email="plex@example.com")
    settings = _make_settings()

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = user
    db.query.return_value.first.return_value = settings

    mock_smtp = AsyncMock()
    client = _client_with_db(db)
    try:
        with patch("app.routers.users_api.smtp_send", mock_smtp):
            r = client.post("/api/users/1/test-email")
        assert r.status_code == 200
        assert r.json()["recipient"] == "plex@example.com"
    finally:
        _cleanup()


# ---------------------------------------------------------------------------
# GET /api/email/preview
# ---------------------------------------------------------------------------


def test_preview_request_returns_html():
    """Preview event=request → 200 avec Content-Type text/html."""
    db = MagicMock()
    db.query.return_value.first.return_value = _make_settings()

    client = _client_with_db(db)
    try:
        r = client.get("/api/email/preview?event=request")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        # Le HTML doit contenir le titre fictif
        assert "Dune" in r.text
        assert "Logiciel créé par" in r.text
        assert "DEHER Rémi" in r.text
    finally:
        _cleanup()


def test_preview_available_returns_html():
    """Preview event=available → 200 avec HTML."""
    db = MagicMock()
    db.query.return_value.first.return_value = _make_settings()

    client = _client_with_db(db)
    try:
        r = client.get("/api/email/preview?event=available")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
    finally:
        _cleanup()


def test_preview_works_without_settings():
    """Preview sans settings en DB → utilise le template par défaut."""
    db = MagicMock()
    db.query.return_value.first.return_value = None

    client = _client_with_db(db)
    try:
        r = client.get("/api/email/preview?event=request")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
    finally:
        _cleanup()


def test_preview_defaults_to_request_event():
    """Sans paramètre event, preview retourne le template request."""
    db = MagicMock()
    db.query.return_value.first.return_value = _make_settings()

    client = _client_with_db(db)
    try:
        r = client.get("/api/email/preview")
        assert r.status_code == 200
    finally:
        _cleanup()


def test_preview_uses_custom_template():
    """Si settings a un template custom, il est utilisé dans la preview."""
    settings = _make_settings()
    settings.email_request_template = "CUSTOM_TEMPLATE_{{title}}"

    db = MagicMock()
    db.query.return_value.first.return_value = settings

    client = _client_with_db(db)
    try:
        r = client.get("/api/email/preview?event=request")
        assert r.status_code == 200
        assert "CUSTOM_TEMPLATE_" in r.text
        assert "DEHER Rémi" in r.text
    finally:
        _cleanup()


def test_preview_uses_custom_subject_and_user():
    """Preview utilise l'objet custom et les informations de l'utilisateur spécifié."""
    settings = _make_settings()
    settings.email_request_subject = "Alerte pour {{ plex_user }} - {{ title }}"

    user = _make_user(user_id=12, custom_name="Bob L'Eponge", notification_email="bob@bikini.bottom")

    db = MagicMock()
    # First query for settings, second query for user
    db.query.return_value.first.return_value = settings
    db.query.return_value.filter.return_value.first.return_value = user

    client = _client_with_db(db)
    try:
        r = client.get("/api/email/preview?event=request&user_id=12")
        assert r.status_code == 200
        assert "Alerte pour Bob L'Eponge - Dune" in r.text
        assert "bob@bikini.bottom" in r.text
    finally:
        _cleanup()
