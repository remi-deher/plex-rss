"""Tests unitaires pour les endpoints de notification :
GET  /api/notifications/log
POST /api/notifications/{id}/resend
POST /api/users/{id}/test-email
GET  /api/email/preview
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_db_async as get_db
from app.dependencies import require_admin, require_auth
from app.main import app
from app.models import DiagnosticEvent, MediaRequest, NotificationLog, PlexUser, Settings
from tests.async_support import AsyncSessionContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client_with_db(db):
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, raise_server_exceptions=False)


def _cleanup():
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(require_admin, None)
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

    return NotificationLog(
        id=log_id,
        event=event,
        recipient=recipient,
        is_admin=is_admin,
        media_title=media_title,
        media_type=media_type,
        success=success,
        error_msg=error_msg,
        req_id=req_id,
        sent_at=sent_at or datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
    )


def _make_user(
    user_id=1, notification_email="user@example.com", plex_email=None, display_name="Alice", custom_name=None
):
    return PlexUser(
        id=user_id,
        plex_user_id=f"user-{user_id}",
        notification_email=notification_email,
        plex_email=plex_email,
        display_name=display_name,
        custom_name=custom_name,
    )


def _make_settings():
    return Settings(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="user@example.com",
        smtp_password="pass",
        smtp_from="noreply@example.com",
        smtp_tls=True,
    )


def _make_req(req_id=42, title="Inception", media_type="movie"):
    return MediaRequest(id=req_id, plex_user_id="alice", title=title, media_type=media_type, status="pending")


def test_notification_hold_is_persisted_and_survives_local_state_reset(async_db, monkeypatch):
    """La suspension reste active apres un redemarrage, meme sans Redis."""
    import app.database
    import app.job_queue as job_queue

    settings = _make_settings()
    async_db.add(settings)
    async_db.commit()
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr(job_queue, "_local_notification_hold", False)

    asyncio.run(job_queue.set_notification_hold(True, db=async_db))
    async_db.commit()
    assert settings.notification_hold_enabled is True

    # Simule un nouveau processus : l'etat memoire est perdu.
    monkeypatch.setattr(job_queue, "_local_notification_hold", False)
    monkeypatch.setattr(app.database, "AsyncSessionLocal", lambda: AsyncSessionContext(async_db))
    assert asyncio.run(job_queue.notification_hold_enabled()) is True


def test_diagnostic_logs_are_filterable(async_db):
    async_db.add(DiagnosticEvent(
        request_id=42,
        correlation_id="request:42",
        category="plex",
        action="matched",
        status="success",
        title="Berceuse Mortelle",
        media_type="movie",
        source="manual_search",
        message="Média Plex trouvé par tmdb.",
        details='{"plex_guid":"plex://movie/test"}',
    ))
    async_db.commit()
    client = _client_with_db(async_db)
    try:
        response = client.get("/api/diagnostic-logs?category=plex&search=Berceuse")
        assert response.status_code == 200
        assert response.json()["items"][0]["action"] == "matched"
        assert response.json()["items"][0]["details"]["plex_guid"] == "plex://movie/test"
    finally:
        _cleanup()


# ---------------------------------------------------------------------------
# GET /api/notifications/log
# ---------------------------------------------------------------------------


def test_list_logs_returns_paginated_structure(async_db):
    """La réponse contient total, offset, limit, items."""
    log = _make_log()
    async_db.add(log)
    async_db.commit()
    client = _client_with_db(async_db)
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


def test_list_logs_item_fields(async_db):
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
    async_db.add(log)
    async_db.commit()
    client = _client_with_db(async_db)
    try:
        r = client.get("/api/notifications/log")
        item = r.json()["items"][0]
        assert item["id"] == 7
        assert item["event"] == "available"
        assert item["event_label"].startswith("Disponibilit")
        assert item["event_group"] == "Disponibilité"
        assert item["event_badge_class"] == "bg-success"
        assert item["status_label"] == "Erreur"
        assert item["recipient"] == "admin@b.com"
        assert item["is_admin"] is True
        assert item["media_title"] == "Dune"
        assert item["success"] is False
        assert item["error_msg"] == "SMTP down"
        assert item["req_id"] == 10
    finally:
        _cleanup()


def test_list_logs_pagination_offset(async_db):
    """Le paramètre offset est transmis à la query."""
    async_db.add_all([_make_log(log_id=i, recipient=f"u{i}@example.com") for i in range(1, 31)])
    async_db.commit()
    client = _client_with_db(async_db)
    try:
        r = client.get("/api/notifications/log?offset=20&limit=10")
        assert r.status_code == 200
        data = r.json()
        assert data["offset"] == 20
        assert data["limit"] == 10
        assert len(data["items"]) == 10
    finally:
        _cleanup()


def test_list_logs_limit_capped_at_200(async_db):
    """Le limit est plafonné à 200 même si le client demande plus."""
    client = _client_with_db(async_db)
    try:
        response = client.get("/api/notifications/log?limit=999")
        assert response.json()["limit"] == 200
    finally:
        _cleanup()


def test_list_logs_empty(async_db):
    """Aucun log → items=[], total=0."""
    client = _client_with_db(async_db)
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


def test_resend_queues_notification(async_db):
    """Resend valide → statut 200 + queued."""
    log = _make_log(log_id=1, req_id=42, event="request", recipient="u@b.com")
    req = _make_req(req_id=42)

    async_db.add_all([req, log])
    async_db.commit()
    mock_enqueue = AsyncMock()
    client = _client_with_db(async_db)
    try:
        with patch("app.routers.notifications_api.enqueue_notification", mock_enqueue):
            r = client.post("/api/notifications/1/resend")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "queued"
        assert data["recipient"] == "u@b.com"
        assert data["event"] == "request"
        mock_enqueue.assert_called_once_with("request", 42, ["u@b.com"], None)
    finally:
        _cleanup()


def test_resend_404_when_log_not_found(async_db):
    """Log introuvable → 404."""
    client = _client_with_db(async_db)
    try:
        r = client.post("/api/notifications/999/resend")
        assert r.status_code == 404
    finally:
        _cleanup()


def test_resend_400_when_no_req_id(async_db):
    """Log sans req_id (ancien format) → 400."""
    log = _make_log(log_id=1, req_id=None)

    async_db.add(log)
    async_db.commit()
    client = _client_with_db(async_db)
    try:
        r = client.post("/api/notifications/1/resend")
        assert r.status_code == 400
    finally:
        _cleanup()


def test_resend_404_when_original_request_not_found(async_db):
    """Log avec req_id, mais MediaRequest supprimée → 404."""
    log = _make_log(log_id=1, req_id=42)

    async_db.add(log)
    async_db.commit()
    client = _client_with_db(async_db)
    try:
        r = client.post("/api/notifications/1/resend")
        assert r.status_code == 404
    finally:
        _cleanup()


# ---------------------------------------------------------------------------
# POST /api/users/{id}/test-email
# ---------------------------------------------------------------------------


def test_test_email_sends_and_returns_200(async_db):
    """Email de test envoyé avec succès → 200 avec {"status": "sent", "recipient": ...}."""
    user = _make_user(notification_email="alice@example.com")
    settings = _make_settings()

    async_db.add_all([user, settings])
    async_db.commit()
    mock_smtp = AsyncMock()
    client = _client_with_db(async_db)
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


def test_test_email_404_when_user_not_found(async_db):
    """Utilisateur introuvable → 404."""
    client = _client_with_db(async_db)
    try:
        r = client.post("/api/users/999/test-email")
        assert r.status_code == 404
    finally:
        _cleanup()


def test_test_email_400_when_no_email(async_db):
    """Utilisateur sans email (ni notif ni plex) → 400."""
    user = _make_user(notification_email=None, plex_email=None)
    settings = _make_settings()

    async_db.add_all([user, settings])
    async_db.commit()
    client = _client_with_db(async_db)
    try:
        r = client.post("/api/users/1/test-email")
        assert r.status_code == 400
    finally:
        _cleanup()


def test_test_email_uses_plex_email_as_fallback(async_db):
    """Si notification_email est None, utilise plex_email."""
    user = _make_user(notification_email=None, plex_email="plex@example.com")
    settings = _make_settings()

    async_db.add_all([user, settings])
    async_db.commit()
    mock_smtp = AsyncMock()
    client = _client_with_db(async_db)
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


def test_preview_request_returns_html(async_db):
    """Preview event=request → 200 avec Content-Type text/html."""
    async_db.add(_make_settings())
    async_db.commit()
    client = _client_with_db(async_db)
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


def test_preview_available_returns_html(async_db):
    """Preview event=available → 200 avec HTML."""
    async_db.add(_make_settings())
    async_db.commit()
    client = _client_with_db(async_db)
    try:
        r = client.get("/api/email/preview?event=available")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
    finally:
        _cleanup()


def test_preview_works_without_settings(async_db):
    """Preview sans settings en DB → utilise le template par défaut."""
    client = _client_with_db(async_db)
    try:
        r = client.get("/api/email/preview?event=request")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
    finally:
        _cleanup()


def test_preview_defaults_to_request_event(async_db):
    """Sans paramètre event, preview retourne le template request."""
    async_db.add(_make_settings())
    async_db.commit()
    client = _client_with_db(async_db)
    try:
        r = client.get("/api/email/preview")
        assert r.status_code == 200
    finally:
        _cleanup()


def test_preview_uses_custom_template(async_db):
    """Si settings a un template custom, il est utilisé dans la preview."""
    settings = _make_settings()
    settings.email_request_template = "CUSTOM_TEMPLATE_{titre}"

    async_db.add(settings)
    async_db.commit()
    client = _client_with_db(async_db)
    try:
        r = client.get("/api/email/preview?event=request")
        assert r.status_code == 200
        assert "CUSTOM_TEMPLATE_" in r.text
        assert "DEHER Rémi" in r.text
    finally:
        _cleanup()


def test_preview_uses_custom_subject_and_user(async_db):
    """Preview utilise l'objet custom et les informations de l'utilisateur spécifié."""
    settings = _make_settings()
    settings.email_request_subject = "Alerte pour {nom_utilisateur} - {titre}"

    user = _make_user(user_id=12, custom_name="Bob L'Eponge", notification_email="bob@bikini.bottom")

    async_db.add_all([settings, user])
    async_db.commit()
    client = _client_with_db(async_db)
    try:
        r = client.get("/api/email/preview?event=request&user_id=12")
        assert r.status_code == 200
        assert "Alerte pour Bob L'Eponge - Dune" in r.text
        assert "bob@bikini.bottom" in r.text
    finally:
        _cleanup()
