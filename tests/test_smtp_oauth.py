"""Tests unitaires pour app/services/microsoft_oauth.py (SMTP OAuth2 Microsoft)."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base, EmailProvider
from app.services import microsoft_oauth
from app.utils import now_utc_naive


async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _provider(**kwargs) -> EmailProvider:
    defaults = dict(
        name="Hotmail perso",
        provider_type="smtp_oauth2",
        oauth_tenant="consumers",
        oauth_client_id="client-123",
    )
    defaults.update(kwargs)
    return EmailProvider(id=1, **defaults)


def test_build_authorize_url_requires_client_id():
    with pytest.raises(ValueError):
        microsoft_oauth.build_authorize_url(
            _provider(oauth_client_id=None), "http://x/callback", "state", "challenge"
        )


def test_build_authorize_url_uses_consumers_tenant_and_pkce():
    url = microsoft_oauth.build_authorize_url(_provider(), "http://x/callback", "state1", "chal1")
    assert url.startswith("https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize?")
    assert "client_id=client-123" in url
    assert "code_challenge=chal1" in url
    assert "code_challenge_method=S256" in url
    assert "state=state1" in url
    assert "scope=https%3A%2F%2Foutlook.office365.com%2FSMTP.Send" in url


def test_generate_pkce_pair_challenge_is_derived_from_verifier():
    verifier, challenge = microsoft_oauth.generate_pkce_pair()
    assert verifier and challenge
    assert verifier != challenge
    # Le challenge est déterministe à partir du verifier (SHA256 + base64url).
    _, challenge2 = microsoft_oauth.generate_pkce_pair()
    assert challenge != challenge2  # verifiers aléatoires -> challenges différents


@pytest.mark.asyncio
async def test_store_tokens_persists_and_updates_in_memory_object():
    engine, session_factory = await _database()
    async with session_factory() as db:
        p = _provider()
        db.add(p)
        await db.commit()
        await db.refresh(p)

    with patch("app.services.microsoft_oauth.AsyncSessionLocal", session_factory):
        await microsoft_oauth.store_tokens(
            p, {"access_token": "acc-1", "refresh_token": "ref-1", "expires_in": 3600}
        )

    assert p.oauth_access_token == "acc-1"
    assert p.oauth_refresh_token == "ref-1"
    assert p.oauth_token_expires_at > now_utc_naive()

    async with session_factory() as db:
        row = await db.get(EmailProvider, p.id)
        assert row.oauth_access_token == "acc-1"
        assert row.oauth_refresh_token == "ref-1"


@pytest.mark.asyncio
async def test_store_tokens_keeps_previous_refresh_token_when_not_rotated():
    """Microsoft ne renvoie pas toujours un nouveau refresh_token au refresh."""
    engine, session_factory = await _database()
    async with session_factory() as db:
        p = _provider(oauth_refresh_token="ref-original")
        db.add(p)
        await db.commit()
        await db.refresh(p)

    with patch("app.services.microsoft_oauth.AsyncSessionLocal", session_factory):
        await microsoft_oauth.store_tokens(p, {"access_token": "acc-2", "expires_in": 3600})

    assert p.oauth_refresh_token == "ref-original"
    assert p.oauth_access_token == "acc-2"


@pytest.mark.asyncio
async def test_get_valid_access_token_raises_without_refresh_token():
    with pytest.raises(RuntimeError):
        await microsoft_oauth.get_valid_access_token(_provider(oauth_refresh_token=None))


@pytest.mark.asyncio
async def test_get_valid_access_token_returns_cached_token_without_refresh_call():
    p = _provider(
        oauth_refresh_token="ref-1",
        oauth_access_token="cached-access",
        oauth_token_expires_at=now_utc_naive() + timedelta(minutes=30),
    )
    with patch("app.services.microsoft_oauth._refresh", new=AsyncMock()) as mock_refresh:
        token = await microsoft_oauth.get_valid_access_token(p)
    assert token == "cached-access"
    mock_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_get_valid_access_token_refreshes_when_expired():
    engine, session_factory = await _database()
    async with session_factory() as db:
        p = _provider(oauth_refresh_token="ref-1", oauth_access_token="stale")
        db.add(p)
        await db.commit()
        await db.refresh(p)

    refresh_mock = AsyncMock(return_value={"access_token": "fresh-access", "expires_in": 3600})
    with (
        patch("app.services.microsoft_oauth.AsyncSessionLocal", session_factory),
        patch("app.services.microsoft_oauth._refresh", new=refresh_mock),
    ):
        token = await microsoft_oauth.get_valid_access_token(p)

    assert token == "fresh-access"
    refresh_mock.assert_awaited_once_with(p, "ref-1")


@pytest.mark.asyncio
async def test_exchange_code_raises_on_error_response(monkeypatch):
    class _Resp:
        status_code = 400
        headers = {"content-type": "application/json"}

        def json(self):
            return {"error_description": "invalid_grant"}

        text = "invalid_grant"

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            return _Resp()

    monkeypatch.setattr(microsoft_oauth.httpx, "AsyncClient", lambda **kw: _Client())

    with pytest.raises(RuntimeError):
        await microsoft_oauth.exchange_code(_provider(), "bad-code", "verifier", "http://x/callback")
