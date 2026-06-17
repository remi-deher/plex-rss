from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import ArrInstance, DownloadClient
from app.routers.api import require_auth


def _client_with_db(db):
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app, raise_server_exceptions=False)
    return client


def _cleanup():
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(get_db, None)


def test_crud_download_clients():
    client_obj = DownloadClient(
        id=1,
        name="Seedbox",
        client_type="qbittorrent",
        url="http://client",
        username="u",
        password="p",
        category="cat",
        tags="tag",
        is_default=True,
        enabled=True,
    )
    db = MagicMock()
    db.query.return_value.all.return_value = [client_obj]
    db.commit = MagicMock()
    db.refresh = MagicMock()

    client = _client_with_db(db)
    try:
        # List
        resp = client.get("/api/download-clients")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["name"] == "Seedbox"

        # Create
        resp_create = client.post(
            "/api/download-clients",
            json={
                "name": "New Client",
                "client_type": "transmission",
                "url": "http://trans",
                "username": "u",
                "password": "p",
                "category": "cat",
                "tags": "tag",
                "is_default": False,
                "enabled": True,
            },
        )
        assert resp_create.status_code == 200
        assert db.add.called

    finally:
        _cleanup()


@pytest.mark.asyncio
async def test_api_search_prowlarr_cached():
    inst = ArrInstance(id=2, name="Prowlarr", arr_type="prowlarr", url="http://prowlarr", api_key="key")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = inst

    mock_results = [{"title": "Release 1", "seeders": 10, "size": 1000000, "guid": "123", "downloadUrl": "http://dl"}]

    client = _client_with_db(db)
    try:
        with patch("app.services.prowlarr.search", new=AsyncMock(return_value=mock_results)) as mock_search:
            resp = client.get("/api/search?query=Inception&media_type=movie")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["title"] == "Release 1"

            # Second call should use cache (mock_search only called once)
            resp2 = client.get("/api/search?query=Inception&media_type=movie")
            assert resp2.status_code == 200
            assert len(resp2.json()) == 1
            mock_search.assert_called_once()

    finally:
        _cleanup()
