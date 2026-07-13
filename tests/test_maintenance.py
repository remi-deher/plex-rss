"""Tests unitaires pour routers/maintenance.py."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import require_admin, require_auth
from app.main import app
from app.models import Settings
from app.routers.maintenance import (
    ACTIONS_META,
    MaintenanceRun,
    _Emit,
    _LogCaptureHandler,
    _new_run,
    _run_check_arr_statuses,
    _run_discover_users,
    _run_recalculate_dates,
    _run_retry_failed,
    _run_seer_sync_requests,
    _run_seer_sync_users,
    _runs,
)
from tests.async_support import make_test_session

# ---------------------------------------------------------------------------
# Fixture : client avec auth bypassé
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_admin] = lambda: None
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(require_admin, None)


# ---------------------------------------------------------------------------
# _new_run
# ---------------------------------------------------------------------------


def test_new_run_returns_unique_id():
    id1, run1 = _new_run("health-check")
    id2, run2 = _new_run("health-check")
    assert id1 != id2
    assert run1 is not run2


def test_new_run_registers_run():
    run_id, run = _new_run("seer-sync-users")
    assert _runs[run_id] is run
    assert run.action == "seer-sync-users"
    assert run.status == "running"
    assert run.progress == 0.0


# ---------------------------------------------------------------------------
# _Emit
# ---------------------------------------------------------------------------


def test_emit_info_appends_prefix():
    run = MaintenanceRun(action="test")
    emit = _Emit(run, logging.getLogger("test"))
    emit.info("hello world")
    assert run.logs == ["[INFO] hello world"]


def test_emit_ok_appends_prefix():
    run = MaintenanceRun(action="test")
    emit = _Emit(run, logging.getLogger("test"))
    emit.ok("done")
    assert run.logs[0] == "[OK] done"


def test_emit_warn_appends_prefix():
    run = MaintenanceRun(action="test")
    emit = _Emit(run, logging.getLogger("test"))
    emit.warn("attention")
    assert run.logs[0] == "[WARN] attention"


def test_emit_err_appends_prefix():
    run = MaintenanceRun(action="test")
    emit = _Emit(run, logging.getLogger("test"))
    emit.err("erreur critique")
    assert run.logs[0] == "[ERR] erreur critique"


def test_emit_multiple_messages():
    run = MaintenanceRun(action="test")
    emit = _Emit(run, logging.getLogger("test"))
    emit.info("step 1")
    emit.ok("step 2")
    assert len(run.logs) == 2


# ---------------------------------------------------------------------------
# _LogCaptureHandler
# ---------------------------------------------------------------------------


def test_log_capture_handler_captures_info():
    run = MaintenanceRun(action="test")
    handler = _LogCaptureHandler(run)
    record = logging.LogRecord("test", logging.INFO, "", 0, "info msg", None, None)
    handler.emit(record)
    assert any("info msg" in log for log in run.logs)


def test_log_capture_handler_captures_warning():
    run = MaintenanceRun(action="test")
    handler = _LogCaptureHandler(run)
    record = logging.LogRecord("test", logging.WARNING, "", 0, "warn msg", None, None)
    handler.emit(record)
    assert any("[WARN]" in log for log in run.logs)


def test_log_capture_handler_captures_error():
    run = MaintenanceRun(action="test")
    handler = _LogCaptureHandler(run)
    record = logging.LogRecord("test", logging.ERROR, "", 0, "err msg", None, None)
    handler.emit(record)
    assert any("[ERR]" in log for log in run.logs)


# ---------------------------------------------------------------------------
# GET /api/maintenance/actions
# ---------------------------------------------------------------------------


def test_list_actions_returns_all_known(client):
    r = client.get("/api/maintenance/actions")
    assert r.status_code == 200
    data = r.json()
    for key in ACTIONS_META:
        assert key in data


def test_list_actions_includes_meta_fields(client):
    r = client.get("/api/maintenance/actions")
    item = r.json()["health-check"]
    assert "label" in item
    assert "description" in item
    assert "icon" in item
    assert "color" in item
    assert "last_run" in item


# ---------------------------------------------------------------------------
# POST /api/maintenance/run/{action}
# ---------------------------------------------------------------------------


def test_start_run_unknown_action_returns_404(client):
    r = client.post("/api/maintenance/run/does-not-exist")
    assert r.status_code == 404


def test_start_run_known_action_returns_run_id(client):
    with patch("app.routers.maintenance._run_seer_sync_users", new_callable=AsyncMock):
        r = client.post("/api/maintenance/run/seer-sync-users")
    assert r.status_code == 200
    data = r.json()
    assert "run_id" in data
    assert isinstance(data["run_id"], str)


def test_start_run_registers_run(client):
    with patch("app.routers.maintenance._run_discover_users", new_callable=AsyncMock):
        r = client.post("/api/maintenance/run/discover-users")
    run_id = r.json()["run_id"]
    assert run_id in _runs


# ---------------------------------------------------------------------------
# GET /api/maintenance/run/{run_id}
# ---------------------------------------------------------------------------


def test_get_run_not_found_returns_404(client):
    r = client.get("/api/maintenance/run/doesnotexist123")
    assert r.status_code == 404


def test_get_run_returns_run_state(client):
    run_id, run = _new_run("health-check")
    run.logs.append("[OK] test log")
    run.progress = 50.0

    r = client.get(f"/api/maintenance/run/{run_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["run_id"] == run_id
    assert data["action"] == "health-check"
    assert data["progress"] == 50.0
    assert "[OK] test log" in data["logs"]


def test_get_run_returns_all_fields(client):
    run_id, _ = _new_run("seer-sync-users")
    r = client.get(f"/api/maintenance/run/{run_id}")
    data = r.json()
    for field in ("run_id", "action", "status", "progress", "logs", "started_at", "finished_at"):
        assert field in data


# ---------------------------------------------------------------------------
# _run_* : tests des exécuteurs individuels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_seer_sync_users_calls_sync():
    # _run_seer_sync_users importe sync_seer_users via "from ..scheduler import sync_seer_users"
    # → on patche à la source, pas dans le module maintenance
    run = MaintenanceRun(action="seer-sync-users")
    with patch("app.scheduler.sync_seer_users", new_callable=AsyncMock):
        await _run_seer_sync_users(run)
    assert run.progress == 100
    assert any("terminée" in log.lower() or "sync" in log.lower() for log in run.logs)


@pytest.mark.asyncio
async def test_run_seer_sync_requests_calls_sync():
    run = MaintenanceRun(action="seer-sync-requests")
    with patch("app.scheduler.sync_seer_requests", new_callable=AsyncMock):
        await _run_seer_sync_requests(run)
    assert run.progress == 100


@pytest.mark.asyncio
async def test_run_discover_users_calls_poll():
    run = MaintenanceRun(action="discover-users")
    with patch("app.scheduler.poll_watchlists", new_callable=AsyncMock):
        await _run_discover_users(run)
    assert run.progress == 100


@pytest.mark.asyncio
async def test_run_recalculate_dates_calls_sync():
    run = MaintenanceRun(action="recalculate-dates")
    with patch("app.scheduler.sync_seer_requests", new_callable=AsyncMock):
        await _run_recalculate_dates(run)
    assert run.progress == 100


@pytest.mark.asyncio
async def test_run_retry_failed_no_failures():
    run = MaintenanceRun(action="retry-failed")
    db = make_test_session()

    with patch("app.routers.maintenance.AsyncSessionLocal", return_value=db):
        await _run_retry_failed(run)

    assert run.progress == 100
    assert any("aucune" in log.lower() for log in run.logs)


@pytest.mark.asyncio
async def test_run_retry_failed_resets_status():
    from app.models import MediaRequest, RequestStatus

    run = MaintenanceRun(action="retry-failed")
    req = MediaRequest(plex_user_id="alice", title="Dune", media_type="movie", status=RequestStatus.failed)
    db = make_test_session()
    db.add(req)
    db.commit()

    with (
        patch("app.routers.maintenance.AsyncSessionLocal", return_value=db),
        patch("app.scheduler.poll_watchlists", new_callable=AsyncMock),
    ):
        await _run_retry_failed(run)

    assert req.status == RequestStatus.pending
    assert run.progress == 100


@pytest.mark.asyncio
async def test_run_check_arr_statuses_no_settings():
    run = MaintenanceRun(action="check-arr-statuses")
    db = make_test_session()

    with patch("app.routers.maintenance.AsyncSessionLocal", return_value=db):
        await _run_check_arr_statuses(run)

    assert any("paramètre" in log.lower() for log in run.logs)


@pytest.mark.asyncio
async def test_run_check_arr_statuses_no_candidates():
    run = MaintenanceRun(action="check-arr-statuses")
    db = make_test_session()
    db.add(Settings())
    db.commit()

    with patch("app.routers.maintenance.AsyncSessionLocal", return_value=db):
        await _run_check_arr_statuses(run)

    assert run.progress == 100
    assert any("aucune" in log.lower() for log in run.logs)
