import pytest

from app.routers import dashboard_api


@pytest.mark.asyncio
async def test_partial_dashboard_snapshot_only_runs_requested_sections(monkeypatch):
    called = []

    async def counts(_db):
        called.append("counts")
        return {"total": 4}

    async def notifications(_db):
        called.append("notifications")
        return {"items": []}

    async def with_session(call):
        return await call(None)

    monkeypatch.setattr(
        dashboard_api,
        "_snapshot_calls",
        lambda: {"counts": counts, "notifications": notifications},
    )
    monkeypatch.setattr(dashboard_api, "_with_session", with_session)

    payload = await dashboard_api._compute_snapshot({"counts"})

    assert payload == {"errors": [], "counts": {"total": 4}}
    assert called == ["counts"]
