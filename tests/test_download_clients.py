import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.download_clients import (
    add_torrent_to_client,
    check_client_connection,
    delete_torrent,
    get_torrent_status,
)


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
        mock_post.side_effect = [mock_response_login, mock_response_add]

        ok, msg, info_hash = await add_torrent_to_client(
            "qbittorrent", "http://localhost:8080", "user", "pass", "magnet:?xt=urn:btih:abc", "category", "tag1,tag2"
        )
        assert ok is True
        assert "added" in msg or "ajouté" in msg
        assert info_hash == "abc"


@pytest.mark.asyncio
async def test_transmission_connection_success():
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
    mock_response_200.json.return_value = {
        "result": "success",
        "arguments": {"torrent-added": {"hashString": "xyz", "id": 5, "name": "test"}},
    }

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = [mock_response_409, mock_response_200]

        ok, msg, info_hash = await add_torrent_to_client(
            "transmission", "http://localhost:9091", "user", "pass", "magnet:?xt=urn:btih:abc", None, "tag1"
        )
        assert ok is True
        assert "added" in msg or "ajouté" in msg
        assert info_hash == "xyz"


@pytest.mark.asyncio
async def test_watch_folder_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        ok, msg = await check_client_connection("watch_folder", tmpdir, None, None)
        assert ok is True

        mock_content = b"fake torrent content"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = mock_content
        mock_response.headers = {"content-disposition": 'attachment; filename="my_movie.torrent"'}

        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_response)):
            ok, msg, info_hash = await add_torrent_to_client(
                "watch_folder", tmpdir, None, None, "http://prowlarr/download/123"
            )
            assert ok is True
            assert info_hash is not None
            assert os.path.isfile(os.path.join(tmpdir, "my_movie.torrent"))


@pytest.mark.asyncio
async def test_get_torrent_status_qbittorrent():
    mock_response_login = MagicMock()
    mock_response_login.status_code = 200
    mock_response_login.text = "Ok."
    mock_response_login.cookies = {"SID": "test_sid_123"}

    mock_response_info = MagicMock()
    mock_response_info.status_code = 200
    mock_response_info.json.return_value = [
        {
            "name": "My test torrent",
            "progress": 0.455,
            "state": "downloading",
            "ratio": 1.2,
            "seeding_time": 3600,
            "dlspeed": 102400,
            "upspeed": 51200,
            "eta": 300,
        }
    ]

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_response_login)):
        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_response_info)):
            status = await get_torrent_status("qbittorrent", "http://localhost:8080", "user", "pass", "abc")
            assert status is not None
            assert status["name"] == "My test torrent"
            assert status["progress"] == 45.5
            assert status["status"] == "downloading"
            assert status["ratio"] == 1.2


@pytest.mark.asyncio
async def test_delete_torrent_transmission():
    mock_response_409 = MagicMock()
    mock_response_409.status_code = 409
    mock_response_409.headers = {"X-Transmission-Session-Id": "sess_abc"}

    mock_response_200 = MagicMock()
    mock_response_200.status_code = 200
    mock_response_200.json.return_value = {"result": "success"}

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = [mock_response_409, mock_response_200]

        ok = await delete_torrent("transmission", "http://localhost:9091", "user", "pass", "xyz", True)
        assert ok is True
