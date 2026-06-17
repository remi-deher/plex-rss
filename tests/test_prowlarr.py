from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import ArrInstance
from app.routers.api import require_auth
from app.services.prowlarr import check_connection, get_indexers, search


def _client_with_db(db):
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app, raise_server_exceptions=False)
    return client


def _cleanup():
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_prowlarr_check_connection():
    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_response)) as mock_get:
        ok = await check_connection("http://prowlarr", "api_key")
        assert ok is True
        mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_prowlarr_get_indexers():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [{"id": 1, "name": "TorrentIndexer"}]

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_response)):
        res = await get_indexers("http://prowlarr", "api_key")
        assert len(res) == 1
        assert res[0]["name"] == "TorrentIndexer"


@pytest.mark.asyncio
async def test_prowlarr_search():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [{"title": "Inception"}]

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_response)):
        res = await search("http://prowlarr", "api_key", "Inception", "movie")
        assert len(res) == 1
        assert res[0]["title"] == "Inception"


def test_api_prowlarr_indexers():
    inst = ArrInstance(id=2, name="Prowlarr", arr_type="prowlarr", url="http://prowlarr", api_key="key")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = inst
    client = _client_with_db(db)

    try:
        with patch("app.services.prowlarr.get_indexers", new=AsyncMock(return_value=[{"id": 1, "name": "Indexer 1"}])):
            resp = client.get("/api/prowlarr/indexers?instance_id=2")
            assert resp.status_code == 200
            assert resp.json() == [{"id": 1, "name": "Indexer 1"}]
    finally:
        _cleanup()
