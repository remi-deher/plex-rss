from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.download_clients import add_torrent_to_client, check_client_connection


@pytest.mark.asyncio
async def test_qbittorrent_connection_success():
    mock_response_login = MagicMock()
    mock_response_login.status_code = 200
    mock_response_login.text = "Ok."
    mock_response_login.cookies = {"SID": "test_sid_123"}

    mock_response_version = MagicMock()
    mock_response_version.status_code = 200
    mock_response_version.text = "4.5.2"

    with (
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_response_login)),
        patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_response_version)),
    ):
        ok, msg = await check_client_connection("qbittorrent", "http://localhost:8080", "user", "pass")
        assert ok is True
        assert "Connecté à qBittorrent v4.5.2" in msg


@pytest.mark.asyncio
async def test_qbittorrent_add_torrent_success():
    mock_response_login = MagicMock()
    mock_response_login.status_code = 200
    mock_response_login.text = "Ok."
    mock_response_login.cookies = {"SID": "test_sid_123"}

    mock_response_add = MagicMock()
    mock_response_add.status_code = 200
    mock_response_add.text = "Ok."

    with patch("httpx.AsyncClient.post") as mock_post:
        # Premier appel login, second appel add
        mock_post.side_effect = [mock_response_login, mock_response_add]

        ok, msg = await add_torrent_to_client(
            "qbittorrent", "http://localhost:8080", "user", "pass", "magnet:?xt=urn:btih:abc", "category", "tag1,tag2"
        )
        assert ok is True
        assert "added" in msg or "ajouté" in msg


@pytest.mark.asyncio
async def test_transmission_connection_success():
    # Simulation d'un code 409 avec entête de session CSRF, puis succès
    mock_response_409 = MagicMock()
    mock_response_409.status_code = 409
    mock_response_409.headers = {"X-Transmission-Session-Id": "sess_abc"}

    mock_response_200 = MagicMock()
    mock_response_200.status_code = 200
    mock_response_200.json.return_value = {"result": "success", "arguments": {"version": "3.00"}}

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = [mock_response_409, mock_response_200]

        ok, msg = await check_client_connection("transmission", "http://localhost:9091", "user", "pass")
        assert ok is True
        assert "Connecté à Transmission v3.00" in msg


@pytest.mark.asyncio
async def test_transmission_add_torrent_success():
    mock_response_409 = MagicMock()
    mock_response_409.status_code = 409
    mock_response_409.headers = {"X-Transmission-Session-Id": "sess_abc"}

    mock_response_200 = MagicMock()
    mock_response_200.status_code = 200
    mock_response_200.json.return_value = {"result": "success"}

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = [mock_response_409, mock_response_200]

        ok, msg = await add_torrent_to_client(
            "transmission", "http://localhost:9091", "user", "pass", "magnet:?xt=urn:btih:abc", None, "tag1"
        )
        assert ok is True
        assert "added" in msg or "ajouté" in msg
