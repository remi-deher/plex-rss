"""Tests unitaires pour app/services/sonarr.py.

Tous les appels httpx sont mockés — aucune instance Sonarr réelle n'est requise.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.sonarr import add_series, check_connection, is_series_available, lookup_series

URL = "http://sonarr.local:8989"
KEY = "testapikey"
ITEM = {"title": "Breaking Bad", "media_type": "show", "tvdb_id": "81189"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(status_code: int, json_data) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _make_error_response(status_code: int) -> MagicMock:
    resp = _make_response(status_code, {})
    resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


# ---------------------------------------------------------------------------
# add_series
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_series_new():
    """Série inexistante → ajoutée, already_existed=False."""
    existing_resp = _make_response(200, [])  # liste vide
    add_resp = _make_response(201, {"id": 42, "titleSlug": "breaking-bad"})

    client_mock = AsyncMock()
    client_mock.get = AsyncMock(return_value=existing_resp)
    client_mock.post = AsyncMock(return_value=add_resp)
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.sonarr.httpx.AsyncClient", return_value=client_mock):
        arr_id, already_existed, slug = await add_series(URL, KEY, 1, "/tv", ITEM)

    assert arr_id == 42
    assert already_existed is False
    assert slug == "breaking-bad"


@pytest.mark.asyncio
async def test_add_series_already_exists():
    """Série déjà dans Sonarr → retourne l'ID existant, already_existed=True."""
    existing_series = [{"id": 7, "tvdbId": 81189, "titleSlug": "breaking-bad"}]
    existing_resp = _make_response(200, existing_series)

    client_mock = AsyncMock()
    client_mock.get = AsyncMock(return_value=existing_resp)
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.sonarr.httpx.AsyncClient", return_value=client_mock):
        arr_id, already_existed, slug = await add_series(URL, KEY, 1, "/tv", ITEM)

    assert arr_id == 7
    assert already_existed is True
    assert slug == "breaking-bad"
    client_mock.post.assert_not_called()


@pytest.mark.asyncio
async def test_add_series_no_tvdb_id_lookup_success():
    """Pas de TVDB ID dans l'item → lookup par titre → série ajoutée."""
    item = {"title": "Breaking Bad", "media_type": "show"}  # pas de tvdb_id

    lookup_resp = _make_response(200, [{"tvdbId": 81189}])
    existing_resp = _make_response(200, [])
    add_resp = _make_response(201, {"id": 99, "titleSlug": "breaking-bad"})

    client_mock = AsyncMock()
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = AsyncMock(return_value=False)

    # GET appelé d'abord pour le lookup, puis pour la liste existante
    client_mock.get = AsyncMock(side_effect=[lookup_resp, existing_resp])
    client_mock.post = AsyncMock(return_value=add_resp)

    with patch("app.services.sonarr.httpx.AsyncClient", return_value=client_mock):
        arr_id, already_existed, slug = await add_series(URL, KEY, 1, "/tv", item)

    assert arr_id == 99
    assert already_existed is False


@pytest.mark.asyncio
async def test_add_series_no_tvdb_id_lookup_fails():
    """Pas de TVDB ID et lookup échoue → retourne (None, False, None)."""
    item = {"title": "Série Introuvable", "media_type": "show"}

    client_mock = AsyncMock()
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = AsyncMock(return_value=False)
    client_mock.get = AsyncMock(side_effect=Exception("timeout"))

    with patch("app.services.sonarr.httpx.AsyncClient", return_value=client_mock):
        arr_id, already_existed, slug = await add_series(URL, KEY, 1, "/tv", item)

    assert arr_id is None
    assert already_existed is False
    assert slug is None


# ---------------------------------------------------------------------------
# is_series_available
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_series_available_true():
    """episodeFileCount > 0 → disponible."""
    series_data = {
        "id": 7,
        "titleSlug": "breaking-bad",
        "statistics": {"episodeFileCount": 5},
    }
    resp = _make_response(200, series_data)

    client_mock = AsyncMock()
    client_mock.get = AsyncMock(return_value=resp)
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.sonarr.httpx.AsyncClient", return_value=client_mock):
        available, arr_id, slug = await is_series_available(URL, KEY, arr_id=7)

    assert available is True
    assert arr_id == 7
    assert slug == "breaking-bad"


@pytest.mark.asyncio
async def test_is_series_available_false():
    """episodeFileCount == 0 → non disponible."""
    series_data = {
        "id": 7,
        "titleSlug": "breaking-bad",
        "statistics": {"episodeFileCount": 0},
    }
    resp = _make_response(200, series_data)

    client_mock = AsyncMock()
    client_mock.get = AsyncMock(return_value=resp)
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.sonarr.httpx.AsyncClient", return_value=client_mock):
        available, arr_id, slug = await is_series_available(URL, KEY, arr_id=7)

    assert available is False


@pytest.mark.asyncio
async def test_is_series_available_not_found():
    """Série introuvable dans Sonarr → (False, None, None)."""
    resp = _make_response(404, {})
    resp.raise_for_status.side_effect = Exception("404")

    client_mock = AsyncMock()
    client_mock.get = AsyncMock(return_value=resp)
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.sonarr.httpx.AsyncClient", return_value=client_mock):
        available, arr_id, slug = await is_series_available(URL, KEY, arr_id=999)

    assert available is False
    assert arr_id is None


@pytest.mark.asyncio
async def test_is_series_available_by_tvdb_id():
    """Recherche par tvdb_id quand arr_id absent."""
    series_list = [
        {"id": 3, "tvdbId": 81189, "titleSlug": "breaking-bad", "statistics": {"episodeFileCount": 2}},
        {"id": 4, "tvdbId": 99999, "titleSlug": "other", "statistics": {"episodeFileCount": 0}},
    ]
    resp = _make_response(200, series_list)

    client_mock = AsyncMock()
    client_mock.get = AsyncMock(return_value=resp)
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.sonarr.httpx.AsyncClient", return_value=client_mock):
        available, arr_id, slug = await is_series_available(URL, KEY, tvdb_id="81189")

    assert available is True
    assert arr_id == 3


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_success():
    resp = _make_response(200, {"version": "3.0.10"})

    client_mock = AsyncMock()
    client_mock.get = AsyncMock(return_value=resp)
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.sonarr.httpx.AsyncClient", return_value=client_mock):
        success, msg = await check_connection(URL, KEY)

    assert success is True
    assert "3.0.10" in msg


@pytest.mark.asyncio
async def test_connection_failure():
    client_mock = AsyncMock()
    client_mock.get = AsyncMock(side_effect=Exception("Connection refused"))
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.sonarr.httpx.AsyncClient", return_value=client_mock):
        success, msg = await check_connection(URL, KEY)

    assert success is False
    assert "Connection refused" in msg
