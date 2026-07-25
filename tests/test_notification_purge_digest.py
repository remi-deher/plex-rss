"""Async database tests for notification retention and the daily digest."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.models import (
    AdminActionLog,
    DiagnosticEvent,
    JobRunLog,
    LoginAttempt,
    MediaRequest,
    NotificationLog,
    PlexUser,
    Settings,
)
from app.scheduler import _purge_notification_logs, _send_digest
from tests.async_support import make_test_session


def _settings(**kwargs):
    defaults = {
        "digest_enabled": True,
        "email_enabled": True,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_user": "user@example.com",
        "smtp_password": "password",
        "smtp_from": "noreply@example.com",
        "smtp_tls": True,
    }
    defaults.update(kwargs)
    return Settings(**defaults)


def _request(**kwargs):
    defaults = {
        "plex_user_id": "alice",
        "plex_user": "Alice",
        "title": "Inception",
        "media_type": "movie",
        "status": "available",
        "requested_at": datetime.now(),
    }
    defaults.update(kwargs)
    return MediaRequest(**defaults)


@pytest.mark.asyncio
async def test_purge_skips_without_settings():
    db = make_test_session()
    with patch("app.services.notification_orchestrator.AsyncSessionLocal", return_value=db):
        await _purge_notification_logs()
    assert db.query(NotificationLog).count() == 0


@pytest.mark.asyncio
async def test_purge_skips_when_retention_is_disabled():
    db = make_test_session()
    db.add(_settings(notification_log_retention_days=None, poll_history_retention_days=None))
    db.add(NotificationLog(event="request", recipient="a@example.com", sent_at=datetime.now() - timedelta(days=90)))
    db.commit()
    with patch("app.services.notification_orchestrator.AsyncSessionLocal", return_value=db):
        await _purge_notification_logs()
    assert db.query(NotificationLog).count() == 1


@pytest.mark.asyncio
async def test_purge_deletes_only_expired_logs():
    db = make_test_session()
    db.add(_settings(notification_log_retention_days=30, poll_history_retention_days=None))
    db.add_all(
        [
            NotificationLog(event="request", recipient="old@example.com", sent_at=datetime.now() - timedelta(days=31)),
            NotificationLog(event="request", recipient="new@example.com", sent_at=datetime.now() - timedelta(days=2)),
        ]
    )
    db.commit()
    with patch("app.services.notification_orchestrator.AsyncSessionLocal", return_value=db):
        await _purge_notification_logs()
    assert [row.recipient for row in db.query(NotificationLog).all()] == ["new@example.com"]


@pytest.mark.asyncio
async def test_purge_deletes_expired_login_attempts():
    db = make_test_session()
    db.add(_settings(notification_log_retention_days=None, poll_history_retention_days=None, login_attempt_retention_days=90))
    db.add_all(
        [
            LoginAttempt(ip_address="1.2.3.4", attempted_at=datetime.now() - timedelta(days=91)),
            LoginAttempt(ip_address="5.6.7.8", attempted_at=datetime.now() - timedelta(days=2)),
        ]
    )
    db.commit()
    with patch("app.services.notification_orchestrator.AsyncSessionLocal", return_value=db):
        await _purge_notification_logs()
    assert [row.ip_address for row in db.query(LoginAttempt).all()] == ["5.6.7.8"]


@pytest.mark.asyncio
async def test_purge_keeps_login_attempts_when_retention_disabled():
    db = make_test_session()
    db.add(_settings(notification_log_retention_days=None, poll_history_retention_days=None))
    db.add(LoginAttempt(ip_address="1.2.3.4", attempted_at=datetime.now() - timedelta(days=400)))
    db.commit()
    # La retention IP a un default colonne 90 (applique a l'INSERT) ; on la desactive
    # explicitement via UPDATE (chemin reel = champ vide dans l'UI -> null) avant purge.
    db.query(Settings).first().login_attempt_retention_days = None
    db.commit()
    with patch("app.services.notification_orchestrator.AsyncSessionLocal", return_value=db):
        await _purge_notification_logs()
    assert db.query(LoginAttempt).count() == 1


@pytest.mark.asyncio
async def test_purge_deletes_expired_audit_logs():
    db = make_test_session()
    db.add(_settings(notification_log_retention_days=None, poll_history_retention_days=None, login_attempt_retention_days=None, audit_log_retention_days=30))
    old, recent = datetime.now() - timedelta(days=31), datetime.now() - timedelta(days=2)
    db.add_all(
        [
            AdminActionLog(action="delete", summary="old", created_at=old),
            AdminActionLog(action="delete", summary="recent", created_at=recent),
            DiagnosticEvent(category="arr", action="submit", created_at=old),
            JobRunLog(job="watchlist", started_at=old, status="complete"),
            JobRunLog(job="watchlist", started_at=recent, status="complete"),
        ]
    )
    db.commit()
    with patch("app.services.notification_orchestrator.AsyncSessionLocal", return_value=db):
        await _purge_notification_logs()
    assert [row.summary for row in db.query(AdminActionLog).all()] == ["recent"]
    assert db.query(DiagnosticEvent).count() == 0
    assert db.query(JobRunLog).count() == 1


@pytest.mark.asyncio
async def test_purge_keeps_audit_logs_when_retention_disabled():
    db = make_test_session()
    db.add(_settings(notification_log_retention_days=None, poll_history_retention_days=None, login_attempt_retention_days=None, audit_log_retention_days=None))
    db.add(AdminActionLog(action="delete", summary="kept", created_at=datetime.now() - timedelta(days=400)))
    db.commit()
    with patch("app.services.notification_orchestrator.AsyncSessionLocal", return_value=db):
        await _purge_notification_logs()
    assert db.query(AdminActionLog).count() == 1


@pytest.mark.asyncio
async def test_digest_skips_without_settings():
    db = make_test_session()
    send = AsyncMock()
    with (
        patch("app.services.notification_orchestrator.AsyncSessionLocal", return_value=db),
        patch("app.services.email_service._send", send),
    ):
        await _send_digest()
    send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "settings",
    [
        _settings(digest_enabled=False),
        _settings(email_enabled=False),
        _settings(smtp_host=None),
    ],
)
async def test_digest_skips_when_disabled_or_smtp_incomplete(settings):
    db = make_test_session()
    db.add(settings)
    db.add(_request())
    db.commit()
    send = AsyncMock()
    with (
        patch("app.services.notification_orchestrator.AsyncSessionLocal", return_value=db),
        patch("app.services.email_service._send", send),
    ):
        await _send_digest()
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_digest_skips_without_recent_requests():
    db = make_test_session()
    db.add(_settings())
    db.add(_request(requested_at=datetime.now() - timedelta(days=2)))
    db.add(PlexUser(plex_user_id="alice", enabled=True, notify_digest=True, notification_email="a@example.com"))
    db.commit()
    send = AsyncMock()
    with (
        patch("app.services.notification_orchestrator.AsyncSessionLocal", return_value=db),
        patch("app.services.email_service._send", send),
    ):
        await _send_digest()
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_digest_sends_to_subscribers_and_uses_plex_email_fallback():
    db = make_test_session()
    db.add(_settings())
    db.add(_request(title="Breaking Bad"))
    db.add_all(
        [
            PlexUser(plex_user_id="alice", enabled=True, notify_digest=True, notification_email="a@example.com"),
            PlexUser(plex_user_id="bob", enabled=True, notify_digest=True, plex_email="b@example.com"),
            PlexUser(plex_user_id="charlie", enabled=True, notify_digest=True),
            PlexUser(plex_user_id="disabled", enabled=False, notify_digest=True, notification_email="d@example.com"),
        ]
    )
    db.commit()
    send = AsyncMock()
    with (
        patch("app.services.notification_orchestrator.AsyncSessionLocal", return_value=db),
        patch("app.services.email_service._send", send),
    ):
        await _send_digest()
    assert [call.args[1] for call in send.await_args_list] == ["a@example.com", "b@example.com"]
    assert all("Breaking Bad" in call.args[3] for call in send.await_args_list)


@pytest.mark.asyncio
async def test_digest_continues_after_smtp_failure():
    db = make_test_session()
    db.add(_settings())
    db.add(_request())
    db.add_all(
        [
            PlexUser(plex_user_id="alice", enabled=True, notify_digest=True, notification_email="fail@example.com"),
            PlexUser(plex_user_id="bob", enabled=True, notify_digest=True, notification_email="ok@example.com"),
        ]
    )
    db.commit()
    send = AsyncMock(side_effect=[RuntimeError("SMTP refused"), None])
    with (
        patch("app.services.notification_orchestrator.AsyncSessionLocal", return_value=db),
        patch("app.services.email_service._send", send),
    ):
        await _send_digest()
    assert send.await_count == 2
