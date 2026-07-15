import json
from unittest.mock import AsyncMock, patch

import pytest

from app import jobs
from app.realtime import _allowed


class FakeRedis:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def exists(self, key):
        return int(key in self.values)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def delete(self, key):
        self.values.pop(key, None)

    async def eval(self, script, key_count, key, token):
        if self.values.get(key) == token:
            await self.delete(key)
            return 1
        return 0


def test_realtime_permission_filtering():
    alice = {"id": 1, "plex_user_id": "alice", "role": "user", "is_owner": False}
    admin = {"id": 2, "plex_user_id": "admin", "role": "admin", "is_owner": True}
    assert _allowed({"user_id": None, "admin_only": False}, alice)
    assert _allowed({"user_id": "alice", "admin_only": False}, alice)
    assert not _allowed({"user_id": "bob", "admin_only": False}, alice)
    assert not _allowed({"user_id": None, "admin_only": True}, alice)
    assert _allowed({"user_id": "bob", "admin_only": True}, admin)


@pytest.mark.asyncio
async def test_worker_job_records_success_and_releases_lock():
    redis = FakeRedis()
    work = AsyncMock(return_value={"changed": 2})
    with patch("app.jobs.publish", new=AsyncMock()), patch("app.jobs._log_job_run", new=AsyncMock()):
        result = await jobs._run({"redis": redis, "job_id": "job-1"}, "sample", work, force=True)
    state = json.loads(redis.values["plexarr:jobs:state:sample"])
    assert result["status"] == "complete"
    assert state["progress"] == 100
    assert "plexarr:jobs:lock:sample" not in redis.values
    work.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_job_deduplicates_concurrent_execution():
    redis = FakeRedis()
    redis.values["plexarr:jobs:lock:sample"] = "another-worker"
    work = AsyncMock()
    with patch("app.jobs.publish", new=AsyncMock()), patch("app.jobs._log_job_run", new=AsyncMock()):
        result = await jobs._run({"redis": redis}, "sample", work, force=True)
    assert result == {"status": "skipped"}
    work.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_job_keeps_last_error():
    redis = FakeRedis()

    async def failing():
        raise RuntimeError("network down")

    with patch("app.jobs.publish", new=AsyncMock()), patch("app.jobs._log_job_run", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="network down"):
            await jobs._run({"redis": redis}, "sample", failing, force=True)
    state = json.loads(redis.values["plexarr:jobs:state:sample"])
    assert state["status"] == "failed"
    assert state["last_error"] == "network down"


@pytest.mark.asyncio
async def test_worker_job_logs_history_on_success():
    redis = FakeRedis()
    work = AsyncMock(return_value={"changed": 1})
    log_mock = AsyncMock()
    with patch("app.jobs.publish", new=AsyncMock()), patch("app.jobs._log_job_run", log_mock):
        await jobs._run({"redis": redis}, "sample", work, force=True)
    log_mock.assert_awaited_once()
    assert log_mock.call_args[0][0] == "sample"
    assert log_mock.call_args[0][3] == "complete"


@pytest.mark.asyncio
async def test_worker_job_logs_history_on_failure():
    redis = FakeRedis()

    async def failing():
        raise RuntimeError("boom")

    log_mock = AsyncMock()
    with patch("app.jobs.publish", new=AsyncMock()), patch("app.jobs._log_job_run", log_mock):
        with pytest.raises(RuntimeError):
            await jobs._run({"redis": redis}, "sample", failing, force=True)
    log_mock.assert_awaited_once()
    assert log_mock.call_args[0][3] == "failed"
    assert log_mock.call_args[0][4] == "boom"


@pytest.mark.asyncio
async def test_worker_job_skips_history_when_log_history_false():
    redis = FakeRedis()
    work = AsyncMock(return_value={"ok": True})
    log_mock = AsyncMock()
    with patch("app.jobs.publish", new=AsyncMock()), patch("app.jobs._log_job_run", log_mock):
        await jobs._run({"redis": redis}, "sample", work, force=True, log_history=False)
    log_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_job_arr_statuses_uses_configured_interval():
    """job_arr_statuses lit settings.arr_poll_interval_seconds plutot que le defaut fige."""
    fake_settings = type("S", (), {"arr_poll_interval_seconds": 2700})()
    with (
        patch("app.jobs._settings", new=AsyncMock(return_value=fake_settings)),
        patch("app.jobs._run", new=AsyncMock(return_value={"status": "not_due"})) as run_mock,
    ):
        await jobs.job_arr_statuses({"redis": FakeRedis()})
    assert run_mock.call_args.kwargs["interval_seconds"] == 2700


@pytest.mark.asyncio
async def test_job_arr_statuses_falls_back_to_default_without_settings():
    with (
        patch("app.jobs._settings", new=AsyncMock(return_value=None)),
        patch("app.jobs._run", new=AsyncMock(return_value={"status": "not_due"})) as run_mock,
    ):
        await jobs.job_arr_statuses({"redis": FakeRedis()})
    assert run_mock.call_args.kwargs["interval_seconds"] == 900
