from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_db_async as get_db
from app.dependencies import require_admin, require_auth
from app.main import app
from app.models import ArrInstance


def _client_with_db(db):
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app, raise_server_exceptions=False)
    return client


def _cleanup():
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides.pop(get_db, None)


def test_list_arr_instances(async_db):
    inst = ArrInstance(id=1, name="Sonarr 1", arr_type="sonarr", url="http://sonarr1", api_key="key")
    async_db.add(inst)
    async_db.commit()
    client = _client_with_db(async_db)
    try:
        resp = client.get("/api/arr-instances")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Sonarr 1"
    finally:
        _cleanup()


def test_create_arr_instance(async_db):
    client = _client_with_db(async_db)
    try:
        resp = client.post(
            "/api/arr-instances",
            json={
                "name": "Sonarr 4K",
                "arr_type": "sonarr",
                "url": "http://sonarr4k",
                "api_key": "apikey",
                "is_default": True,
            },
        )
        assert resp.status_code == 200
        created = async_db.query(ArrInstance).filter(ArrInstance.name == "Sonarr 4K").one()
        assert created.is_default is True
    finally:
        _cleanup()


def test_delete_arr_instance(async_db):
    inst = ArrInstance(id=1, name="Sonarr 1", arr_type="sonarr", url="http://sonarr1", api_key="key")
    async_db.add(inst)
    async_db.commit()
    client = _client_with_db(async_db)
    try:
        resp = client.delete("/api/arr-instances/1")
        assert resp.status_code == 200
        assert resp.json() == {"status": "deleted"}
        assert async_db.query(ArrInstance).filter(ArrInstance.id == 1).first() is None
    finally:
        _cleanup()


@pytest.mark.asyncio
async def test_test_arr_instance_connectivity(async_db):
    client = _client_with_db(async_db)
    try:
        with patch(
            "app.services.sonarr.check_connection", new=AsyncMock(return_value=(True, "Connecté"))
        ) as mock_check:
            resp = client.post(
                "/api/test/arr-instance", json={"arr_type": "sonarr", "url": "http://sonarr", "api_key": "key"}
            )
            assert resp.status_code == 200
            assert resp.json() == {"success": True, "message": "Connecté"}
            mock_check.assert_called_once_with("http://sonarr", "key")
    finally:
        _cleanup()
