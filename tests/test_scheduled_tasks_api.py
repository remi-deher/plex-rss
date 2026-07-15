"""Tests unitaires pour /api/scheduled-tasks."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_db_async as get_db
from app.dependencies import require_admin, require_auth
from app.main import app
from app.models import JobRunLog, Settings


@pytest.fixture()
def db(async_db):
    return async_db


@pytest.fixture()
def client(db):
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides.pop(get_db, None)


def test_list_scheduled_tasks_without_settings(client, db):
    """Sans Settings en base, le catalogue retourne les intervalles par defaut."""
    with patch("app.routers.scheduled_tasks_api._job_states", new=AsyncMock(return_value={})):
        resp = client.get("/api/scheduled-tasks")
    assert resp.status_code == 200
    data = resp.json()
    jobs = {row["job"] for row in data}
    assert "arr-statuses" in jobs
    assert "watchlist" in jobs
    arr_row = next(row for row in data if row["job"] == "arr-statuses")
    assert arr_row["interval_seconds"] == 900  # default : 15 min
    assert arr_row["configurable"] is True
    assert arr_row["settings_field"] == "arr_poll_interval_seconds"
    assert arr_row["state"] is None


def test_list_scheduled_tasks_uses_configured_arr_interval(client, db):
    """L'intervalle configure (arr_poll_interval_seconds) prime sur la valeur par defaut."""
    db.add(Settings(id=1, arr_poll_interval_seconds=2700))
    db.commit()

    with patch("app.routers.scheduled_tasks_api._job_states", new=AsyncMock(return_value={})):
        resp = client.get("/api/scheduled-tasks")
    assert resp.status_code == 200
    arr_row = next(row for row in resp.json() if row["job"] == "arr-statuses")
    assert arr_row["interval_seconds"] == 2700
    assert arr_row["settings_value"] == 2700


def test_list_scheduled_tasks_merges_live_state(client, db):
    fake_state = {"arr-statuses": {"name": "arr-statuses", "status": "complete", "duration_ms": 4230.1}}
    with patch("app.routers.scheduled_tasks_api._job_states", new=AsyncMock(return_value=fake_state)):
        resp = client.get("/api/scheduled-tasks")
    arr_row = next(row for row in resp.json() if row["job"] == "arr-statuses")
    assert arr_row["state"]["status"] == "complete"
    assert arr_row["state"]["duration_ms"] == 4230.1


def test_scheduled_task_history_returns_recent_runs_desc(client, db):
    db.add_all([
        JobRunLog(job="arr-statuses", started_at=datetime(2026, 1, 1, 10, 0, 0), duration_ms=100, status="complete"),
        JobRunLog(job="arr-statuses", started_at=datetime(2026, 1, 1, 10, 15, 0), duration_ms=200, status="failed", error="boom"),
        JobRunLog(job="watchlist", started_at=datetime(2026, 1, 1, 10, 0, 0), duration_ms=50, status="complete"),
    ])
    db.commit()

    resp = client.get("/api/scheduled-tasks/arr-statuses/history")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    assert rows[0]["status"] == "failed"
    assert rows[0]["error"] == "boom"
    assert rows[1]["status"] == "complete"


def test_scheduled_task_history_limit_capped(client, db):
    db.add_all([
        JobRunLog(job="watchlist", started_at=datetime(2026, 1, 1, 10, i, 0), duration_ms=10, status="complete")
        for i in range(5)
    ])
    db.commit()

    resp = client.get("/api/scheduled-tasks/watchlist/history?limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) == 2
