"""Tests unitaires pour app/notification_queue.py — logique _process, retry, logs, push."""

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from sqlalchemy import text

from app.notification_queue import _process, enqueue

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**kwargs):
    s = MagicMock()
    s.admin_notification_email = kwargs.get("admin_notification_email", None)
    s.telegram_bot_token = kwargs.get("telegram_bot_token", None)
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


def _make_req(req_id=1, title="Inception", media_type="movie", request_mail_sent=False, available_mail_sent=False):
    r = MagicMock()
    r.id = req_id
    r.title = title
    r.media_type = media_type
    r.plex_user_id = "alice"
    r.request_mail_sent = request_mail_sent
    r.available_mail_sent = available_mail_sent
    return r


def _make_user(discord_webhook_url=None, telegram_chat_id=None):
    u = MagicMock()
    u.discord_webhook_url = discord_webhook_url
    u.telegram_chat_id = telegram_chat_id
    return u


def _make_db(settings=None, req=None, user=None):
    """DB mock qui renvoie settings via .first() et req/user via .filter().first()."""
    db = MagicMock()
    db.query.return_value.first.side_effect = [settings, req]
    # Tous les appels filter().first() renvoient req en premier, puis user
    db.query.return_value.filter.return_value.first.side_effect = [req, user]
    return db


# ---------------------------------------------------------------------------
# Cas : Settings ou Request introuvable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_no_settings_does_nothing():
    """Si Settings est absent, _process retourne sans envoyer ni committer."""
    db = MagicMock()
    db.query.return_value.first.return_value = None

    with patch("app.notification_queue.SessionLocal", return_value=db):
        await _process("request", 1, ["a@b.com"], "")

    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_process_no_request_does_nothing():
    """Si MediaRequest est absent, _process retourne sans envoyer ni committer."""
    db = MagicMock()
    db.query.return_value.first.side_effect = [_make_settings(), None]
    db.query.return_value.filter.return_value.first.return_value = None

    with patch("app.notification_queue.SessionLocal", return_value=db):
        await _process("request", 99, ["a@b.com"], "")

    db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Cas : envoi réussi → flag posé + commit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_request_all_ok_sets_flag():
    """Tous les emails envoyés → request_mail_sent=True + commit."""
    settings = _make_settings()
    req = _make_req()
    db = _make_db(settings, req, user=None)

    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_request_notification", new_callable=AsyncMock) as mock_send,
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord_to_webhook", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram_to_chat", new_callable=AsyncMock),
    ):
        await _process("request", 1, ["a@b.com", "c@d.com"], "")

    assert mock_send.call_count == 2
    assert req.request_mail_sent is True
    db.commit.assert_called()


@pytest.mark.asyncio
async def test_process_passes_custom_name_as_display_name():
    """Le custom_name du PlexUser est transmis comme display_name à l'envoi d'email."""
    settings = _make_settings()
    req = _make_req()
    user = _make_user()
    user.custom_name = "Papa"
    db = _make_db(settings, req, user=user)

    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_request_notification", new_callable=AsyncMock) as mock_send,
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord_to_webhook", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram_to_chat", new_callable=AsyncMock),
    ):
        await _process("request", 1, ["a@b.com"], "")

    mock_send.assert_called_once_with(settings, req, "a@b.com", "Papa")


@pytest.mark.asyncio
async def test_process_available_all_ok_sets_flag():
    """event=available → available_mail_sent=True."""
    settings = _make_settings()
    req = _make_req()
    db = _make_db(settings, req, user=None)

    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_available_notification", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord_to_webhook", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram_to_chat", new_callable=AsyncMock),
    ):
        await _process("available", 1, ["a@b.com"], "")

    assert req.available_mail_sent is True
    db.commit.assert_called()


@pytest.mark.asyncio
async def test_process_empty_recipients_still_commits():
    """Aucun destinataire → pas d'email envoyé mais commit pour les logs."""
    settings = _make_settings()
    req = _make_req()
    db = _make_db(settings, req, user=None)

    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord_to_webhook", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram_to_chat", new_callable=AsyncMock),
    ):
        await _process("request", 1, [], "")

    # Aucun email envoyé, flag non posé mais commit appelé (pour les logs)
    assert req.request_mail_sent is True  # all_ok reste True sur boucle vide
    db.commit.assert_called()


# ---------------------------------------------------------------------------
# Cas : retry automatique
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_retry_succeeds_on_second_attempt():
    """Un échec SMTP → retry → succès au 2e essai → flag posé."""
    settings = _make_settings()
    req = _make_req()
    db = _make_db(settings, req, user=None)

    attempts = []

    async def flaky_send(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise Exception("SMTP temporaire")

    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_request_notification", side_effect=flaky_send),
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord_to_webhook", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram_to_chat", new_callable=AsyncMock),
        patch("app.notification_queue.asyncio.sleep", new_callable=AsyncMock),
    ):
        await _process("request", 1, ["a@b.com"], "")

    assert len(attempts) == 2  # 1 échec + 1 succès
    assert req.request_mail_sent is True


@pytest.mark.asyncio
async def test_process_all_retries_fail_flag_not_set():
    """Tous les retries échouent → all_ok=False → flag non posé."""
    settings = _make_settings()
    req = _make_req()
    db = _make_db(settings, req, user=None)

    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_request_notification", side_effect=Exception("SMTP down")),
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord_to_webhook", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram_to_chat", new_callable=AsyncMock),
        patch("app.notification_queue.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        await _process("request", 1, ["a@b.com"], "")

    # Les délais de retry ont bien été respectés
    assert mock_sleep.call_count == 2  # _RETRY_DELAYS = [2, 5]
    assert req.request_mail_sent is False
    db.commit.assert_called()  # commit quand même pour sauver les logs


@pytest.mark.asyncio
async def test_process_partial_failure_all_retries_flag_not_set():
    """Un destinataire échoue sur tous ses retries → all_ok=False → flag non posé."""
    settings = _make_settings()
    req = _make_req()
    db = _make_db(settings, req, user=None)

    success_calls = 0
    fail_calls = 0

    async def targeted_send(*args, **kwargs):
        recipient = args[2] if len(args) > 2 else kwargs.get("recipient", "")
        nonlocal success_calls, fail_calls
        if "fail" in str(recipient):
            fail_calls += 1
            raise Exception("SMTP timeout")
        success_calls += 1

    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_request_notification", side_effect=targeted_send),
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord_to_webhook", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram_to_chat", new_callable=AsyncMock),
        patch("app.notification_queue.asyncio.sleep", new_callable=AsyncMock),
    ):
        await _process("request", 1, ["ok@b.com", "fail@b.com"], "")

    assert success_calls == 1  # ok@b.com réussit du premier coup
    assert fail_calls == 3  # fail@b.com: 3 tentatives (1 + 2 retries)
    assert req.request_mail_sent is False


@pytest.mark.asyncio
async def test_process_retry_uses_correct_delays():
    """Les délais de retry sont bien 2s puis 5s."""
    from app.notification_queue import _RETRY_DELAYS

    settings = _make_settings()
    req = _make_req()
    db = _make_db(settings, req, user=None)
    sleep_calls = []

    async def record_sleep(delay):
        sleep_calls.append(delay)

    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_request_notification", side_effect=Exception("down")),
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord_to_webhook", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram_to_chat", new_callable=AsyncMock),
        patch("app.notification_queue.asyncio.sleep", side_effect=record_sleep),
    ):
        await _process("request", 1, ["a@b.com"], "")

    assert sleep_calls == _RETRY_DELAYS


# ---------------------------------------------------------------------------
# Cas : NotificationLog créé à chaque tentative finale
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_logs_success_entry():
    """Un envoi réussi → NotificationLog avec success=True ajouté à la DB."""
    settings = _make_settings()
    req = _make_req()
    db = _make_db(settings, req, user=None)
    added_logs = []
    db.add.side_effect = lambda obj: added_logs.append(obj)

    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_request_notification", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord_to_webhook", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram_to_chat", new_callable=AsyncMock),
    ):
        await _process("request", 1, ["a@b.com"], "")

    from app.models import NotificationLog

    logs = [o for o in added_logs if isinstance(o, NotificationLog)]
    assert len(logs) == 1
    assert logs[0].recipient == "a@b.com"
    assert logs[0].success is True
    assert logs[0].error_msg is None
    assert logs[0].req_id == 1
    assert logs[0].event == "request"


@pytest.mark.asyncio
async def test_process_logs_failure_entry_with_error_msg():
    """Un envoi en échec → NotificationLog avec success=False + error_msg."""
    settings = _make_settings()
    req = _make_req()
    db = _make_db(settings, req, user=None)
    added_logs = []
    db.add.side_effect = lambda obj: added_logs.append(obj)

    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_request_notification", side_effect=Exception("SMTP refused")),
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord_to_webhook", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram_to_chat", new_callable=AsyncMock),
        patch("app.notification_queue.asyncio.sleep", new_callable=AsyncMock),
    ):
        await _process("request", 1, ["a@b.com"], "")

    from app.models import NotificationLog

    logs = [o for o in added_logs if isinstance(o, NotificationLog)]
    assert len(logs) == 1
    assert logs[0].success is False
    assert "SMTP refused" in logs[0].error_msg


@pytest.mark.asyncio
async def test_process_logs_one_entry_per_recipient():
    """2 destinataires → 2 entrées de log distinctes."""
    settings = _make_settings()
    req = _make_req()
    db = _make_db(settings, req, user=None)
    added_logs = []
    db.add.side_effect = lambda obj: added_logs.append(obj)

    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_request_notification", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord_to_webhook", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram_to_chat", new_callable=AsyncMock),
    ):
        await _process("request", 1, ["a@b.com", "c@d.com"], "")

    from app.models import NotificationLog

    logs = [o for o in added_logs if isinstance(o, NotificationLog)]
    assert len(logs) == 2
    recipients = {log.recipient for log in logs}
    assert recipients == {"a@b.com", "c@d.com"}


@pytest.mark.asyncio
async def test_process_logs_is_admin_flag():
    """L'adresse admin est marquée is_admin=True dans le log."""
    settings = _make_settings(admin_notification_email="admin@example.com")
    req = _make_req()
    db = _make_db(settings, req, user=None)
    added_logs = []
    db.add.side_effect = lambda obj: added_logs.append(obj)

    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_request_notification", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord_to_webhook", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram_to_chat", new_callable=AsyncMock),
    ):
        await _process("request", 1, ["user@b.com", "admin@example.com"], "")

    from app.models import NotificationLog

    logs = {log.recipient: log for log in added_logs if isinstance(log, NotificationLog)}
    assert logs["admin@example.com"].is_admin is True
    assert logs["user@b.com"].is_admin is False


# ---------------------------------------------------------------------------
# Cas : push par utilisateur (Discord/Telegram individuels)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_per_user_discord_webhook_called():
    """Si l'utilisateur a un discord_webhook_url → send_discord_to_webhook appelé."""
    settings = _make_settings()
    req = _make_req()
    user = _make_user(discord_webhook_url="https://discord.com/api/webhooks/xxx")
    db = _make_db(settings, req, user=user)

    mock_discord_user = AsyncMock()
    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_request_notification", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord_to_webhook", mock_discord_user),
        patch("app.notification_queue.send_telegram_to_chat", new_callable=AsyncMock),
    ):
        await _process("request", 1, ["a@b.com"], "")

    mock_discord_user.assert_called_once_with("https://discord.com/api/webhooks/xxx", req, "request")


@pytest.mark.asyncio
async def test_process_per_user_telegram_called_with_global_token():
    """Si l'utilisateur a un telegram_chat_id → send_telegram_to_chat appelé avec le bot token global."""
    settings = _make_settings(telegram_bot_token="BOT:TOKEN123")
    req = _make_req()
    user = _make_user(telegram_chat_id="-100123456")
    db = _make_db(settings, req, user=user)

    mock_tg_user = AsyncMock()
    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_request_notification", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord_to_webhook", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram_to_chat", mock_tg_user),
    ):
        await _process("request", 1, ["a@b.com"], "")

    mock_tg_user.assert_called_once_with("BOT:TOKEN123", "-100123456", req, "request")


@pytest.mark.asyncio
async def test_process_no_per_user_push_when_no_webhook():
    """Si l'utilisateur n'a pas de webhook → send_discord_to_webhook et send_telegram_to_chat NON appelés."""
    settings = _make_settings()
    req = _make_req()
    user = _make_user(discord_webhook_url=None, telegram_chat_id=None)
    db = _make_db(settings, req, user=user)

    mock_discord_user = AsyncMock()
    mock_tg_user = AsyncMock()
    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_request_notification", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord_to_webhook", mock_discord_user),
        patch("app.notification_queue.send_telegram_to_chat", mock_tg_user),
    ):
        await _process("request", 1, ["a@b.com"], "")

    mock_discord_user.assert_not_called()
    mock_tg_user.assert_not_called()


@pytest.mark.asyncio
async def test_process_no_per_user_push_when_user_not_found():
    """Si le PlexUser est introuvable → push per-user silencieusement ignoré."""
    settings = _make_settings()
    req = _make_req()
    db = _make_db(settings, req, user=None)

    mock_discord_user = AsyncMock()
    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_request_notification", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord_to_webhook", mock_discord_user),
        patch("app.notification_queue.send_telegram_to_chat", new_callable=AsyncMock),
    ):
        await _process("request", 1, ["a@b.com"], "")

    mock_discord_user.assert_not_called()


@pytest.mark.asyncio
async def test_process_telegram_not_called_without_global_token():
    """Si settings.telegram_bot_token est vide → send_telegram_to_chat non appelé même avec chat_id."""
    settings = _make_settings(telegram_bot_token=None)
    req = _make_req()
    user = _make_user(telegram_chat_id="-100123")
    db = _make_db(settings, req, user=user)

    mock_tg_user = AsyncMock()
    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_request_notification", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord_to_webhook", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram_to_chat", mock_tg_user),
    ):
        await _process("request", 1, ["a@b.com"], "")

    mock_tg_user.assert_not_called()


# ---------------------------------------------------------------------------
# Cas : global push toujours appelé indépendamment de l'email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_discord_called_even_if_email_fails():
    """Discord global envoyé même si l'email échoue sur tous les retries."""
    settings = _make_settings()
    req = _make_req()
    db = _make_db(settings, req, user=None)

    mock_discord = AsyncMock()

    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_request_notification", side_effect=Exception("down")),
        patch("app.notification_queue.send_discord", mock_discord),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord_to_webhook", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram_to_chat", new_callable=AsyncMock),
        patch("app.notification_queue.asyncio.sleep", new_callable=AsyncMock),
    ):
        await _process("request", 1, ["a@b.com"], "")

    mock_discord.assert_called_once()


# ---------------------------------------------------------------------------
# Cas : event == "failed"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_failed_event_calls_failure_notification():
    """event=failed → send_failure_notification appelé avec la raison."""
    settings = _make_settings()
    req = _make_req()
    db = _make_db(settings, req, user=None)

    mock_failure = AsyncMock()
    with (
        patch("app.notification_queue.SessionLocal", return_value=db),
        patch("app.notification_queue.send_failure_notification", mock_failure),
        patch("app.notification_queue.send_discord", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram", new_callable=AsyncMock),
        patch("app.notification_queue.send_discord_to_webhook", new_callable=AsyncMock),
        patch("app.notification_queue.send_telegram_to_chat", new_callable=AsyncMock),
    ):
        await _process("failed", 1, ["a@b.com"], "Sonarr unreachable")

    mock_failure.assert_called_once()
    # La raison est transmise
    call_args = mock_failure.call_args
    assert "Sonarr unreachable" in call_args[0] or "Sonarr unreachable" in str(call_args)


# ---------------------------------------------------------------------------
# Cas : enqueue (API publique synchrone)
# ---------------------------------------------------------------------------


def test_enqueue_puts_item_in_queue():
    """enqueue() dépose un tuple dans la queue sans bloquer."""
    from app.notification_queue import _queue

    initial_size = _queue.qsize()
    enqueue("request", 99, ["x@y.com"], "")
    assert _queue.qsize() == initial_size + 1
    # Vide la queue pour ne pas polluer d'autres tests
    _queue.get_nowait()


# ---------------------------------------------------------------------------
# Cas : _load_pending — une ligne corrompue ne doit jamais faire perdre les
# autres (voir notification_queue.py : incident réel où des lignes poll_history
# mal insérées dans pending_notifications faisaient échouer tout le rechargement).
# ---------------------------------------------------------------------------


@pytest.fixture()
def pending_db():
    import json as _json

    from sqlalchemy import create_engine
    from sqlalchemy import text as _text
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.models import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    def _insert(event, req_id, recipients, reason=""):
        session.execute(
            _text(
                "INSERT INTO pending_notifications (created_at, event, req_id, recipients, reason) "
                "VALUES (:created_at, :event, :req_id, :recipients, :reason)"
            ),
            {
                "created_at": "2026-07-11 21:19:56.602985",
                "event": event,
                "req_id": req_id,
                "recipients": _json.dumps(recipients),
                "reason": reason,
            },
        )
        session.commit()

    def _insert_garbage():
        # Reproduit exactement l'incident : des données shape "poll_history" dans
        # les colonnes de pending_notifications (created_at contient "watchlist",
        # event contient un timestamp).
        session.execute(
            _text(
                "INSERT INTO pending_notifications (created_at, event, req_id, recipients, reason) "
                "VALUES ('watchlist', '2026-07-11 21:19:56.602985', 2192, '70', '0')"
            )
        )
        session.commit()

    session.insert = _insert
    session.insert_garbage = _insert_garbage
    yield session
    session.close()


def test_load_pending_skips_garbage_rows_without_losing_valid_ones(pending_db):
    from app.notification_queue import _load_pending, _queue

    pending_db.insert("request", 1, ["alice@example.com"])
    pending_db.insert_garbage()
    pending_db.insert("available", 2, ["bob@example.com"], reason='{"scope": "movie"}')

    initial_size = _queue.qsize()
    with patch("app.notification_queue.SessionLocal", return_value=pending_db):
        _load_pending()

    loaded = [_queue.get_nowait() for _ in range(_queue.qsize() - initial_size)]
    events = {item[1] for item in loaded}
    assert events == {"request", "available"}
    assert len(loaded) == 2


def test_load_pending_skips_row_with_invalid_req_id(pending_db):
    from app.notification_queue import _load_pending, _queue

    pending_db.execute(
        text(
            "INSERT INTO pending_notifications (created_at, event, req_id, recipients, reason) "
            "VALUES ('2026-07-11 21:19:56', 'request', 'not-an-id', '[]', '')"
        )
    )
    pending_db.commit()
    pending_db.insert("request", 3, ["carol@example.com"])

    initial_size = _queue.qsize()
    with patch("app.notification_queue.SessionLocal", return_value=pending_db):
        _load_pending()

    loaded = [_queue.get_nowait() for _ in range(_queue.qsize() - initial_size)]
    assert len(loaded) == 1
    assert loaded[0][2] == 3


def test_load_pending_recovers_all_rows_when_none_are_corrupt(pending_db):
    from app.notification_queue import _load_pending, _queue

    pending_db.insert("request", 10, ["a@example.com"])
    pending_db.insert("available", 11, ["b@example.com"])
    pending_db.insert("failed", 12, ["c@example.com"], reason="Sonarr down")

    initial_size = _queue.qsize()
    with patch("app.notification_queue.SessionLocal", return_value=pending_db):
        _load_pending()

    loaded = [_queue.get_nowait() for _ in range(_queue.qsize() - initial_size)]
    assert len(loaded) == 3


# ---------------------------------------------------------------------------
# Cas : stop_worker — doit attendre la sortie effective du worker (pas juste
# demander l'annulation) avant de rendre la main à l'appelant (lifespan).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_worker_waits_for_task_to_actually_finish():
    import asyncio as _asyncio

    import app.notification_queue as nq

    finished = _asyncio.Event()

    async def fake_worker():
        try:
            await _asyncio.sleep(100)
        except _asyncio.CancelledError:
            finished.set()
            raise

    nq._worker_task = _asyncio.create_task(fake_worker())
    await _asyncio.sleep(0)  # laisse le worker démarrer et atteindre son premier await, comme en prod
    await nq.stop_worker()

    assert finished.is_set()
    assert nq._worker_task.done()


@pytest.mark.asyncio
async def test_stop_worker_is_noop_without_running_task():
    import app.notification_queue as nq

    nq._worker_task = None
    await nq.stop_worker()  # ne doit pas lever


@pytest.mark.asyncio
async def test_stop_worker_gives_up_after_timeout_if_task_ignores_cancellation():
    """stop_worker() ne doit jamais bloquer indéfiniment, même si le worker met du
    temps à répondre à l'annulation (ex. bloqué dans un envoi SMTP) — il rend la
    main après son timeout de 5s plutôt que d'empêcher tout arrêt du process."""
    import asyncio as _asyncio

    import app.notification_queue as nq

    ignored_once = _asyncio.Event()

    async def slow_to_cancel_worker():
        # Ignore une seule annulation (simule un travail en cours qui ne peut pas
        # être interrompu instantanément), puis se termine normalement à la suivante
        # — sans quoi ce test laisserait une tâche orpheline tourner indéfiniment.
        try:
            await _asyncio.sleep(100)
        except _asyncio.CancelledError:
            ignored_once.set()
        await _asyncio.sleep(100)

    nq._worker_task = _asyncio.create_task(slow_to_cancel_worker())
    await _asyncio.sleep(0)  # laisse le worker démarrer, comme en prod

    started = _asyncio.get_event_loop().time()
    await _asyncio.wait_for(nq.stop_worker(), timeout=7)
    elapsed = _asyncio.get_event_loop().time() - started

    assert ignored_once.is_set()
    assert elapsed < 7  # a bien rendu la main via son propre timeout (~5s), pas via wait_for

    # Nettoyage réel pour ne pas polluer les autres tests.
    nq._worker_task.cancel()
    try:
        await nq._worker_task
    except _asyncio.CancelledError:
        pass
