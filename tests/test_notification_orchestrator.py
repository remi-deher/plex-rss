from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import ArrInstance, Base, MediaRequest, NotificationMilestone, PendingNotification, PlexUser, RequestSeasonStatus, RequestStatus, SeriesAcquisitionBatch, Settings
from app.services.notification_orchestrator import (
    AvailabilityCandidate,
    _handle_show_progress_notification,
    _notify,
    _resolve_requester_users,
    notify_single_user,
    resolve_and_notify_availability,
)


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
async def test_open_acquisition_batch_accumulates_candidates_without_immediate_email():
    engine, db = await _make_db()
    settings = Settings(id=1, smtp_from="alice@example.com", email_on_available=True, email_on_vf_available=True)
    user = PlexUser(plex_user_id="alice", enabled=True, notification_email="alice@example.com")
    instance = ArrInstance(name="Sonarr", arr_type="sonarr", url="http://sonarr", api_key="secret", enabled=True)
    db.add_all([settings, user, instance])
    await db.flush()
    req = MediaRequest(
        plex_user_id="alice",
        title="Show",
        media_type="show",
        status=RequestStatus.available,
        source="rss",
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
        source="rss",
        expected_scope="all_seasons",
        status="open",
    )
    db.add(batch)
    await db.commit()

    with patch("app.services.notification_orchestrator.enqueue", new_callable=AsyncMock) as immediate_enqueue:
        accepted = await resolve_and_notify_availability(
            settings,
            req,
            db,
            candidates=[
                AvailabilityCandidate(
                    scope="season_start",
                    language="vf",
                    is_upgrade=True,
                    season_number=1,
                    episode_number=1,
                ),
                AvailabilityCandidate(
                    scope="season_start",
                    language="vo",
                    is_upgrade=False,
                    season_number=2,
                    episode_number=1,
                ),
            ],
        )

    assert accepted is True
    immediate_enqueue.assert_not_awaited()
    await db.refresh(batch)
    assert '"language": "vf"' in batch.pending_events
    assert '"language": "vo"' in batch.pending_events
    assert batch.last_plex_change_at is not None
    milestones = (await db.execute(select(NotificationMilestone).filter_by(req_id=req.id))).scalars().all()
    assert len(milestones) == 2
    await db.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_complete_season_wins_over_start_when_detected_in_same_scan():
    engine, db = await _make_db()
    settings = Settings(id=1, smtp_from="alice@example.com", email_on_available=True)
    user = PlexUser(plex_user_id="alice", enabled=True, notification_email="alice@example.com")
    req = MediaRequest(plex_user_id="alice", title="Show", media_type="show", status=RequestStatus.available)
    db.add_all([settings, user, req])
    await db.commit()

    with patch("app.services.notification_orchestrator.enqueue", new_callable=AsyncMock) as enqueue_mock:
        await resolve_and_notify_availability(
            settings,
            req,
            db,
            candidates=[
                AvailabilityCandidate(scope="season_start", season_number=1, episode_number=1),
                AvailabilityCandidate(scope="season_complete", season_number=1),
            ],
        )

    enqueue_mock.assert_awaited_once()
    assert enqueue_mock.call_args.args[3]["scope"] == "season_complete"
    assert enqueue_mock.call_args.args[3]["season_number"] == 1
    await db.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_milestone_and_pending_notification_are_committed_together():
    engine, db = await _make_db()
    settings = Settings(id=1, smtp_from="alice@example.com", email_on_available=True)
    user = PlexUser(plex_user_id="alice", enabled=True, notification_email="alice@example.com")
    req = MediaRequest(
        plex_user_id="alice", title="Movie", media_type="movie", status=RequestStatus.available,
    )
    db.add_all([settings, user, req])
    await db.commit()

    with patch("app.notification_queue.schedule_pending_notification", new_callable=AsyncMock) as schedule:
        sent = await resolve_and_notify_availability(
            settings, req, db, candidates=[AvailabilityCandidate(scope="movie")]
        )

    assert sent is True
    assert len((await db.execute(select(NotificationMilestone))).scalars().all()) == 1
    assert len((await db.execute(select(PendingNotification))).scalars().all()) == 1
    schedule.assert_awaited_once()
    await db.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_pending_persistence_failure_rolls_back_milestone():
    engine, db = await _make_db()
    settings = Settings(id=1, smtp_from="alice@example.com", email_on_available=True)
    user = PlexUser(plex_user_id="alice", enabled=True, notification_email="alice@example.com")
    req = MediaRequest(
        plex_user_id="alice", title="Movie", media_type="movie", status=RequestStatus.available,
    )
    db.add_all([settings, user, req])
    await db.commit()

    with patch(
        "app.notification_queue.persist_pending_notification",
        new=AsyncMock(side_effect=RuntimeError("database unavailable")),
    ):
        with pytest.raises(RuntimeError, match="database unavailable"):
            await resolve_and_notify_availability(
                settings, req, db, candidates=[AvailabilityCandidate(scope="movie")]
            )

    assert (await db.execute(select(NotificationMilestone))).scalars().all() == []
    assert (await db.execute(select(PendingNotification))).scalars().all() == []
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


# ---------------------------------------------------------------------------
# Co-demandeurs (extra_requesters) : résolution + inclusion dans les notifications
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_requester_users_includes_primary_and_extras():
    engine, db = await _make_db()
    primary = PlexUser(plex_user_id="alice", enabled=True, notification_email="alice@example.com")
    extra = PlexUser(plex_user_id="bob", enabled=True, notification_email="bob@example.com")
    req = MediaRequest(
        plex_user_id="alice",
        plex_user="Alice",
        title="Dune",
        media_type="movie",
        status=RequestStatus.sent_to_arr,
        extra_requesters='[{"plex_user_id": "bob", "display_name": "Bob"}]',
    )
    db.add_all([primary, extra, req])
    await db.commit()

    users = await _resolve_requester_users(req, db)
    assert [u.plex_user_id for u in users] == ["alice", "bob"]
    await db.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_requester_users_dedupes_and_skips_unknown():
    """Un co-demandeur dupliqué ou dont le PlexUser n'existe plus (compte supprimé) ne
    doit ni planter, ni apparaître deux fois."""
    engine, db = await _make_db()
    primary = PlexUser(plex_user_id="alice", enabled=True, notification_email="alice@example.com")
    req = MediaRequest(
        plex_user_id="alice",
        plex_user="Alice",
        title="Dune",
        media_type="movie",
        status=RequestStatus.sent_to_arr,
        extra_requesters='[{"plex_user_id": "alice", "display_name": "Alice"}, {"plex_user_id": "ghost", "display_name": "Ghost"}]',
    )
    db.add_all([primary, req])
    await db.commit()

    users = await _resolve_requester_users(req, db)
    assert [u.plex_user_id for u in users] == ["alice"]
    await db.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_and_notify_availability_notifies_co_requester():
    """Régression : un co-demandeur ajouté à une demande doit recevoir les futures
    notifications de disponibilité, pas seulement le demandeur principal."""
    engine, db = await _make_db()
    settings = Settings(id=1, smtp_from="fallback@example.com", email_on_available=True)
    primary = PlexUser(plex_user_id="alice", enabled=True, notification_email="alice@example.com")
    extra = PlexUser(plex_user_id="bob", enabled=True, notification_email="bob@example.com")
    req = MediaRequest(
        plex_user_id="alice",
        plex_user="Alice",
        title="Dune",
        media_type="movie",
        status=RequestStatus.available,
        extra_requesters='[{"plex_user_id": "bob", "display_name": "Bob"}]',
    )
    db.add_all([settings, primary, extra, req])
    await db.commit()

    with patch("app.services.notification_orchestrator.enqueue", new_callable=AsyncMock) as mock_enqueue:
        sent = await resolve_and_notify_availability(
            settings, req, db, candidates=[AvailabilityCandidate(scope="movie")]
        )

    assert sent is True
    recipients = mock_enqueue.call_args.args[2]
    assert "alice@example.com" in recipients
    assert "bob@example.com" in recipients
    await db.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_notify_request_event_includes_co_requester():
    engine, db = await _make_db()
    settings = Settings(id=1, smtp_from="fallback@example.com", email_on_request=True)
    primary = PlexUser(plex_user_id="alice", enabled=True, notification_email="alice@example.com")
    extra = PlexUser(plex_user_id="bob", enabled=True, notification_email="bob@example.com")
    req = MediaRequest(
        plex_user_id="alice",
        plex_user="Alice",
        title="Dune",
        media_type="movie",
        status=RequestStatus.pending,
        extra_requesters='[{"plex_user_id": "bob", "display_name": "Bob"}]',
    )
    db.add_all([settings, primary, extra, req])
    await db.commit()

    with patch("app.services.notification_orchestrator.enqueue", new_callable=AsyncMock) as mock_enqueue:
        await _notify("request", settings, req, db)

    recipients = mock_enqueue.call_args.args[2]
    assert "alice@example.com" in recipients
    assert "bob@example.com" in recipients
    await db.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_notify_single_user_targets_only_that_user():
    """Régression : le renvoi rétroactif à un co-demandeur fraîchement ajouté ne doit
    contenir QUE son adresse, jamais celle du demandeur principal ni des autres."""
    engine, db = await _make_db()
    settings = Settings(id=1, smtp_from="fallback@example.com", email_on_request=True, email_on_available=True)
    primary = PlexUser(plex_user_id="alice", enabled=True, notification_email="alice@example.com")
    extra = PlexUser(plex_user_id="bob", enabled=True, notification_email="bob@example.com")
    req = MediaRequest(
        plex_user_id="alice",
        plex_user="Alice",
        title="Dune",
        media_type="movie",
        status=RequestStatus.available,
        request_mail_sent=True,
        available_mail_sent=True,
        extra_requesters='[{"plex_user_id": "bob", "display_name": "Bob"}]',
    )
    db.add_all([settings, primary, extra, req])
    await db.commit()

    with patch("app.services.notification_orchestrator.enqueue", new_callable=AsyncMock) as mock_enqueue:
        queued_request = await notify_single_user("request", settings, req, db, "bob")
        queued_available = await notify_single_user("available", settings, req, db, "bob")

    assert queued_request is True
    assert queued_available is True
    assert mock_enqueue.call_count == 2
    for call in mock_enqueue.call_args_list:
        assert call.args[2] == ["bob@example.com"]
    await db.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_notify_single_user_unknown_plex_user_returns_false():
    engine, db = await _make_db()
    settings = Settings(id=1, email_on_request=True)
    req = MediaRequest(plex_user_id="alice", plex_user="Alice", title="Dune", media_type="movie", status=RequestStatus.pending)
    db.add_all([settings, req])
    await db.commit()

    with patch("app.services.notification_orchestrator.enqueue", new_callable=AsyncMock) as mock_enqueue:
        result = await notify_single_user("request", settings, req, db, "ghost")

    assert result is False
    mock_enqueue.assert_not_called()
    await db.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_handle_show_progress_notification_fires_season_milestones():
    """VFF desactive, granularite 'jalons' : un jalon par saison (season_complete pour
    une saison finie, season_start pour une saison entamee), pas un seul jalon generique
    "episode" pour la serie entiere -- regression du detail par saison (RequestSeasonStatus)."""
    engine, db = await _make_db()
    settings = Settings(
        id=1, smtp_from="alice@example.com", email_on_available=True,
        vff_enabled=False, series_notify_granularity="jalons",
    )
    user = PlexUser(plex_user_id="alice", enabled=True, notification_email="alice@example.com")
    req = MediaRequest(
        plex_user_id="alice", plex_user="Alice", title="Breaking Bad", media_type="show",
        status=RequestStatus.partially_available, episodes_available_count=6, episodes_total_count=13,
    )
    db.add_all([settings, user, req])
    await db.commit()
    db.add_all([
        RequestSeasonStatus(request_id=req.id, season_number=1, episodes_available_count=6, episodes_total_count=6, status="available"),
        RequestSeasonStatus(request_id=req.id, season_number=2, episodes_available_count=0, episodes_total_count=7, status="pending"),
    ])
    await db.commit()

    with patch("app.services.notification_orchestrator.enqueue", new_callable=AsyncMock) as mock_enqueue:
        await _handle_show_progress_notification(settings, req, db)

    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args.args[3]["scope"] == "season_complete"
    assert mock_enqueue.call_args.args[3]["season_number"] == 1

    milestones = (await db.execute(select(NotificationMilestone).filter_by(req_id=req.id))).scalars().all()
    assert {(m.milestone_type, m.season_number) for m in milestones} == {("season_complete", 1)}
    await db.close()
    await engine.dispose()
