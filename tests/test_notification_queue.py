"""Tests unitaires pour app/notification_queue.py — logique _process."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.notification_queue import _process


def _make_settings(**kwargs):
    s = MagicMock()
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


def _make_req(req_id=1, title="Inception", request_mail_sent=False, available_mail_sent=False):
    r = MagicMock()
    r.id = req_id
    r.title = title
    r.request_mail_sent = request_mail_sent
    r.available_mail_sent = available_mail_sent
    return r


def _make_db(settings=None, req=None):
    db = MagicMock()
    db.query.return_value.first.side_effect = [settings, req]
    db.query.return_value.filter.return_value.first.return_value = req
    return db


# ---------------------------------------------------------------------------
# Cas : Settings ou Request introuvable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_no_settings_does_nothing():
    """Si Settings est absent, _process retourne sans erreur."""
    db = MagicMock()
    db.query.return_value.first.return_value = None

    with patch("app.notification_queue.SessionLocal", return_value=db):
        await _process("request", 1, ["a@b.com"], "")

    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_process_no_request_does_nothing():
    """Si MediaRequest est absent, _process retourne sans erreur."""
    db = MagicMock()
    db.query.return_value.first.side_effect = [_make_settings(), None]
    db.query.return_value.filter.return_value.first.return_value = None

    with patch("app.notification_queue.SessionLocal", return_value=db):
        await _process("request", 99, ["a@b.com"], "")

    db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Cas : tous les destinataires réussissent → flag posé
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_request_all_ok_sets_flag():
    """Tous les emails envoyés → request_mail_sent=True + commit."""
    settings = _make_settings()
    req = _make_req()
    db = _make_db(settings, req)

    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_request_notification", new_callable=AsyncMock) as mock_send,
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
    ):
        await _process("request", 1, ["a@b.com", "c@d.com"], "")

    assert mock_send.call_count == 2
    assert req.request_mail_sent is True
    db.commit.assert_called()


@pytest.mark.asyncio
async def test_process_available_all_ok_sets_flag():
    """event=available → available_mail_sent=True."""
    settings = _make_settings()
    req = _make_req()
    db = _make_db(settings, req)

    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_available_notification", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
    ):
        await _process("available", 1, ["a@b.com"], "")

    assert req.available_mail_sent is True
    db.commit.assert_called()


# ---------------------------------------------------------------------------
# Cas : un destinataire échoue → flag NON posé (bug corrigé)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_partial_failure_does_not_set_flag():
    """Si un destinataire échoue, all_ok=False → flag non posé → permettre retry."""
    settings = _make_settings()
    req = _make_req()
    db = _make_db(settings, req)

    call_count = 0

    async def send_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise Exception("SMTP timeout")

    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_request_notification", side_effect=send_side_effect),
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
    ):
        await _process("request", 1, ["a@b.com", "fail@b.com"], "")

    assert req.request_mail_sent is False
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_process_all_fail_does_not_set_flag():
    """Tous les destinataires échouent → flag non posé."""
    settings = _make_settings()
    req = _make_req()
    db = _make_db(settings, req)

    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_request_notification", side_effect=Exception("down")),
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
    ):
        await _process("request", 1, ["a@b.com"], "")

    assert req.request_mail_sent is False
    db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Cas : Discord / Telegram toujours appelés indépendamment de l'email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_discord_called_even_if_email_fails():
    """Discord est envoyé même si l'email échoue."""
    settings = _make_settings()
    req = _make_req()
    db = _make_db(settings, req)

    mock_discord = AsyncMock()

    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_request_notification", side_effect=Exception("down")),
        patch("app.notification_queue.send_discord", mock_discord),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
    ):
        await _process("request", 1, ["a@b.com"], "")

    mock_discord.assert_called_once()
