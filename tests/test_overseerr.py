"""Tests unitaires pour app/services/overseerr.py."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.overseerr import check_connection, is_request_available, request_media

URL = "http://overseerr.local:5055"
KEY = "testoverseerrkey"
MOVIE_ITEM = {"title": "Inception", "media_type": "movie", "tmdb_id": "27205"}
SHOW_ITEM = {"title": "Breaking Bad", "media_type": "show", "tmdb_id": "1396"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resp(status_code: int, json_data=None) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data or {}
    r.raise_for_status = MagicMock()
    return r


def _mock_client(*responses) -> AsyncMock:
    """Retourne un mock client dont les appels successifs retournent les réponses données."""
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    if len(responses) == 1:
        client.get = AsyncMock(return_value=responses[0])
        client.post = AsyncMock(return_value=responses[0])
    else:
        client.get = AsyncMock(side_effect=list(responses))
        client.post = AsyncMock(side_effect=list(responses))
    return client


# ---------------------------------------------------------------------------
# request_media
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_movie_success():
    """Nouvelle demande film → retourne l'ID Overseerr, already_existed=False."""
    post_resp = _resp(201, {"id": 42})

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=post_resp)

    with patch("app.services.overseerr.httpx.AsyncClient", return_value=client):
        req_id, already_existed, slug = await request_media(URL, KEY, MOVIE_ITEM)

    assert req_id == 42
    assert already_existed is False
    assert slug is None


@pytest.mark.asyncio
async def test_request_show_includes_seasons():
    """Demande série → payload contient seasons='all'."""
    post_resp = _resp(201, {"id": 7})

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=post_resp)

    with patch("app.services.overseerr.httpx.AsyncClient", return_value=client):
        await request_media(URL, KEY, SHOW_ITEM)

    call_kwargs = client.post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
    assert payload["seasons"] == "all"
    assert payload["mediaType"] == "tv"


@pytest.mark.asyncio
async def test_request_conflict_already_existed():
    """409 Conflict → demande déjà soumise, already_existed=True."""
    conflict_resp = _resp(409)

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=conflict_resp)

    with patch("app.services.overseerr.httpx.AsyncClient", return_value=client):
        req_id, already_existed, slug = await request_media(URL, KEY, MOVIE_ITEM)

    assert req_id is None
    assert already_existed is True


@pytest.mark.asyncio
async def test_request_no_tmdb_id_search_success():
    """Pas de TMDB ID → recherche par titre → demande créée."""
    item = {"title": "Inception", "media_type": "movie"}

    search_resp = _resp(200, {"results": [{"mediaType": "movie", "id": 27205}]})
    post_resp = _resp(201, {"id": 55})

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=search_resp)
    client.post = AsyncMock(return_value=post_resp)

    with patch("app.services.overseerr.httpx.AsyncClient", return_value=client):
        req_id, already_existed, _ = await request_media(URL, KEY, item)

    assert req_id == 55
    assert already_existed is False


@pytest.mark.asyncio
async def test_request_no_tmdb_id_search_fails():
    """Pas de TMDB ID et recherche échoue → ValueError levée."""
    item = {"title": "Film Introuvable", "media_type": "movie"}

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=Exception("timeout"))

    with patch("app.services.overseerr.httpx.AsyncClient", return_value=client):
        with pytest.raises(ValueError, match="TMDB ID introuvable"):
            await request_media(URL, KEY, item)


@pytest.mark.asyncio
async def test_request_search_no_matching_media_type():
    """Recherche retourne des résultats mais aucun ne correspond au mediaType."""
    item = {"title": "Inception", "media_type": "movie"}

    search_resp = _resp(200, {"results": [{"mediaType": "tv", "id": 1234}]})

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=search_resp)

    with patch("app.services.overseerr.httpx.AsyncClient", return_value=client):
        with pytest.raises(ValueError, match="TMDB ID introuvable"):
            await request_media(URL, KEY, item)


# ---------------------------------------------------------------------------
# is_request_available
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_request_available_status_5():
    """media.status=5 (AVAILABLE) → disponible."""
    resp = _resp(200, {"media": {"status": 5}})
    client = _mock_client(resp)

    with patch("app.services.overseerr.httpx.AsyncClient", return_value=client):
        available, req_id, _ = await is_request_available(URL, KEY, overseerr_request_id=42)

    assert available is True
    assert req_id == 42


@pytest.mark.asyncio
async def test_is_request_available_status_4():
    """media.status=4 (PARTIALLY_AVAILABLE) → disponible."""
    resp = _resp(200, {"media": {"status": 4}})
    client = _mock_client(resp)

    with patch("app.services.overseerr.httpx.AsyncClient", return_value=client):
        available, req_id, _ = await is_request_available(URL, KEY, overseerr_request_id=42)

    assert available is True


@pytest.mark.asyncio
async def test_is_request_available_status_pending():
    """media.status=2 (PENDING) → non disponible."""
    resp = _resp(200, {"media": {"status": 2}})
    client = _mock_client(resp)

    with patch("app.services.overseerr.httpx.AsyncClient", return_value=client):
        available, req_id, _ = await is_request_available(URL, KEY, overseerr_request_id=42)

    assert available is False


@pytest.mark.asyncio
async def test_is_request_available_404():
    """Demande introuvable dans Overseerr → (False, None, None)."""
    resp = _resp(404)

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=resp)

    with patch("app.services.overseerr.httpx.AsyncClient", return_value=client):
        available, req_id, _ = await is_request_available(URL, KEY, overseerr_request_id=999)

    assert available is False
    assert req_id is None


@pytest.mark.asyncio
async def test_is_request_available_network_error():
    """Erreur réseau → (False, None, None) sans lever d'exception."""
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=Exception("timeout"))

    with patch("app.services.overseerr.httpx.AsyncClient", return_value=client):
        available, req_id, _ = await is_request_available(URL, KEY, overseerr_request_id=42)

    assert available is False
    assert req_id is None


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_success():
    resp = _resp(200, {"displayName": "admin", "email": "admin@example.com"})
    client = _mock_client(resp)

    with patch("app.services.overseerr.httpx.AsyncClient", return_value=client):
        success, msg = await check_connection(URL, KEY)

    assert success is True
    assert "admin" in msg


@pytest.mark.asyncio
async def test_connection_failure():
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=Exception("Connection refused"))

    with patch("app.services.overseerr.httpx.AsyncClient", return_value=client):
        success, msg = await check_connection(URL, KEY)

    assert success is False
    assert "Connection refused" in msg
