from unittest.mock import AsyncMock, patch
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import (
    ArrInstance,
    Base,
    MediaRequest,
    SeriesAcquisitionBatch,
    SonarrQueueObservation,
    PlexUser,
    Settings,
)
from app.services.acquisition_batches import advance_acquisition_batches, build_batch_summary
from app.services.sonarr_queue_monitor import classify_queue_record, monitor_sonarr_queue
from app.utils import now_utc_naive


async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _record(**changes):
    record = {
        "queue_id": 10,
        "arr_media_id": 42,
        "download_id": "download-1",
        "title": "Show - S01E01",
        "status": "completed",
        "tracked_state": "importPending",
        "tracked_status": "warning",
        "size": 1000,
        "sizeleft": 0,
        "progress": 100.0,
        "season_number": 1,
        "episode_number": 1,
        "error": "Episode match is required",
        "status_messages": [{"title": "Import blocked", "messages": ["Series match failed"]}],
        "series_seasons": [
            {"season_number": 0, "monitored": True},
            {"season_number": 1, "monitored": True},
            {"season_number": 2, "monitored": False},
            {"season_number": 3, "monitored": True},
        ],
    }
    record.update(changes)
    return record


def test_queue_classification_keeps_active_download_active():
    result = classify_queue_record(_record(status="downloading", progress=55, sizeleft=450, tracked_state="downloading"))
    assert result.state == "downloading"
    assert result.blocked_candidate is False


def test_queue_classification_marks_completed_import_pending_as_candidate():
    result = classify_queue_record(_record())
    assert result.state == "awaiting_import"
    assert result.blocked_candidate is True


@pytest.mark.asyncio
async def test_monitor_confirms_block_on_second_minute_and_resolves_when_missing():
    engine, session_factory = await _database()
    async with session_factory() as db:
        instance = ArrInstance(
            name="Sonarr",
            arr_type="sonarr",
            url="http://sonarr",
            api_key="secret",
            enabled=True,
        )
        db.add(instance)
        await db.flush()
        db.add(MediaRequest(
            plex_user_id="alice",
            title="Show",
            media_type="show",
            source="rss",
            arr_instance_id=instance.id,
            arr_id=42,
        ))
        await db.commit()

    queue = AsyncMock(return_value=[_record()])
    with (
        patch("app.services.sonarr_queue_monitor.AsyncSessionLocal", session_factory),
        patch("app.services.sonarr_queue_monitor.sonarr.get_queue", queue),
    ):
        first = await monitor_sonarr_queue()
        second = await monitor_sonarr_queue()

        async with session_factory() as db:
            observation = (await db.execute(select(SonarrQueueObservation))).scalars().one()
            batch = (await db.execute(select(SeriesAcquisitionBatch))).scalars().one()
            assert first["blocked"] == 0
            assert second["blocked"] == 1
            assert observation.state == "import_blocked"
            assert observation.consecutive_blocked_checks == 2
            assert observation.blocked_at is not None
            assert "Series match failed" in observation.status_messages
            assert batch.expected_scope == "all_seasons"
            assert batch.source == "rss"
            assert batch.expected_seasons == "[1, 2, 3]"

        queue.return_value = []
        resolved = await monitor_sonarr_queue()
        assert resolved["resolved"] == 1

    async with session_factory() as db:
        observation = (await db.execute(select(SonarrQueueObservation))).scalars().one()
        assert observation.state == "resolved"
        assert observation.resolved_at is not None
        assert observation.consecutive_blocked_checks == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_monitor_does_not_resolve_observations_when_sonarr_is_unreachable():
    engine, session_factory = await _database()
    async with session_factory() as db:
        instance = ArrInstance(name="Sonarr", arr_type="sonarr", url="http://sonarr", api_key="secret", enabled=True)
        db.add(instance)
        await db.flush()
        db.add(SonarrQueueObservation(
            arr_instance_id=instance.id,
            queue_id=99,
            state="import_blocked",
            consecutive_blocked_checks=2,
        ))
        await db.commit()

    with (
        patch("app.services.sonarr_queue_monitor.AsyncSessionLocal", session_factory),
        patch(
            "app.services.sonarr_queue_monitor.sonarr.get_queue",
            new=AsyncMock(side_effect=RuntimeError("offline")),
        ),
    ):
        result = await monitor_sonarr_queue()
    assert result["instances"] == 0

    async with session_factory() as db:
        observation = (await db.execute(select(SonarrQueueObservation))).scalars().one()
        assert observation.state == "import_blocked"
        assert observation.resolved_at is None
    await engine.dispose()


def test_batch_summary_combines_vo_vf_and_blocked_imports():
    summary = build_batch_summary(
        [
            {"scope": "season_start", "language": "vf", "season_number": 1},
            {"scope": "season_complete", "language": "vf", "season_number": 2},
            {"scope": "season_start", "language": "vo", "season_number": 3},
        ],
        blocked_count=1,
        expected_seasons=[1, 2, 3, 4],
    )
    assert "2 saison(s) en VF" in summary
    assert "1 saison(s) en VO" in summary
    assert "1 import(s)" in summary
    assert "1 saison(s) encore en attente" in summary


@pytest.mark.asyncio
async def test_stable_batch_queues_one_summary_and_one_deduplicated_admin_alert():
    engine, session_factory = await _database()
    now = now_utc_naive()
    async with session_factory() as db:
        settings = Settings(
            id=1,
            email_enabled=True,
            email_on_available=True,
            email_on_vf_available=True,
            admin_notification_email="admin@example.com",
            smtp_from="fallback@example.com",
        )
        user = PlexUser(
            plex_user_id="alice",
            notification_email="alice@example.com",
            enabled=True,
            notify_vf_series=True,
        )
        instance = ArrInstance(name="Sonarr", arr_type="sonarr", url="http://sonarr", api_key="secret", enabled=True)
        db.add_all([settings, user, instance])
        await db.flush()
        req = MediaRequest(
            plex_user_id="alice",
            title="Show",
            media_type="show",
            source="api",
            arr_instance_id=instance.id,
            arr_id=42,
            vf_category="series",
        )
        db.add(req)
        await db.flush()
        batch = SeriesAcquisitionBatch(
            request_id=req.id,
            arr_instance_id=instance.id,
            arr_id=42,
            source="api",
            expected_scope="all_seasons",
            status="stabilizing",
            opened_at=now - timedelta(minutes=20),
            stabilization_started_at=now - timedelta(minutes=6),
            last_plex_change_at=now - timedelta(minutes=6),
            pending_events='[{"scope":"season_start","language":"vf","is_upgrade":true,"season_number":1,"episode_number":1}]',
        )
        db.add(batch)
        await db.flush()
        blocked = SonarrQueueObservation(
            batch_id=batch.id,
            request_id=req.id,
            arr_instance_id=instance.id,
            queue_id=10,
            title="Show - S02",
            state="import_blocked",
            progress=100,
            consecutive_blocked_checks=2,
            error_message="Season match failed",
            blocked_at=now - timedelta(minutes=5),
        )
        db.add(blocked)
        await db.commit()

        with patch("app.services.acquisition_batches.enqueue", new_callable=AsyncMock) as enqueue_mock:
            result = await advance_acquisition_batches(db, settings, now=now)
            await db.commit()
            second = await advance_acquisition_batches(db, settings, now=now + timedelta(minutes=1))

        assert result == {"stabilizing": 0, "summaries": 1, "admin_alerts": 1, "closed": 1}
        assert second == {"stabilizing": 0, "summaries": 0, "admin_alerts": 0, "closed": 0}
        assert enqueue_mock.await_count == 2
        admin_call, summary_call = enqueue_mock.await_args_list
        assert admin_call.args[0] == "failed"
        assert admin_call.args[2] == ["admin@example.com"]
        assert admin_call.args[3]["admin_only"] is True
        assert summary_call.args[0] == "available"
        assert "1 saison(s) en VF" in summary_call.args[3]["batch_summary"]
        assert "1 import(s)" in summary_call.args[3]["batch_summary"]
        assert batch.status == "closed"
        assert batch.summary_queued_at == now
        assert blocked.admin_alert_queued_at == now
    await engine.dispose()
