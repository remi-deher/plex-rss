from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import ArrInstance
from app.dependencies import require_auth


def _client_with_db(db):
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app, raise_server_exceptions=False)
    return client


def _cleanup():
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(get_db, None)


def test_list_arr_instances():
    inst = ArrInstance(id=1, name="Sonarr 1", arr_type="sonarr", url="http://sonarr1", api_key="key")
    db = MagicMock()
    db.query.return_value.all.return_value = [inst]
    client = _client_with_db(db)
    try:
        resp = client.get("/api/arr-instances")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Sonarr 1"
    finally:
        _cleanup()


def test_create_arr_instance():
    db = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    client = _client_with_db(db)
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
        # Vérifie que les autres instances du même type sont passées à is_default = False
        assert db.query.return_value.filter.return_value.update.called
    finally:
        _cleanup()


def test_delete_arr_instance():
    inst = ArrInstance(id=1, name="Sonarr 1", arr_type="sonarr", url="http://sonarr1", api_key="key")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = inst
    client = _client_with_db(db)
    try:
        resp = client.delete("/api/arr-instances/1")
        assert resp.status_code == 200
        assert resp.json() == {"status": "deleted"}
        db.delete.assert_called_once_with(inst)
    finally:
        _cleanup()


@pytest.mark.asyncio
async def test_test_arr_instance_connectivity():
    client = _client_with_db(MagicMock())
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
