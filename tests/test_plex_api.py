"""Tests unitaires pour app/services/plex_api.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.plex_api import _parse_api_item, check_connection, get_friends_watchlist

URL = "http://plex.local"
TOKEN = "testplextoken"


def _resp(status_code: int, json_data=None) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data or {}
    r.raise_for_status = MagicMock()
    return r


# ---------------------------------------------------------------------------
# check_connection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_connection_success():
    """Serveur Plex local joignable + token valide → success=True."""
    resp = _resp(200, {"MediaContainer": {"machineIdentifier": "abc123"}})
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=resp)

    with patch("app.services.plex_api.httpx.AsyncClient", return_value=client):
        success, msg = await check_connection(URL, TOKEN)

    assert success is True
    assert "abc123" in msg
    # Doit interroger le serveur Plex local (plex_url), pas plex.tv.
    called_url = client.get.call_args[0][0]
    assert called_url.startswith(URL)


@pytest.mark.asyncio
async def test_check_connection_failure():
    """Erreur réseau (ex: mauvaise IP) → success=False, message explicite."""
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=Exception("All connection attempts failed"))

    with patch("app.services.plex_api.httpx.AsyncClient", return_value=client):
        success, msg = await check_connection(URL, TOKEN)

    assert success is False
    assert "All connection attempts failed" in msg


@pytest.mark.asyncio
async def test_check_connection_no_url_configured():
    """URL Plex vide → échec immédiat, sans appel réseau."""
    success, msg = await check_connection("", TOKEN)
    assert success is False
    assert "non configurée" in msg


# ---------------------------------------------------------------------------
# _parse_api_item — clé plex_user présente, plex_user_id absente
# ---------------------------------------------------------------------------


def test_parse_api_item_contains_plex_user():
    """_parse_api_item retourne 'plex_user' et 'plex_user_id' (support multi-utilisateur)."""
    raw = {
        "title": "Inception",
        "type": "movie",
        "guid": "plex://movie/abc123",
        "Guid": [{"id": "tmdb://27205"}, {"id": "imdb://tt1375666"}],
        "thumb": "/thumb/abc",
        "summary": "Un rêve dans un rêve",
    }
    item = _parse_api_item(raw, "Alice", "Alice")

    assert item["plex_user"] == "Alice"
    assert item["plex_user_id"] == "Alice"
    assert item["title"] == "Inception"
    assert item["media_type"] == "movie"
    assert item["tmdb_id"] == "27205"
    assert item["imdb_id"] == "tt1375666"


def test_parse_api_item_show_type():
    """Type 'show' mappé correctement."""
    raw = {"title": "Breaking Bad", "type": "show", "guid": "plex://show/xyz", "Guid": []}
    item = _parse_api_item(raw, "Bob", "Bob")

    assert item["media_type"] == "show"
    assert item["plex_user"] == "Bob"


def test_parse_api_item_thumb_prefixed_with_tmdb_cdn():
    """Thumb relatif préfixé avec le CDN TMDB."""
    raw = {"title": "Test", "type": "movie", "guid": "", "Guid": [], "thumb": "/images/poster.jpg"}
    item = _parse_api_item(raw, "User", "User")

    assert item["poster_url"].startswith("https://image.tmdb.org/t/p/w300")


# ---------------------------------------------------------------------------
# get_friends_watchlist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_friends_watchlist_items_have_plex_user():
    """Items retournés par get_friends_watchlist contiennent 'plex_user'."""
    # /api/v2/friends retourne une liste avec authToken directement dans l'objet friend
    friends_resp = _resp(200, [{"title": "Alice", "username": "Alice", "authToken": "token_alice"}])
    # _get_user_watchlist pour Alice
    alice_watchlist = _resp(
        200,
        {
            "MediaContainer": {
                "Metadata": [{"title": "Inception", "type": "movie", "guid": "plex://movie/abc", "Guid": []}]
            }
        },
    )
    # _get_account_username (résolution du username admin avant sa propre watchlist)
    admin_user_resp = _resp(200, {"username": "admin"})
    # _get_user_watchlist pour admin (toujours inclus)
    admin_watchlist = _resp(200, {"MediaContainer": {"Metadata": []}})

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    # 1er appel : /api/v2/friends, 2e : watchlist Alice, 3e : /api/v2/user (admin), 4e : watchlist admin
    client.get = AsyncMock(side_effect=[friends_resp, alice_watchlist, admin_user_resp, admin_watchlist])

    with patch("app.services.plex_api.httpx.AsyncClient", return_value=client):
        items = await get_friends_watchlist(URL, TOKEN)

    assert len(items) == 1
    assert items[0]["plex_user"] == "Alice"
    assert items[0]["plex_user_id"] == "Alice"
    assert items[0]["title"] == "Inception"


@pytest.mark.asyncio
async def test_get_friends_watchlist_no_auth_token_friend_skipped():
    """Un ami sans authToken est ignoré."""
    friends_resp = _resp(
        200,
        [
            {"title": "NoToken", "username": "NoToken"}  # pas d'authToken
        ],
    )
    admin_user_resp = _resp(200, {"username": "admin"})
    admin_watchlist = _resp(200, {"MediaContainer": {"Metadata": []}})

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=[friends_resp, admin_user_resp, admin_watchlist])

    with patch("app.services.plex_api.httpx.AsyncClient", return_value=client):
        items = await get_friends_watchlist(URL, TOKEN)

    assert items == []
