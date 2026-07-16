from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base, MediaRequest, NotificationMilestone, PlexUser, RequestStatus, Settings
from app.services.notification_orchestrator import AvailabilityCandidate, resolve_and_notify_availability


async def _make_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)()


@pytest.mark.asyncio
async def test_resolve_and_notify_availability_sends_one_and_consumes_all_candidates():
    engine, db = await _make_db()
    settings = Settings(id=1, smtp_from="alice@example.com", email_on_available=True)
    user = PlexUser(plex_user_id="alice", enabled=True, notification_email="alice@example.com")
    req = MediaRequest(
        plex_user_id="alice",
        plex_user="Alice",
        title="Show",
        media_type="show",
        status=RequestStatus.available,
    )
    db.add_all([settings, user, req])
    await db.commit()

    with patch("app.services.notification_orchestrator.enqueue", new_callable=AsyncMock) as mock_enqueue:
        sent = await resolve_and_notify_availability(
            settings,
            req,
            db,
            candidates=[
                AvailabilityCandidate(scope="season_complete", season_number=2),
                AvailabilityCandidate(scope="episode", season_number=2, episode_number=5),
            ],
        )

    assert sent is True
    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args.args[0] == "available"
    assert mock_enqueue.call_args.args[3] == {
        "scope": "episode",
        "language": None,
        "is_upgrade": False,
        "season_number": 2,
        "episode_number": 5,
    }

    milestones = (
        await db.execute(select(NotificationMilestone).filter_by(req_id=req.id))
    ).scalars().all()
    assert {(m.milestone_type, m.season_number, m.episode_number) for m in milestones} == {
        ("season_complete", 2, None),
        ("episode", 2, 5),
    }
    assert all(m.language is None and m.is_upgrade is False for m in milestones)
    await db.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_and_notify_availability_skips_when_suppressed():
    """notify_suppressed (vieil item watchlist resurgi dans le flux RSS) doit bloquer
    aussi ce chemin — la majorite des mails "disponible" y transitent, contrairement a
    _notify() qui n'est qu'un chemin secondaire."""
    engine, db = await _make_db()
    settings = Settings(id=1, smtp_from="alice@example.com", email_on_available=True)
    user = PlexUser(plex_user_id="alice", enabled=True, notification_email="alice@example.com")
    req = MediaRequest(
        plex_user_id="alice",
        plex_user="Alice",
        title="Show",
        media_type="show",
        status=RequestStatus.available,
        notify_suppressed=True,
    )
    db.add_all([settings, user, req])
    await db.commit()

    with patch("app.services.notification_orchestrator.enqueue", new_callable=AsyncMock) as mock_enqueue:
        sent = await resolve_and_notify_availability(
            settings,
            req,
            db,
            candidates=[AvailabilityCandidate(scope="season_complete", season_number=2)],
        )

    assert sent is False
    mock_enqueue.assert_not_called()

    milestones = (
        await db.execute(select(NotificationMilestone).filter_by(req_id=req.id))
    ).scalars().all()
    assert milestones == []
    await db.close()
    await engine.dispose()
