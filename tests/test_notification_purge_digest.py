"""Tests unitaires pour _purge_notification_logs et _send_digest dans scheduler.py."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.scheduler import _purge_notification_logs, _send_digest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**kwargs):
    s = MagicMock()
    # Valeurs par défaut SMTP
    s.digest_enabled = kwargs.get("digest_enabled", True)
    s.digest_hour = kwargs.get("digest_hour", 8)
    s.smtp_host = kwargs.get("smtp_host", "smtp.example.com")
    s.smtp_port = kwargs.get("smtp_port", 587)
    s.smtp_user = kwargs.get("smtp_user", "user@example.com")
    s.smtp_password = kwargs.get("smtp_password", "password")
    s.smtp_from = kwargs.get("smtp_from", "noreply@example.com")
    s.smtp_tls = kwargs.get("smtp_tls", True)
    s.notification_log_retention_days = kwargs.get("notification_log_retention_days", None)
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


def _make_user(notification_email="user@example.com", plex_email=None, notify_digest=True, enabled=True):
    u = MagicMock()
    u.notification_email = notification_email
    u.plex_email = plex_email
    u.notify_digest = notify_digest
    u.enabled = enabled
    return u


def _make_req(
    title="Inception", media_type="movie", status="available", requested_at=None, year=2010, plex_user="alice"
):
    r = MagicMock()
    r.title = title
    r.media_type = media_type
    r.status = status
    r.requested_at = requested_at or datetime.now()
    r.year = year
    r.plex_user = plex_user
    r.plex_user_id = "alice"
    return r


# ---------------------------------------------------------------------------
# _purge_notification_logs
# ---------------------------------------------------------------------------


def test_purge_skips_when_no_settings():
    """Si settings est None, aucune suppression."""
    db = MagicMock()
    db.query.return_value.first.return_value = None

    with patch("app.services.notification_orchestrator.SessionLocal", return_value=db):
        _purge_notification_logs()

    db.query.return_value.filter.return_value.delete.assert_not_called()
    db.commit.assert_not_called()


def test_purge_skips_when_retention_is_none():
    """Si notification_log_retention_days est None → aucune purge."""
    db = MagicMock()
    db.query.return_value.first.return_value = _make_settings(notification_log_retention_days=None)

    with patch("app.services.notification_orchestrator.SessionLocal", return_value=db):
        _purge_notification_logs()

    db.commit.assert_not_called()


def test_purge_skips_when_retention_is_zero():
    """Valeur 0 traitée comme aucune rétention → skip."""
    db = MagicMock()
    db.query.return_value.first.return_value = _make_settings(notification_log_retention_days=0)

    with patch("app.services.notification_orchestrator.SessionLocal", return_value=db):
        _purge_notification_logs()

    db.commit.assert_not_called()


def test_purge_deletes_old_logs_and_commits():
    """Rétention 30j → delete + commit."""
    db = MagicMock()
    db.query.return_value.first.return_value = _make_settings(notification_log_retention_days=30)
    db.query.return_value.filter.return_value.delete.return_value = 5

    with patch("app.services.notification_orchestrator.SessionLocal", return_value=db):
        _purge_notification_logs()

    db.query.return_value.filter.return_value.delete.assert_called_once()
    db.commit.assert_called_once()


def test_purge_no_commit_when_nothing_deleted():
    """Si delete retourne 0 → pas de commit inutile."""
    db = MagicMock()
    db.query.return_value.first.return_value = _make_settings(notification_log_retention_days=30)
    db.query.return_value.filter.return_value.delete.return_value = 0

    with patch("app.services.notification_orchestrator.SessionLocal", return_value=db):
        _purge_notification_logs()

    db.commit.assert_not_called()


def test_purge_always_closes_db():
    """La session DB est toujours fermée, même en cas d'exception."""
    db = MagicMock()
    db.query.side_effect = Exception("DB error")

    with patch("app.services.notification_orchestrator.SessionLocal", return_value=db):
        _purge_notification_logs()  # ne doit pas lever

    db.close.assert_called_once()


# ---------------------------------------------------------------------------
# _send_digest — cas d'arrêt rapide
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_digest_skips_when_no_settings():
    """Digest skip si settings introuvable."""
    db = MagicMock()
    db.query.return_value.first.return_value = None

    with patch("app.services.notification_orchestrator.SessionLocal", return_value=db):
        await _send_digest()

    # aiosmtplib.send ne doit pas être appelé
    # On vérifie qu'aucun envoi n'a eu lieu en s'assurant que db.close est appelé
    db.close.assert_called_once()


@pytest.mark.asyncio
async def test_digest_skips_when_digest_disabled():
    """Digest skip si digest_enabled=False."""
    db = MagicMock()
    db.query.return_value.first.return_value = _make_settings(digest_enabled=False)

    with (
        patch("app.services.notification_orchestrator.SessionLocal", return_value=db),
        patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send,
    ):
        await _send_digest()

    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_digest_skips_when_smtp_incomplete():
    """Digest skip si SMTP non complet (smtp_host manquant)."""
    db = MagicMock()
    db.query.return_value.first.return_value = _make_settings(smtp_host=None)

    with (
        patch("app.services.notification_orchestrator.SessionLocal", return_value=db),
        patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send,
    ):
        await _send_digest()

    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_digest_skips_when_no_recent_requests():
    """Digest skip si aucune demande dans les 24h."""
    db = MagicMock()
    settings = _make_settings()
    db.query.return_value.first.return_value = settings
    # La requête MediaRequest retourne une liste vide
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

    with (
        patch("app.services.notification_orchestrator.SessionLocal", return_value=db),
        patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send,
    ):
        await _send_digest()

    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_digest_skips_when_no_subscribers():
    """Digest skip si aucun utilisateur a notify_digest=True."""
    db = MagicMock()
    settings = _make_settings()
    recent_req = _make_req()

    # Premier filter() retourne les demandes récentes
    # Deuxième filter() retourne les abonnés digest → liste vide
    call_count = 0

    def mock_filter(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        m = MagicMock()
        if call_count == 1:
            m.order_by.return_value.all.return_value = [recent_req]
        else:
            m.all.return_value = []
        return m

    db.query.return_value.first.return_value = settings
    db.query.return_value.filter.side_effect = mock_filter

    with (
        patch("app.services.notification_orchestrator.SessionLocal", return_value=db),
        patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send,
    ):
        await _send_digest()

    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_digest_sends_to_subscribers():
    """Digest envoyé aux utilisateurs notify_digest=True ayant un email."""
    db = MagicMock()
    settings = _make_settings()
    user1 = _make_user(notification_email="sub1@example.com")
    user2 = _make_user(notification_email="sub2@example.com")
    recent_req = _make_req(title="Breaking Bad")

    call_count = 0

    def mock_filter(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        m = MagicMock()
        if call_count == 1:
            m.order_by.return_value.all.return_value = [recent_req]
        else:
            m.all.return_value = [user1, user2]
        return m

    db.query.return_value.first.return_value = settings
    db.query.return_value.filter.side_effect = mock_filter

    with (
        patch("app.services.notification_orchestrator.SessionLocal", return_value=db),
        patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send,
    ):
        await _send_digest()

    assert mock_send.call_count == 2


@pytest.mark.asyncio
async def test_digest_skips_user_without_email():
    """Un utilisateur sans notification_email ni plex_email est ignoré."""
    db = MagicMock()
    settings = _make_settings()
    user_no_email = _make_user(notification_email=None, plex_email=None)
    recent_req = _make_req()

    call_count = 0

    def mock_filter(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        m = MagicMock()
        if call_count == 1:
            m.order_by.return_value.all.return_value = [recent_req]
        else:
            m.all.return_value = [user_no_email]
        return m

    db.query.return_value.first.return_value = settings
    db.query.return_value.filter.side_effect = mock_filter

    with (
        patch("app.services.notification_orchestrator.SessionLocal", return_value=db),
        patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send,
    ):
        await _send_digest()

    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_digest_falls_back_to_plex_email():
    """Si notification_email est None mais plex_email existe → utilise plex_email."""
    db = MagicMock()
    settings = _make_settings()
    user = _make_user(notification_email=None, plex_email="plex@example.com")
    recent_req = _make_req()

    call_count = 0

    def mock_filter(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        m = MagicMock()
        if call_count == 1:
            m.order_by.return_value.all.return_value = [recent_req]
        else:
            m.all.return_value = [user]
        return m

    db.query.return_value.first.return_value = settings
    db.query.return_value.filter.side_effect = mock_filter

    with (
        patch("app.services.notification_orchestrator.SessionLocal", return_value=db),
        patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send,
    ):
        await _send_digest()

    mock_send.assert_called_once()
    # Vérifier que le destinataire est bien plex@example.com
    call_kwargs = mock_send.call_args
    msg_arg = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("message")
    assert msg_arg["To"] == "plex@example.com"


@pytest.mark.asyncio
async def test_digest_smtp_failure_continues_other_users():
    """Si un envoi échoue, le digest continue pour les autres utilisateurs."""
    db = MagicMock()
    settings = _make_settings()
    user1 = _make_user(notification_email="fail@example.com")
    user2 = _make_user(notification_email="ok@example.com")
    recent_req = _make_req()

    call_count = 0

    def mock_filter(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        m = MagicMock()
        if call_count == 1:
            m.order_by.return_value.all.return_value = [recent_req]
        else:
            m.all.return_value = [user1, user2]
        return m

    db.query.return_value.first.return_value = settings
    db.query.return_value.filter.side_effect = mock_filter

    send_count = 0

    async def flaky_send(*args, **kwargs):
        nonlocal send_count
        send_count += 1
        if send_count == 1:
            raise Exception("SMTP refused")

    with (
        patch("app.services.notification_orchestrator.SessionLocal", return_value=db),
        patch("aiosmtplib.send", side_effect=flaky_send),
    ):
        await _send_digest()  # ne doit pas lever

    assert send_count == 2  # tentative pour les 2 utilisateurs


@pytest.mark.asyncio
async def test_digest_always_closes_db():
    """La session DB est toujours fermée, même en cas d'erreur inattendue."""
    db = MagicMock()
    db.query.side_effect = Exception("DB error")

    with patch("app.services.notification_orchestrator.SessionLocal", return_value=db):
        await _send_digest()  # ne doit pas lever

    db.close.assert_called_once()
