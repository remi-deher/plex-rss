"""Tests pour la granularité VF (vf_granularity) sur MediaRequest/LibraryItem.

Une série non-complète en VF (has_vf=False) peut avoir 0 épisode VF, quelques
épisodes VF épars ("episode_partial"), ou une saison entière en VF sans que la
série le soit ("season_partial"). Ces tests vérifient que check_vf_statuses
persiste bien ce champ, pour piloter les badges "VF Épisode Partiel" /
"VF Saison Partiel" sans requête supplémentaire à l'affichage.
"""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, LibraryItem, MediaRequest, NotificationMilestone, PlexUser, RequestStatus, Settings
from app.scheduler import check_vf_statuses


def _make_db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


@pytest.mark.asyncio
async def test_check_vf_statuses_sets_episode_partial_granularity():
    db = _make_db()
    settings = Settings(
        id=1, plex_url="http://plex", plex_token="tok", vff_enabled=True,
        vff_libraries='[{"name": "Séries", "kind": "series"}]',
    )
    db.add(settings)
    li = LibraryItem(title="Show", year=2020, media_type="show", plex_guid="plex://show/abc")
    db.add(li)
    db.commit()
    li_id = li.id

    scan_result = {
        "id": li_id, "found": True, "has_vf": False, "category": "series",
        "episode_status": {1: {1: True, 2: False}, 2: {1: False}},
    }
    with (
        patch("app.scheduler.SessionLocal", return_value=db),
        patch("app.scheduler.enqueue_notification"),
        patch("app.scheduler._scan_vf_blocking", return_value=[scan_result]),
    ):
        await check_vf_statuses()

    li_fresh = db.query(LibraryItem).filter(LibraryItem.id == li_id).first()
    assert li_fresh.has_vf is False
    assert li_fresh.vf_granularity == "episode_partial"


@pytest.mark.asyncio
async def test_check_vf_statuses_sets_season_partial_granularity():
    db = _make_db()
    settings = Settings(
        id=1, plex_url="http://plex", plex_token="tok", vff_enabled=True,
        vff_libraries='[{"name": "Séries", "kind": "series"}]',
    )
    db.add(settings)
    li = LibraryItem(title="Show", year=2020, media_type="show", plex_guid="plex://show/abc")
    db.add(li)
    db.commit()
    li_id = li.id

    scan_result = {
        "id": li_id, "found": True, "has_vf": False, "category": "series",
        "episode_status": {1: {1: True, 2: True}, 2: {1: False, 2: False}},
    }
    with (
        patch("app.scheduler.SessionLocal", return_value=db),
        patch("app.scheduler.enqueue_notification"),
        patch("app.scheduler._scan_vf_blocking", return_value=[scan_result]),
    ):
        await check_vf_statuses()

    li_fresh = db.query(LibraryItem).filter(LibraryItem.id == li_id).first()
    assert li_fresh.has_vf is False
    assert li_fresh.vf_granularity == "season_partial"


@pytest.mark.asyncio
async def test_check_vf_statuses_sets_full_granularity_on_complete_show():
    db = _make_db()
    settings = Settings(
        id=1, plex_url="http://plex", plex_token="tok", vff_enabled=True,
        vff_libraries='[{"name": "Séries", "kind": "series"}]',
        email_on_vf_available=True,
    )
    db.add(settings)
    req = MediaRequest(
        plex_user_id="alice", title="Show", year=2020, media_type="show",
        plex_guid="plex://show/abc", status=RequestStatus.available, has_vf=False,
    )
    db.add(req)
    db.commit()
    req_id = req.id

    scan_result = {
        "id": req_id, "found": True, "has_vf": True, "category": "series",
        "episode_status": {1: {1: True, 2: True}},
    }
    with (
        patch("app.scheduler.SessionLocal", return_value=db),
        patch("app.scheduler.enqueue_notification"),
        patch("app.scheduler._scan_vf_blocking", return_value=[scan_result]),
    ):
        await check_vf_statuses()

    req_fresh = db.query(MediaRequest).filter(MediaRequest.id == req_id).first()
    assert req_fresh.has_vf is True
    assert req_fresh.vf_granularity == "full"


@pytest.mark.asyncio
async def test_linked_request_shares_single_scan_with_library_item():
    """Une demande liée à un LibraryItem encore suivi (has_vf=False) partage le même
    scan Plex que la bibliothèque : un seul appel _scan_vf_blocking, pas de scan
    dédié pour la demande — et elle reprend la granularité fraîchement calculée."""
    db = _make_db()
    settings = Settings(
        id=1, plex_url="http://plex", plex_token="tok", vff_enabled=True,
        vff_libraries='[{"name": "Séries", "kind": "series"}]',
    )
    db.add(settings)
    li = LibraryItem(title="Show", year=2020, media_type="show", plex_guid="plex://show/abc", has_vf=False)
    db.add(li)
    db.commit()
    li_id = li.id

    req = MediaRequest(
        plex_user_id="alice", title="Show", year=2020, media_type="show",
        plex_guid="plex://show/abc", status=RequestStatus.available,
        has_vf=False, library_item_id=li_id,
    )
    db.add(req)
    db.commit()
    req_id = req.id

    scan_result = {
        "id": li_id, "found": True, "has_vf": False, "category": "series",
        "episode_status": {1: {1: True, 2: True}, 2: {1: False}},
    }
    with (
        patch("app.scheduler.SessionLocal", return_value=db),
        patch("app.scheduler.enqueue_notification"),
        patch("app.scheduler._scan_vf_blocking", return_value=[scan_result]) as mock_scan,
    ):
        await check_vf_statuses()

    assert mock_scan.call_count == 1  # un seul scan Plex, partagé entre li et req
    li_fresh = db.query(LibraryItem).filter(LibraryItem.id == li_id).first()
    req_fresh = db.query(MediaRequest).filter(MediaRequest.id == req_id).first()
    assert li_fresh.vf_granularity == "season_partial"
    assert req_fresh.vf_granularity == "season_partial"


@pytest.mark.asyncio
async def test_check_vf_statuses_notifies_vf_season_start_once_for_partial_upgrade():
    db = _make_db()
    settings = Settings(
        id=1,
        plex_url="http://plex",
        plex_token="tok",
        smtp_from="admin@example.com",
        vff_enabled=True,
        vff_libraries='[{"name": "Series", "kind": "series"}]',
        email_on_vf_available=True,
        series_vf_notify_mode="season_start_and_complete",
    )
    db.add(settings)
    db.add(PlexUser(plex_user_id="alice", notification_email="alice@example.com", enabled=True))
    req = MediaRequest(
        plex_user_id="alice",
        title="Show",
        year=2020,
        media_type="show",
        plex_guid="plex://show/abc",
        status=RequestStatus.available,
        has_vf=False,
    )
    db.add(req)
    db.commit()
    req_id = req.id

    scan_result = {
        "id": req_id,
        "found": True,
        "has_vf": False,
        "category": "series",
        "episode_status": {1: {1: True, 2: False}},
    }
    with (
        patch("app.scheduler.SessionLocal", return_value=db),
        patch("app.scheduler.enqueue_notification") as mock_enqueue,
        patch("app.scheduler._scan_vf_blocking", return_value=[scan_result]),
    ):
        await check_vf_statuses()
        await check_vf_statuses()

    assert mock_enqueue.call_count == 1
    assert mock_enqueue.call_args.args[:3] == ("vf_available", req_id, ["alice@example.com"])
    assert "VF saison 1 demarree" in mock_enqueue.call_args.args[3]
    milestones = db.query(NotificationMilestone).filter_by(req_id=req_id).all()
    assert len(milestones) == 1
    assert milestones[0].direction == "vf"
    assert milestones[0].milestone_type == "season_start"
    assert milestones[0].season_number == 1
    assert milestones[0].episode_number == 1


@pytest.mark.asyncio
async def test_linked_request_notifies_vf_milestone_from_library_episode_cache():
    db = _make_db()
    settings = Settings(
        id=1,
        plex_url="http://plex",
        plex_token="tok",
        smtp_from="admin@example.com",
        vff_enabled=True,
        vff_libraries='[{"name": "Series", "kind": "series"}]',
        email_on_vf_available=True,
        series_vf_notify_mode="season_start_and_complete",
    )
    db.add(settings)
    db.add(PlexUser(plex_user_id="alice", notification_email="alice@example.com", enabled=True))
    li = LibraryItem(title="Show", year=2020, media_type="show", plex_guid="plex://show/abc", has_vf=False)
    db.add(li)
    db.commit()
    li_id = li.id
    req = MediaRequest(
        plex_user_id="alice",
        title="Show",
        year=2020,
        media_type="show",
        plex_guid="plex://show/abc",
        status=RequestStatus.available,
        has_vf=False,
        library_item_id=li_id,
    )
    db.add(req)
    db.commit()
    req_id = req.id

    scan_result = {
        "id": li_id,
        "found": True,
        "has_vf": False,
        "category": "series",
        "episode_status": {1: {1: True, 2: False}},
    }
    with (
        patch("app.scheduler.SessionLocal", return_value=db),
        patch("app.scheduler.enqueue_notification") as mock_enqueue,
        patch("app.scheduler._scan_vf_blocking", return_value=[scan_result]),
    ):
        await check_vf_statuses()

    assert mock_enqueue.call_count == 1
    assert mock_enqueue.call_args.args[:3] == ("vf_available", req_id, ["alice@example.com"])
    assert mock_enqueue.call_args.args[3] == "VF saison 1 demarree"
    milestone = db.query(NotificationMilestone).filter_by(req_id=req_id).one()
    assert milestone.direction == "vf"
    assert milestone.milestone_type == "season_start"


@pytest.mark.asyncio
async def test_check_vf_statuses_notifies_vo_every_episode_on_first_detection():
    db = _make_db()
    settings = Settings(
        id=1,
        plex_url="http://plex",
        plex_token="tok",
        smtp_from="admin@example.com",
        vff_enabled=True,
        vff_libraries='[{"name": "Series", "kind": "series"}]',
        series_vo_notify_mode="every_episode",
    )
    db.add(settings)
    db.add(PlexUser(plex_user_id="alice", notification_email="alice@example.com", enabled=True))
    req = MediaRequest(
        plex_user_id="alice",
        title="Show",
        year=2020,
        media_type="show",
        plex_guid="plex://show/abc",
        status=RequestStatus.available,
        has_vf=None,
    )
    db.add(req)
    db.commit()
    req_id = req.id

    scan_result = {
        "id": req_id,
        "found": True,
        "has_vf": False,
        "category": "series",
        "episode_status": {1: {1: False, 2: False}},
    }
    with (
        patch("app.scheduler.SessionLocal", return_value=db),
        patch("app.scheduler.enqueue_notification") as mock_enqueue,
        patch("app.scheduler._scan_vf_blocking", return_value=[scan_result]),
    ):
        await check_vf_statuses()

    assert mock_enqueue.call_count == 2
    assert [call.args[0] for call in mock_enqueue.call_args_list] == ["vo_only", "vo_only"]
    assert [call.args[3] for call in mock_enqueue.call_args_list] == ["VO S01E01", "VO S01E02"]
    milestones = db.query(NotificationMilestone).filter_by(req_id=req_id, direction="vo").all()
    assert len(milestones) == 2


@pytest.mark.asyncio
async def test_movie_first_vo_detection_uses_single_available_vo_tracking_event():
    db = _make_db()
    settings = Settings(
        id=1,
        plex_url="http://plex",
        plex_token="tok",
        smtp_from="admin@example.com",
        vff_enabled=True,
        vff_libraries='[{"name": "Films", "kind": "movie"}]',
    )
    db.add(settings)
    db.add(PlexUser(plex_user_id="alice", notification_email="alice@example.com", enabled=True))
    req = MediaRequest(
        plex_user_id="alice",
        title="Movie",
        year=2020,
        media_type="movie",
        plex_guid="plex://movie/abc",
        status=RequestStatus.available,
        has_vf=None,
    )
    db.add(req)
    db.commit()
    req_id = req.id

    scan_result = {"id": req_id, "found": True, "has_vf": False, "category": "movie"}
    with (
        patch("app.scheduler.SessionLocal", return_value=db),
        patch("app.scheduler.enqueue_notification") as mock_enqueue,
        patch("app.scheduler._scan_vf_blocking", return_value=[scan_result]),
    ):
        await check_vf_statuses()

    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args.args[:3] == ("available_vo_tracking", req_id, ["alice@example.com"])
