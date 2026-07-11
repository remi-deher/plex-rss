from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, MediaRequest, NotificationMilestone, PlexUser, RequestStatus, Settings
from app.services.notification_orchestrator import AvailabilityCandidate, resolve_and_notify_availability


def _make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_resolve_and_notify_availability_sends_one_and_consumes_all_candidates():
    db = _make_db()
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
    db.commit()

    with patch("app.services.notification_orchestrator.enqueue_notification") as mock_enqueue:
        sent = resolve_and_notify_availability(
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

    milestones = db.query(NotificationMilestone).filter_by(req_id=req.id).all()
    assert {(m.milestone_type, m.season_number, m.episode_number) for m in milestones} == {
        ("season_complete", 2, None),
        ("episode", 2, 5),
    }
    assert all(m.language is None and m.is_upgrade is False for m in milestones)

