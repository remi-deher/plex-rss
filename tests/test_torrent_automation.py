from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import ArrInstance, Base, DownloadClient, MediaRequest, RequestStatus, Settings
from app.scheduler import check_torrent_statuses, poll_watchlists


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _settings(**kwargs) -> Settings:
    defaults = dict(
        sonarr_enabled=False,  # Disabled to trigger torrent fallback
        radarr_enabled=False,
        torrent_min_size_gb=1.0,
        torrent_max_size_gb=20.0,
        torrent_required_keywords="MULTI",
        torrent_forbidden_keywords="CAM",
        torrent_ratio_limit=2.0,
        torrent_seed_time_limit_hours=24,
        torrent_auto_delete_files=True,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


@pytest.mark.asyncio
async def test_watchlist_torrent_automation_fallback(db):
    # Setup settings and default download client
    settings = _settings()
    db.add(settings)
    client_obj = DownloadClient(
        name="Default Client",
        client_type="qbittorrent",
        url="http://localhost:8080",
        is_default=True,
        enabled=True,
    )
    db.add(client_obj)

    # Setup Prowlarr ArrInstance
    prowlarr_inst = ArrInstance(
        name="Prowlarr",
        arr_type="prowlarr",
        url="http://prowlarr",
        api_key="key",
        enabled=True,
    )
    db.add(prowlarr_inst)
    db.commit()

    client_id = client_obj.id

    watchlist_item = {
        "title": "Inception",
        "year": 2010,
        "media_type": "movie",
        "plex_user_id": "alice",
        "plex_user": "alice",
        "tmdb_id": "27205",
        "source": "api",
    }

    mock_search_results = [
        # Filtered out due to size
        {"title": "Inception 2010 MULTI 1080p", "size": 500 * 1024 * 1024, "seeders": 100, "downloadUrl": "http://dl1"},
        # Filtered out due to keyword
        {
            "title": "Inception 2010 CAM 1080p",
            "size": 5 * 1024 * 1024 * 1024,
            "seeders": 90,
            "downloadUrl": "http://dl2",
        },
        # Matches and has seeders
        {
            "title": "Inception 2010 MULTI 1080p",
            "size": 5 * 1024 * 1024 * 1024,
            "seeders": 50,
            "downloadUrl": "http://dl3",
        },
    ]

    with (
        patch("app.scheduler.SessionLocal", return_value=db),
        patch("app.scheduler.fetch_watchlist", new=AsyncMock(return_value=[watchlist_item])),
        patch("app.services.prowlarr.search", new=AsyncMock(return_value=mock_search_results)),
        patch("app.scheduler.add_torrent_to_client", new=AsyncMock(return_value=(True, "Added", "inception_hash"))),
        patch("app.scheduler._notify") as mock_notify,
    ):
        await poll_watchlists()

        # Check request was created and is sent_to_arr
        req = db.query(MediaRequest).filter(MediaRequest.title == "Inception").first()
        assert req is not None
        assert req.status == RequestStatus.sent_to_arr
        assert req.torrent_hash == "inception_hash"
        assert req.download_client_id == client_id
        assert mock_notify.called


@pytest.mark.asyncio
async def test_check_torrent_statuses_available_and_cleanup(db):
    settings = _settings()
    db.add(settings)
    client_obj = DownloadClient(
        name="Default Client",
        client_type="qbittorrent",
        url="http://localhost:8080",
        is_default=True,
        enabled=True,
    )
    db.add(client_obj)
    db.flush()

    client_id = client_obj.id

    # Request that is active
    req = MediaRequest(
        title="Inception",
        media_type="movie",
        plex_user_id="alice",
        status=RequestStatus.sent_to_arr,
        torrent_hash="inception_hash",
        download_client_id=client_id,
    )
    db.add(req)
    db.commit()

    mock_status = {
        "name": "Inception",
        "progress": 100.0,
        "status": "seeding",
        "ratio": 2.5,  # Exceeds ratio limit (2.0)
        "seeding_time": 3600,
        "download_speed": 0,
        "upload_speed": 0,
        "eta": 0,
    }

    with (
        patch("app.scheduler.SessionLocal", return_value=db),
        patch("app.scheduler.get_torrent_status", new=AsyncMock(return_value=mock_status)),
        patch("app.scheduler.delete_torrent", new=AsyncMock(return_value=True)) as mock_delete,
        patch("app.scheduler._notify") as mock_notify,
    ):
        await check_torrent_statuses()

        # Query using a new session since the previous one was closed by check_torrent_statuses()
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=db.get_bind())
        new_session = Session()
        try:
            req_db = new_session.query(MediaRequest).filter(MediaRequest.title == "Inception").first()
            assert req_db is not None
            # Request should now be available
            assert req_db.status == RequestStatus.available
            # Torrent should be cleaned up (deleted) and hash cleared
            assert req_db.torrent_hash is None
        finally:
            new_session.close()

        mock_delete.assert_called_once_with("qbittorrent", "http://localhost:8080", None, None, "inception_hash", True)
        mock_notify.assert_called_once()
