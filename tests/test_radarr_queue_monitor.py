from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import ArrInstance, Base, MediaRequest, RadarrQueueObservation, Settings
from app.services.radarr_queue_monitor import monitor_radarr_queue


async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _record(**changes):
    record = {
        "queue_id": 10,
        "arr_media_id": 42,
        "title": "A Movie",
        "status": "completed",
        "tracked_state": "importPending",
        "tracked_status": "warning",
        "size": 1000,
        "sizeleft": 0,
        "progress": 100.0,
        "error": "Movie match is required",
    }
    record.update(changes)
    return record


@pytest.mark.asyncio
async def test_monitor_confirms_block_on_second_minute_and_sends_admin_alert():
    engine, session_factory = await _database()
    async with session_factory() as db:
        instance = ArrInstance(name="Radarr", arr_type="radarr", url="http://radarr", api_key="secret", enabled=True)
        db.add(instance)
        await db.flush()
        db.add(MediaRequest(
            plex_user_id="alice",
            title="A Movie",
            media_type="movie",
            source="rss",
            arr_instance_id=instance.id,
            arr_id=42,
        ))
        db.add(Settings(admin_notification_email="admin@example.com", notify_import_blocked=True))
        await db.commit()

    queue = AsyncMock(return_value=[_record()])
    with (
        patch("app.services.radarr_queue_monitor.AsyncSessionLocal", session_factory),
        patch("app.services.radarr_queue_monitor.radarr.get_queue", queue),
        patch("app.services.radarr_queue_monitor.enqueue", new_callable=AsyncMock) as enqueue_mock,
    ):
        first = await monitor_radarr_queue()
        second = await monitor_radarr_queue()

    assert first["blocked"] == 0
    assert first["admin_alerts"] == 0
    assert second["blocked"] == 1
    assert second["admin_alerts"] == 1
    enqueue_mock.assert_awaited_once()
    args = enqueue_mock.await_args.args
    assert args[0] == "import_blocked"
    assert args[2] == ["admin@example.com"]
    assert args[3]["admin_only"] is True

    async with session_factory() as db:
        observation = (await db.execute(select(RadarrQueueObservation))).scalars().one()
        assert observation.state == "import_blocked"
        assert observation.consecutive_blocked_checks == 2
        assert observation.admin_alert_queued_at is not None

    # Un second passage bloque ne doit pas redeclencher l'alerte (deduplication).
    with (
        patch("app.services.radarr_queue_monitor.AsyncSessionLocal", session_factory),
        patch("app.services.radarr_queue_monitor.radarr.get_queue", queue),
        patch("app.services.radarr_queue_monitor.enqueue", new_callable=AsyncMock) as enqueue_mock_2,
    ):
        third = await monitor_radarr_queue()
    assert third["admin_alerts"] == 0
    enqueue_mock_2.assert_not_awaited()

    queue.return_value = []
    with (
        patch("app.services.radarr_queue_monitor.AsyncSessionLocal", session_factory),
        patch("app.services.radarr_queue_monitor.radarr.get_queue", queue),
    ):
        resolved = await monitor_radarr_queue()
    assert resolved["resolved"] == 1

    async with session_factory() as db:
        observation = (await db.execute(select(RadarrQueueObservation))).scalars().one()
        assert observation.state == "resolved"
        assert observation.resolved_at is not None
        assert observation.consecutive_blocked_checks == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_monitor_skips_alert_when_toggle_disabled():
    engine, session_factory = await _database()
    async with session_factory() as db:
        instance = ArrInstance(name="Radarr", arr_type="radarr", url="http://radarr", api_key="secret", enabled=True)
        db.add(instance)
        await db.flush()
        db.add(MediaRequest(
            plex_user_id="alice",
            title="A Movie",
            media_type="movie",
            source="rss",
            arr_instance_id=instance.id,
            arr_id=42,
        ))
        db.add(Settings(admin_notification_email="admin@example.com", notify_import_blocked=False))
        await db.commit()

    queue = AsyncMock(return_value=[_record()])
    with (
        patch("app.services.radarr_queue_monitor.AsyncSessionLocal", session_factory),
        patch("app.services.radarr_queue_monitor.radarr.get_queue", queue),
        patch("app.services.radarr_queue_monitor.enqueue", new_callable=AsyncMock) as enqueue_mock,
    ):
        await monitor_radarr_queue()
        second = await monitor_radarr_queue()

    assert second["blocked"] == 1
    assert second["admin_alerts"] == 0
    enqueue_mock.assert_not_awaited()
    await engine.dispose()


@pytest.mark.asyncio
async def test_monitor_does_not_resolve_observations_when_radarr_is_unreachable():
    engine, session_factory = await _database()
    async with session_factory() as db:
        instance = ArrInstance(name="Radarr", arr_type="radarr", url="http://radarr", api_key="secret", enabled=True)
        db.add(instance)
        await db.flush()
        db.add(RadarrQueueObservation(
            arr_instance_id=instance.id,
            queue_id=99,
            state="import_blocked",
            consecutive_blocked_checks=2,
        ))
        await db.commit()

    with (
        patch("app.services.radarr_queue_monitor.AsyncSessionLocal", session_factory),
        patch(
            "app.services.radarr_queue_monitor.radarr.get_queue",
            new=AsyncMock(side_effect=RuntimeError("offline")),
        ),
    ):
        result = await monitor_radarr_queue()
    assert result["instances"] == 0

    async with session_factory() as db:
        observation = (await db.execute(select(RadarrQueueObservation))).scalars().one()
        assert observation.state == "import_blocked"
        assert observation.resolved_at is None
    await engine.dispose()
