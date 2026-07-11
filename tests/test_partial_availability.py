from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, MediaRequest, PlexUser, RequestStatus, Settings
from app.scheduler import _handle_show_progress_notification
from app.services.notification_orchestrator import _resolve_series_granularity


def _make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _settings(**kwargs) -> Settings:
    defaults = dict(email_on_available=True, smtp_from="admin@example.com", vff_enabled=False)
    defaults.update(kwargs)
    return Settings(id=1, **defaults)


def _show_request(**kwargs) -> MediaRequest:
    defaults = dict(
        plex_user_id="alice",
        plex_user="alice",
        title="Breaking Bad",
        media_type="show",
        status=RequestStatus.available,
        available_mail_sent=False,
    )
    defaults.update(kwargs)
    return MediaRequest(**defaults)


def test_resolve_granularity_user_override_wins():
    settings = _settings(series_notify_granularity="jalons")
    user = PlexUser(plex_user_id="alice", series_notify_granularity="tout")
    assert _resolve_series_granularity(settings, user) == "tout"


def test_resolve_granularity_falls_back_to_global():
    settings = _settings(series_notify_granularity="minimal")
    user = PlexUser(plex_user_id="alice", series_notify_granularity=None)
    assert _resolve_series_granularity(settings, user) == "minimal"


@pytest.mark.asyncio
async def test_jalons_notifies_once_on_first_partial():
    db = _make_db()
    settings = _settings(series_notify_granularity="jalons")
    db.add(settings)
    req = _show_request(episodes_available_count=2, episodes_aired_count=5, episodes_total_count=10)
    db.add(req)
    db.commit()

    with patch("app.services.notification_orchestrator.enqueue_notification") as mock_enqueue:
        await _handle_show_progress_notification(settings, req, db)

    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args.args[0] == "available"
    assert mock_enqueue.call_args.args[3]["scope"] == "episode"


@pytest.mark.asyncio
async def test_jalons_does_not_repeat_once_flagged():
    db = _make_db()
    settings = _settings(series_notify_granularity="jalons")
    db.add(settings)
    req = _show_request(
        episodes_available_count=3,
        episodes_aired_count=5,
        episodes_total_count=10,
        partial_available_mail_sent=True,
    )
    db.add(req)
    db.commit()

    with patch("app.services.notification_orchestrator.enqueue_notification") as mock_enqueue:
        await _handle_show_progress_notification(settings, req, db)

    mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_tout_notifies_on_each_increase():
    db = _make_db()
    settings = _settings(series_notify_granularity="tout")
    db.add(settings)
    req = _show_request(
        episodes_available_count=3,
        episodes_aired_count=5,
        episodes_total_count=10,
        last_notified_episode_count=2,
    )
    db.add(req)
    db.commit()

    with patch("app.services.notification_orchestrator.enqueue_notification") as mock_enqueue:
        await _handle_show_progress_notification(settings, req, db)

    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args.args[0] == "available"
    assert mock_enqueue.call_args.args[3]["scope"] == "episode"


@pytest.mark.asyncio
async def test_tout_skips_when_count_unchanged():
    db = _make_db()
    settings = _settings(series_notify_granularity="tout")
    db.add(settings)
    req = _show_request(
        episodes_available_count=3,
        episodes_aired_count=5,
        episodes_total_count=10,
        last_notified_episode_count=3,
    )
    db.add(req)
    db.commit()

    with patch("app.services.notification_orchestrator.enqueue_notification") as mock_enqueue:
        await _handle_show_progress_notification(settings, req, db)

    mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_complete_series_sends_available_notification():
    db = _make_db()
    settings = _settings(series_notify_granularity="jalons")
    db.add(settings)
    req = _show_request(episodes_available_count=10, episodes_aired_count=10, episodes_total_count=10)
    db.add(req)
    db.commit()

    with patch("app.services.notification_orchestrator.enqueue_notification") as mock_enqueue:
        await _handle_show_progress_notification(settings, req, db)

    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args.args[0] == "available"
    assert mock_enqueue.call_args.args[3]["scope"] == "series_complete"


@pytest.mark.asyncio
async def test_complete_series_does_not_repeat_once_sent():
    db = _make_db()
    settings = _settings(series_notify_granularity="jalons")
    db.add(settings)
    req = _show_request(
        episodes_available_count=10,
        episodes_aired_count=10,
        episodes_total_count=10,
        available_mail_sent=True,
    )
    db.add(req)
    db.commit()

    with patch("app.services.notification_orchestrator.enqueue_notification") as mock_enqueue:
        await _handle_show_progress_notification(settings, req, db)

    mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_no_episode_data_falls_back_to_classic_available_notification():
    db = _make_db()
    settings = _settings()
    db.add(settings)
    req = _show_request(episodes_available_count=None, episodes_aired_count=None, episodes_total_count=None)
    db.add(req)
    db.commit()

    with patch("app.services.notification_orchestrator.enqueue_notification") as mock_enqueue:
        await _handle_show_progress_notification(settings, req, db)

    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args.args[0] == "available"


@pytest.mark.asyncio
async def test_zero_episodes_available_does_not_notify():
    db = _make_db()
    settings = _settings()
    db.add(settings)
    req = _show_request(episodes_available_count=0, episodes_aired_count=3, episodes_total_count=10)
    db.add(req)
    db.commit()

    with patch("app.services.notification_orchestrator.enqueue_notification") as mock_enqueue:
        await _handle_show_progress_notification(settings, req, db)

    mock_enqueue.assert_not_called()
