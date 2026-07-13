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
    with patch("app.jobs.publish", new=AsyncMock()):
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
    with patch("app.jobs.publish", new=AsyncMock()):
        result = await jobs._run({"redis": redis}, "sample", work, force=True)
    assert result == {"status": "skipped"}
    work.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_job_keeps_last_error():
    redis = FakeRedis()

    async def failing():
        raise RuntimeError("network down")

    with patch("app.jobs.publish", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="network down"):
            await jobs._run({"redis": redis}, "sample", failing, force=True)
    state = json.loads(redis.values["plexarr:jobs:state:sample"])
    assert state["status"] == "failed"
    assert state["last_error"] == "network down"
