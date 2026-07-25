"""Tests unitaires pour app/services/email_providers.py (dispatch + repli multi-fournisseurs)."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base, EmailProvider
from app.services import brevo_email, email_providers, microsoft_oauth


async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _smtp_provider(**kwargs) -> EmailProvider:
    defaults = dict(
        name="SMTP perso",
        provider_type="smtp",
        enabled=True,
        priority=0,
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_tls=True,
        smtp_user="user@example.com",
        smtp_password="secret",
    )
    defaults.update(kwargs)
    return EmailProvider(**defaults)


def _oauth_provider(**kwargs) -> EmailProvider:
    defaults = dict(
        name="Hotmail perso",
        provider_type="smtp_oauth2",
        enabled=True,
        priority=0,
        smtp_host="smtp-mail.outlook.com",
        smtp_port=587,
        smtp_tls=True,
        oauth_mailbox="user@hotmail.fr",
        oauth_refresh_token="ref-1",
    )
    defaults.update(kwargs)
    return EmailProvider(**defaults)


def _brevo_provider(**kwargs) -> EmailProvider:
    defaults = dict(name="Brevo", provider_type="brevo", enabled=True, priority=0, brevo_api_key="brevo-key-123")
    defaults.update(kwargs)
    return EmailProvider(**defaults)


# ---------------------------------------------------------------------------
# send_via_provider — dispatch par type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_via_provider_smtp_uses_starttls_when_tls_true():
    with patch("app.services.email_providers.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await email_providers.send_via_provider(
            _smtp_provider(smtp_tls=True), "from@example.com", "dest@example.com", "Sujet", "<p>Corps</p>"
        )
    kwargs = mock_send.call_args[1]
    assert kwargs["start_tls"] is True
    assert kwargs["use_tls"] is False
    assert kwargs["username"] == "user@example.com"
    assert kwargs["password"] == "secret"
    msg = mock_send.call_args[0][0]
    assert msg["From"] == "from@example.com"
    assert msg["To"] == "dest@example.com"
    assert msg["Subject"] == "Sujet"


@pytest.mark.asyncio
async def test_send_via_provider_smtp_uses_ssl_when_tls_false():
    with patch("app.services.email_providers.aiosmtplib.send", new=AsyncMock()) as mock_send:
        await email_providers.send_via_provider(
            _smtp_provider(smtp_tls=False), "from@example.com", "dest@example.com", "Sujet", "<p>Corps</p>"
        )
    kwargs = mock_send.call_args[1]
    assert kwargs["use_tls"] is True
    assert kwargs["start_tls"] is False


@pytest.mark.asyncio
async def test_send_via_provider_smtp_raises_when_incomplete():
    with patch("app.services.email_providers.aiosmtplib.send", new=AsyncMock()) as mock_send:
        with pytest.raises(RuntimeError, match="incomplète"):
            await email_providers.send_via_provider(
                _smtp_provider(smtp_password=None), "from@example.com", "dest@example.com", "Sujet", "<p>x</p>"
            )
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_send_via_provider_oauth2_uses_mailbox_and_token_generator():
    with (
        patch("app.services.email_providers.aiosmtplib.send", new=AsyncMock()) as mock_send,
        patch.object(
            microsoft_oauth, "get_valid_access_token", new=AsyncMock(return_value="access-token-xyz")
        ) as mock_token,
    ):
        await email_providers.send_via_provider(
            _oauth_provider(), "from@example.com", "dest@example.com", "Sujet", "<p>x</p>"
        )
        kwargs = mock_send.call_args[1]
        assert kwargs["username"] == "user@hotmail.fr"
        assert "password" not in kwargs
        assert await kwargs["oauth_token_generator"]() == "access-token-xyz"
        mock_token.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_via_provider_oauth2_raises_when_mailbox_missing():
    with patch("app.services.email_providers.aiosmtplib.send", new=AsyncMock()) as mock_send:
        with pytest.raises(RuntimeError, match="incomplète"):
            await email_providers.send_via_provider(
                _oauth_provider(oauth_mailbox=None), "from@example.com", "dest@example.com", "Sujet", "<p>x</p>"
            )
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_send_via_provider_brevo_calls_api_not_smtp():
    with (
        patch("app.services.email_providers.aiosmtplib.send", new=AsyncMock()) as mock_smtp,
        patch.object(brevo_email, "send_transactional_email", new=AsyncMock(return_value="msg-1")) as mock_brevo,
    ):
        await email_providers.send_via_provider(
            _brevo_provider(), "from@example.com", "dest@example.com", "Sujet", "<p>x</p>"
        )
    mock_smtp.assert_not_called()
    mock_brevo.assert_awaited_once()
    kwargs = mock_brevo.call_args.kwargs
    assert kwargs["api_key"] == "brevo-key-123"
    assert kwargs["sender_email"] == "from@example.com"
    assert kwargs["to_email"] == "dest@example.com"


@pytest.mark.asyncio
async def test_send_via_provider_brevo_raises_when_api_key_missing():
    with patch.object(brevo_email, "send_transactional_email", new=AsyncMock()) as mock_brevo:
        with pytest.raises(RuntimeError, match="Brevo incomplète"):
            await email_providers.send_via_provider(
                _brevo_provider(brevo_api_key=None), "from@example.com", "dest@example.com", "Sujet", "<p>x</p>"
            )
    mock_brevo.assert_not_called()


# ---------------------------------------------------------------------------
# get_enabled_providers / has_enabled_provider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_enabled_providers_orders_by_priority_and_excludes_disabled():
    session_factory = await _database()
    async with session_factory() as db:
        db.add_all(
            [
                _smtp_provider(name="second", priority=2),
                _smtp_provider(name="first", priority=1),
                _smtp_provider(name="disabled", priority=0, enabled=False),
            ]
        )
        await db.commit()

        providers = await email_providers.get_enabled_providers(db)
        assert [p.name for p in providers] == ["first", "second"]


@pytest.mark.asyncio
async def test_has_enabled_provider_false_when_none_or_all_disabled():
    session_factory = await _database()
    async with session_factory() as db:
        assert await email_providers.has_enabled_provider(db) is False

        db.add(_smtp_provider(enabled=False))
        await db.commit()
        assert await email_providers.has_enabled_provider(db) is False


# ---------------------------------------------------------------------------
# send_with_fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_with_fallback_raises_without_any_provider():
    session_factory = await _database()
    async with session_factory() as db:
        with pytest.raises(RuntimeError, match="Aucun fournisseur"):
            await email_providers.send_with_fallback(db, "from@example.com", "dest@example.com", "Sujet", "<p>x</p>")


@pytest.mark.asyncio
async def test_send_with_fallback_uses_first_provider_when_it_succeeds():
    session_factory = await _database()
    async with session_factory() as db:
        db.add_all([_smtp_provider(name="A", priority=0), _brevo_provider(name="B", priority=1)])
        await db.commit()

        with (
            patch.object(email_providers, "send_via_provider", new=AsyncMock()) as mock_dispatch,
        ):
            await email_providers.send_with_fallback(db, "from@example.com", "dest@example.com", "Sujet", "<p>x</p>")
        mock_dispatch.assert_awaited_once()
        assert mock_dispatch.call_args[0][0].name == "A"


@pytest.mark.asyncio
async def test_send_with_fallback_tries_next_provider_after_failure():
    session_factory = await _database()
    async with session_factory() as db:
        db.add_all([_smtp_provider(name="A", priority=0), _brevo_provider(name="B", priority=1)])
        await db.commit()

        calls = []

        async def _fake_dispatch(provider, *a, **kw):
            calls.append(provider.name)
            if provider.name == "A":
                raise RuntimeError("connexion refusée")

        with patch.object(email_providers, "send_via_provider", new=_fake_dispatch):
            await email_providers.send_with_fallback(db, "from@example.com", "dest@example.com", "Sujet", "<p>x</p>")

        assert calls == ["A", "B"]


@pytest.mark.asyncio
async def test_send_with_fallback_raises_aggregated_error_when_all_fail():
    session_factory = await _database()
    async with session_factory() as db:
        db.add_all([_smtp_provider(name="A", priority=0), _brevo_provider(name="B", priority=1)])
        await db.commit()

        async def _always_fail(provider, *a, **kw):
            raise RuntimeError(f"échec {provider.name}")

        with patch.object(email_providers, "send_via_provider", new=_always_fail):
            with pytest.raises(RuntimeError) as exc_info:
                await email_providers.send_with_fallback(
                    db, "from@example.com", "dest@example.com", "Sujet", "<p>x</p>"
                )
        assert "échec A" in str(exc_info.value)
        assert "échec B" in str(exc_info.value)


# ---------------------------------------------------------------------------
# test_provider — envoi de test sur UN fournisseur, sans repli
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_provider_success():
    with patch.object(email_providers, "send_via_provider", new=AsyncMock()):
        ok, message = await email_providers.test_provider(_smtp_provider(), "from@example.com", "dest@example.com")
    assert ok is True
    assert "dest@example.com" in message


@pytest.mark.asyncio
async def test_test_provider_failure_returns_message_not_exception():
    with patch.object(email_providers, "send_via_provider", new=AsyncMock(side_effect=RuntimeError("auth failed"))):
        ok, message = await email_providers.test_provider(_smtp_provider(), "from@example.com", "dest@example.com")
    assert ok is False
    assert "auth failed" in message
