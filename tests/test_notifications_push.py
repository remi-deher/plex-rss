"""Tests unitaires pour services/notifications.py (Discord + Telegram)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.notifications import (
    _build_discord_embed,
    _build_message,
    _post_discord_embed,
    _post_telegram_message,
    send_all,
    send_discord,
    send_discord_to_webhook,
    send_telegram,
    send_telegram_to_chat,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _req(title="Dune", media_type="movie", year=2021,
         plex_user="Alice", plex_user_id="alice",
         overview="Un épopée.", poster_url=None):
    r = MagicMock()
    r.title = title
    r.media_type = media_type
    r.year = year
    r.plex_user = plex_user
    r.plex_user_id = plex_user_id
    r.overview = overview
    r.poster_url = poster_url
    return r


def _settings(discord_webhook_url=None, telegram_bot_token=None, telegram_chat_id=None):
    s = MagicMock()
    s.discord_webhook_url = discord_webhook_url
    s.telegram_bot_token = telegram_bot_token
    s.telegram_chat_id = telegram_chat_id
    return s


def _httpx_mock(raise_on_status=False):
    """Retourne un mock AsyncClient qui simule httpx."""
    mock_resp = MagicMock()
    if raise_on_status:
        mock_resp.raise_for_status.side_effect = Exception("HTTP 500")
    mock_instance = AsyncMock()
    mock_instance.post = AsyncMock(return_value=mock_resp)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_instance)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, mock_instance, mock_resp


# ---------------------------------------------------------------------------
# _build_message
# ---------------------------------------------------------------------------


def test_build_message_request_movie():
    title, body = _build_message("request", _req(title="Dune", media_type="movie", year=2021, plex_user="Alice"))
    assert "Dune" in title
    assert "2021" in title
    assert "Film" in body
    assert "Alice" in body


def test_build_message_request_show():
    title, body = _build_message("request", _req(title="The Bear", media_type="show", year=None, plex_user="Bob"))
    assert "The Bear" in title
    assert "year" not in title.lower()
    assert "Série" in body
    assert "Bob" in body


def test_build_message_available():
    title, body = _build_message("available", _req(title="Inception"))
    assert "Disponible" in title
    assert "disponible" in body.lower()


def test_build_message_failed_movie():
    title, body = _build_message("failed", _req(media_type="movie"))
    assert "Echec" in title
    assert "Radarr" in body


def test_build_message_failed_show():
    title, body = _build_message("failed", _req(media_type="show"))
    assert "Sonarr" in body


def test_build_message_unknown_event():
    title, body = _build_message("other", _req(title="X"))
    assert "X" in title


# ---------------------------------------------------------------------------
# _build_discord_embed
# ---------------------------------------------------------------------------


def test_build_discord_embed_request_color():
    embed = _build_discord_embed("request", _req())
    assert embed["color"] == 0xE5A00D


def test_build_discord_embed_available_color():
    embed = _build_discord_embed("available", _req())
    assert embed["color"] == 0x1DB954


def test_build_discord_embed_with_poster():
    r = _req(poster_url="https://img.example.com/poster.jpg")
    embed = _build_discord_embed("request", r)
    assert embed["thumbnail"]["url"] == "https://img.example.com/poster.jpg"


def test_build_discord_embed_no_poster():
    embed = _build_discord_embed("request", _req(poster_url=None))
    assert "thumbnail" not in embed


def test_build_discord_embed_with_synopsis():
    r = _req(overview="Résumé du film.")
    embed = _build_discord_embed("request", r, include_synopsis=True)
    assert any(f["name"] == "Synopsis" for f in embed.get("fields", []))


def test_build_discord_embed_no_synopsis_by_default():
    r = _req(overview="Résumé du film.")
    embed = _build_discord_embed("request", r)
    assert "fields" not in embed


# ---------------------------------------------------------------------------
# _post_discord_embed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_discord_embed_calls_post():
    ctx, mock_instance, mock_resp = _httpx_mock()
    with patch("app.services.notifications.httpx.AsyncClient", return_value=ctx):
        await _post_discord_embed("https://hook.example.com", {"title": "test"})
    mock_instance.post.assert_called_once()
    mock_resp.raise_for_status.assert_called_once()


@pytest.mark.asyncio
async def test_post_discord_embed_raises_on_http_error():
    ctx, mock_instance, _ = _httpx_mock(raise_on_status=True)
    with patch("app.services.notifications.httpx.AsyncClient", return_value=ctx):
        with pytest.raises(Exception, match="HTTP 500"):
            await _post_discord_embed("https://hook.example.com", {})


# ---------------------------------------------------------------------------
# _post_telegram_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_telegram_message_calls_post():
    ctx, mock_instance, mock_resp = _httpx_mock()
    with patch("app.services.notifications.httpx.AsyncClient", return_value=ctx):
        await _post_telegram_message("token123", "chat456", "Hello")
    call_args = mock_instance.post.call_args
    assert "bot" in call_args[0][0]
    assert call_args[1]["json"]["chat_id"] == "chat456"
    assert call_args[1]["json"]["text"] == "Hello"


@pytest.mark.asyncio
async def test_post_telegram_message_raises_on_http_error():
    ctx, _, _ = _httpx_mock(raise_on_status=True)
    with patch("app.services.notifications.httpx.AsyncClient", return_value=ctx):
        with pytest.raises(Exception):
            await _post_telegram_message("tok", "chat", "msg")


# ---------------------------------------------------------------------------
# send_discord
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_discord_no_url_returns_early():
    s = _settings(discord_webhook_url=None)
    # Pas d'appel httpx si pas de webhook URL
    with patch("app.services.notifications._post_discord_embed", new_callable=AsyncMock) as mock_post:
        await send_discord(s, _req(), "request")
    mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_send_discord_sends_embed():
    s = _settings(discord_webhook_url="https://hook.example.com")
    with patch("app.services.notifications._post_discord_embed", new_callable=AsyncMock) as mock_post:
        await send_discord(s, _req(), "available")
    mock_post.assert_called_once()
    embed = mock_post.call_args[0][1]
    assert embed["color"] == 0x1DB954


@pytest.mark.asyncio
async def test_send_discord_logs_exception_on_failure():
    s = _settings(discord_webhook_url="https://hook.example.com")
    with patch("app.services.notifications._post_discord_embed", new_callable=AsyncMock, side_effect=Exception("Network error")):
        # Ne doit pas remonter l'exception
        await send_discord(s, _req(), "request")


# ---------------------------------------------------------------------------
# send_discord_to_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_discord_to_webhook_sends():
    with patch("app.services.notifications._post_discord_embed", new_callable=AsyncMock) as mock_post:
        await send_discord_to_webhook("https://hook.example.com", _req(), "request")
    mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_send_discord_to_webhook_exception_logged():
    with patch("app.services.notifications._post_discord_embed", new_callable=AsyncMock, side_effect=Exception("err")):
        await send_discord_to_webhook("https://hook.example.com", _req(), "request")


# ---------------------------------------------------------------------------
# send_telegram
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_telegram_no_token_returns_early():
    s = _settings(telegram_bot_token=None, telegram_chat_id="123")
    with patch("app.services.notifications._post_telegram_message", new_callable=AsyncMock) as mock_post:
        await send_telegram(s, _req(), "request")
    mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_send_telegram_no_chat_id_returns_early():
    s = _settings(telegram_bot_token="tok", telegram_chat_id=None)
    with patch("app.services.notifications._post_telegram_message", new_callable=AsyncMock) as mock_post:
        await send_telegram(s, _req(), "request")
    mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_send_telegram_sends_message():
    s = _settings(telegram_bot_token="tok", telegram_chat_id="chat")
    with patch("app.services.notifications._post_telegram_message", new_callable=AsyncMock) as mock_post:
        await send_telegram(s, _req(title="Inception", overview="Rêve."), "available")
    mock_post.assert_called_once()
    text = mock_post.call_args[0][2]
    assert "Inception" in text
    assert "Rêve" in text


@pytest.mark.asyncio
async def test_send_telegram_logs_exception():
    s = _settings(telegram_bot_token="tok", telegram_chat_id="chat")
    with patch("app.services.notifications._post_telegram_message", new_callable=AsyncMock, side_effect=Exception("Timeout")):
        await send_telegram(s, _req(), "request")


# ---------------------------------------------------------------------------
# send_telegram_to_chat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_telegram_to_chat_sends():
    with patch("app.services.notifications._post_telegram_message", new_callable=AsyncMock) as mock_post:
        await send_telegram_to_chat("tok", "chat", _req(title="Dune"), "request")
    mock_post.assert_called_once()
    assert "Dune" in mock_post.call_args[0][2]


@pytest.mark.asyncio
async def test_send_telegram_to_chat_exception_logged():
    with patch("app.services.notifications._post_telegram_message", new_callable=AsyncMock, side_effect=Exception("err")):
        await send_telegram_to_chat("tok", "chat", _req(), "request")


# ---------------------------------------------------------------------------
# send_all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_all_calls_both():
    s = _settings()
    with (
        patch("app.services.notifications.send_discord", new_callable=AsyncMock) as mock_dc,
        patch("app.services.notifications.send_telegram", new_callable=AsyncMock) as mock_tg,
    ):
        await send_all(s, _req(), "available")
    mock_dc.assert_called_once_with(s, mock_dc.call_args[0][1], "available")
    mock_tg.assert_called_once()
