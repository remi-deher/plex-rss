"""Tests pour la disponibilité partielle des séries en cours de diffusion.

Une série pouvait passer en statut "available" (donc notifiée comme telle) dès
qu'un seul épisode avait un fichier, même si elle est encore en cours de
diffusion. Ces tests couvrent la décision de notification (milestones vs
every_episode, réglage global vs par utilisateur) et la fréquence de rappel.
"""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, MediaRequest, PlexUser, RequestStatus, Settings
from app.scheduler import _handle_show_progress_notification, _resolve_partial_notify_frequency


def _make_db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _settings(**kwargs) -> Settings:
    defaults = dict(email_on_available=True, smtp_from="admin@example.com")
    defaults.update(kwargs)
    return Settings(id=1, **defaults)


def _show_request(**kwargs) -> MediaRequest:
    defaults = dict(
        plex_user_id="alice", plex_user="alice", title="Breaking Bad", media_type="show",
        status=RequestStatus.available, available_mail_sent=False,
    )
    defaults.update(kwargs)
    return MediaRequest(**defaults)


def test_resolve_frequency_user_override_wins():
    settings = _settings(partial_notify_frequency="milestones")
    user = PlexUser(plex_user_id="alice", partial_notify_frequency="every_episode")
    assert _resolve_partial_notify_frequency(settings, user) == "every_episode"


def test_resolve_frequency_falls_back_to_global():
    settings = _settings(partial_notify_frequency="every_episode")
    user = PlexUser(plex_user_id="alice", partial_notify_frequency=None)
    assert _resolve_partial_notify_frequency(settings, user) == "every_episode"


def test_milestones_notifies_once_on_first_partial():
    db = _make_db()
    settings = _settings(partial_notify_frequency="milestones")
    db.add(settings)
    req = _show_request(episodes_available_count=2, episodes_aired_count=5, episodes_total_count=10)
    db.add(req)
    db.commit()

    with patch("app.scheduler.enqueue_notification") as mock_enqueue:
        _handle_show_progress_notification(settings, req, db)

    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args[0][0] == "partially_available"


def test_milestones_does_not_repeat_once_flagged():
    db = _make_db()
    settings = _settings(partial_notify_frequency="milestones")
    db.add(settings)
    req = _show_request(
        episodes_available_count=3, episodes_aired_count=5, episodes_total_count=10,
        partial_available_mail_sent=True,  # déjà notifié une 1ère fois
    )
    db.add(req)
    db.commit()

    with patch("app.scheduler.enqueue_notification") as mock_enqueue:
        _handle_show_progress_notification(settings, req, db)

    mock_enqueue.assert_not_called()


def test_every_episode_notifies_on_each_increase():
    db = _make_db()
    settings = _settings(partial_notify_frequency="every_episode")
    db.add(settings)
    req = _show_request(
        episodes_available_count=3, episodes_aired_count=5, episodes_total_count=10,
        last_notified_episode_count=2,
    )
    db.add(req)
    db.commit()

    with patch("app.scheduler.enqueue_notification") as mock_enqueue:
        _handle_show_progress_notification(settings, req, db)

    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args[0][0] == "partially_available"


def test_every_episode_skips_when_count_unchanged():
    db = _make_db()
    settings = _settings(partial_notify_frequency="every_episode")
    db.add(settings)
    req = _show_request(
        episodes_available_count=3, episodes_aired_count=5, episodes_total_count=10,
        last_notified_episode_count=3,  # déjà notifié pour ce compte
    )
    db.add(req)
    db.commit()

    with patch("app.scheduler.enqueue_notification") as mock_enqueue:
        _handle_show_progress_notification(settings, req, db)

    mock_enqueue.assert_not_called()


def test_complete_series_sends_available_notification():
    db = _make_db()
    settings = _settings(partial_notify_frequency="milestones")
    db.add(settings)
    req = _show_request(episodes_available_count=10, episodes_aired_count=10, episodes_total_count=10)
    db.add(req)
    db.commit()

    with patch("app.scheduler.enqueue_notification") as mock_enqueue:
        _handle_show_progress_notification(settings, req, db)

    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args[0][0] == "available"


def test_complete_series_does_not_repeat_once_sent():
    db = _make_db()
    settings = _settings(partial_notify_frequency="milestones")
    db.add(settings)
    req = _show_request(
        episodes_available_count=10, episodes_aired_count=10, episodes_total_count=10,
        available_mail_sent=True,
    )
    db.add(req)
    db.commit()

    with patch("app.scheduler.enqueue_notification") as mock_enqueue:
        _handle_show_progress_notification(settings, req, db)

    mock_enqueue.assert_not_called()


def test_no_episode_data_falls_back_to_classic_available_notification():
    """Média sans données de progression (ex: géré par Seer) -> comportement historique."""
    db = _make_db()
    settings = _settings()
    db.add(settings)
    req = _show_request(episodes_available_count=None, episodes_aired_count=None, episodes_total_count=None)
    db.add(req)
    db.commit()

    with patch("app.scheduler.enqueue_notification") as mock_enqueue:
        _handle_show_progress_notification(settings, req, db)

    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args[0][0] == "available"


def test_zero_episodes_available_does_not_notify():
    db = _make_db()
    settings = _settings()
    db.add(settings)
    req = _show_request(episodes_available_count=0, episodes_aired_count=3, episodes_total_count=10)
    db.add(req)
    db.commit()

    with patch("app.scheduler.enqueue_notification") as mock_enqueue:
        _handle_show_progress_notification(settings, req, db)

    mock_enqueue.assert_not_called()
