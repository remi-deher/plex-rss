"""Tests unitaires pour app/services/watchlist.py — routage API vs RSS."""

from unittest.mock import AsyncMock, patch

import pytest

from app.models import Settings
from app.services.watchlist import fetch_watchlist

API_ITEMS = [{"title": "Inception", "media_type": "movie", "plex_user": "alice"}]
RSS_ITEMS = [{"title": "Breaking Bad", "media_type": "show", "plex_user": "bob"}]


def _settings(**kwargs) -> Settings:
    defaults = dict(
        plex_url="http://plex.local",
        plex_token="token",
        plex_rss_url="http://rss.local/feed",
        watchlist_source_priority="api",
        watchlist_fallback_enabled=True,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


# ---------------------------------------------------------------------------
# Routage selon priorité
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_priority_api_merges_with_rss_when_fallback_enabled():
    """Priorité api + fallback activé → les deux sources sont interrogées et fusionnées.

    L'API Plex peut "réussir" tout en omettant silencieusement certains amis (pas
    d'authToken exposé) : on ne peut donc plus se contenter d'ignorer le RSS dès que
    l'API répond sans exception, sous peine de perdre ces items en silence.
    """
    with (
        patch("app.services.watchlist.get_friends_watchlist", new=AsyncMock(return_value=API_ITEMS)) as mock_api,
        patch("app.services.watchlist.fetch_watchlist_rss", new=AsyncMock(return_value=RSS_ITEMS)) as mock_rss,
    ):
        result = await fetch_watchlist(_settings(watchlist_source_priority="api"))

    mock_api.assert_called_once()
    mock_rss.assert_called_once()
    assert result == API_ITEMS + RSS_ITEMS


@pytest.mark.asyncio
async def test_priority_rss_merges_with_api_when_fallback_enabled():
    """Priorité rss + fallback activé → les deux sources sont interrogées et fusionnées."""
    with (
        patch("app.services.watchlist.get_friends_watchlist", new=AsyncMock(return_value=API_ITEMS)) as mock_api,
        patch("app.services.watchlist.fetch_watchlist_rss", new=AsyncMock(return_value=RSS_ITEMS)) as mock_rss,
    ):
        result = await fetch_watchlist(_settings(watchlist_source_priority="rss"))

    mock_rss.assert_called_once()
    mock_api.assert_called_once()
    assert result == RSS_ITEMS + API_ITEMS


@pytest.mark.asyncio
async def test_priority_api_skips_rss_when_fallback_disabled():
    """Priorité api + fallback désactivé → comportement legacy, RSS jamais consulté."""
    with (
        patch("app.services.watchlist.get_friends_watchlist", new=AsyncMock(return_value=API_ITEMS)) as mock_api,
        patch("app.services.watchlist.fetch_watchlist_rss", new=AsyncMock(return_value=RSS_ITEMS)) as mock_rss,
    ):
        result = await fetch_watchlist(_settings(watchlist_source_priority="api", watchlist_fallback_enabled=False))

    mock_api.assert_called_once()
    mock_rss.assert_not_called()
    assert result == API_ITEMS


@pytest.mark.asyncio
async def test_merge_dedupes_items_present_in_both_sources():
    """Un même item vu via les deux sources ne doit apparaître qu'une fois."""
    shared = [{"title": "Dune", "media_type": "movie", "plex_user": "alice", "tmdb_id": "438631"}]
    with (
        patch("app.services.watchlist.get_friends_watchlist", new=AsyncMock(return_value=shared)),
        patch(
            "app.services.watchlist.fetch_watchlist_rss",
            new=AsyncMock(return_value=shared + RSS_ITEMS),
        ),
    ):
        result = await fetch_watchlist(_settings(watchlist_source_priority="api"))

    assert result == shared + RSS_ITEMS


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_fails_fallback_to_rss():
    """API échoue + fallback activé → RSS utilisé."""
    with (
        patch("app.services.watchlist.get_friends_watchlist", new=AsyncMock(side_effect=Exception("timeout"))),
        patch("app.services.watchlist.fetch_watchlist_rss", new=AsyncMock(return_value=RSS_ITEMS)),
    ):
        result = await fetch_watchlist(_settings(watchlist_source_priority="api", watchlist_fallback_enabled=True))

    assert result == RSS_ITEMS


@pytest.mark.asyncio
async def test_rss_fails_fallback_to_api():
    """RSS échoue + fallback activé → API utilisée."""
    with (
        patch("app.services.watchlist.fetch_watchlist_rss", new=AsyncMock(side_effect=Exception("404"))),
        patch("app.services.watchlist.get_friends_watchlist", new=AsyncMock(return_value=API_ITEMS)),
    ):
        result = await fetch_watchlist(_settings(watchlist_source_priority="rss", watchlist_fallback_enabled=True))

    assert result == API_ITEMS


@pytest.mark.asyncio
async def test_api_fails_fallback_disabled_returns_empty():
    """API échoue + fallback désactivé → liste vide, pas de crash."""
    with (
        patch("app.services.watchlist.get_friends_watchlist", new=AsyncMock(side_effect=Exception("timeout"))),
        patch("app.services.watchlist.fetch_watchlist_rss", new=AsyncMock(return_value=RSS_ITEMS)) as mock_rss,
    ):
        result = await fetch_watchlist(_settings(watchlist_fallback_enabled=False))

    mock_rss.assert_not_called()
    assert result == []


@pytest.mark.asyncio
async def test_both_sources_fail_returns_empty():
    """Les deux sources échouent → liste vide, pas de crash."""
    with (
        patch("app.services.watchlist.get_friends_watchlist", new=AsyncMock(side_effect=Exception("api error"))),
        patch("app.services.watchlist.fetch_watchlist_rss", new=AsyncMock(side_effect=Exception("rss error"))),
    ):
        result = await fetch_watchlist(_settings(watchlist_fallback_enabled=True))

    assert result == []


# ---------------------------------------------------------------------------
# Tokens manquants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_plex_token_raises_and_falls_back_to_rss():
    """Token Plex absent → api_source lève ValueError → fallback RSS."""
    with patch("app.services.watchlist.fetch_watchlist_rss", new=AsyncMock(return_value=RSS_ITEMS)):
        result = await fetch_watchlist(
            _settings(plex_token=None, watchlist_source_priority="api", watchlist_fallback_enabled=True)
        )

    assert result == RSS_ITEMS


@pytest.mark.asyncio
async def test_missing_rss_url_raises_and_falls_back_to_api():
    """URL RSS absente → rss_source lève ValueError → fallback API."""
    with patch("app.services.watchlist.get_friends_watchlist", new=AsyncMock(return_value=API_ITEMS)):
        result = await fetch_watchlist(
            _settings(plex_rss_url=None, watchlist_source_priority="rss", watchlist_fallback_enabled=True)
        )

    assert result == API_ITEMS
