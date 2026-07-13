from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app.database import get_db_async
from app.dependencies import require_admin, require_auth
from app.main import app
from app.models import ArrInstance, LibraryItem, MediaRequest, RequestStatus


def _client(db):
    app.dependency_overrides[get_db_async] = lambda: db
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_admin] = lambda: None
    return TestClient(app, raise_server_exceptions=True)


def _cleanup():
    app.dependency_overrides.pop(get_db_async, None)
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(require_admin, None)


def test_spa_library_list_supports_search_and_type(async_db):
    async_db.add_all(
        [
            LibraryItem(title="Dune", media_type="movie", year=2021, has_vf=True),
            LibraryItem(title="Dune Prophecy", media_type="show", year=2024, has_vf=False),
            LibraryItem(title="Arrival", media_type="movie", year=2016),
        ]
    )
    async_db.commit()
    client = _client(async_db)
    try:
        response = client.get("/api/library?query=dune&media_type=movie")
        assert response.status_code == 200
        assert response.json() == [
            {
                "id": 1,
                "title": "Dune",
                "year": 2021,
                "media_type": "movie",
                "poster_url": None,
                "overview": None,
                "has_vf": True,
                "vf_granularity": None,
                "arr_instance_id": None,
                "arr_id": None,
                "added_at": None,
            }
        ]
    finally:
        _cleanup()


def test_spa_notification_feeds_are_async(async_db):
    client = _client(async_db)
    try:
        activity = client.get("/api/activity")
        pending = client.get("/api/notifications/pending")
        assert activity.status_code == 200
        assert activity.json() == []
        assert pending.status_code == 200
        assert pending.json()["items"] == []
    finally:
        _cleanup()


def test_spa_arr_releases_put_english_results_last_and_grab(async_db):
    instance = ArrInstance(
        name="Radarr",
        arr_type="radarr",
        url="http://radarr",
        api_key="secret",
        enabled=True,
        is_default=True,
    )
    request = MediaRequest(
        plex_user_id="alice",
        title="Dune",
        media_type="movie",
        arr_id=42,
        status=RequestStatus.pending,
    )
    async_db.add_all([instance, request])
    async_db.commit()
    client = _client(async_db)
    releases = [
        {"guid": "en", "title": "Dune 2021 ENGLISH", "indexer_id": 1, "seeders": 80},
        {"guid": "vf", "title": "Dune 2021 MULTI VFF", "indexer_id": 2, "seeders": 10},
    ]
    try:
        with patch("app.routers.arr_api.radarr.get_releases", new=AsyncMock(return_value=releases)):
            response = client.get(f"/api/arr/releases?media_type=movie&arr_id=42&instance_id={instance.id}")
        assert response.status_code == 200
        assert [item["guid"] for item in response.json()] == ["vf", "en"]
        assert [item["is_french"] for item in response.json()] == [True, False]

        with patch("app.routers.arr_api.radarr.grab_release", new=AsyncMock(return_value=(True, "ok"))):
            grabbed = client.post(
                "/api/arr/grab",
                json={
                    "media_type": "movie",
                    "guid": "vf",
                    "indexer_id": 2,
                    "instance_id": instance.id,
                    "request_id": request.id,
                },
            )
        assert grabbed.status_code == 200
        assert request.status == RequestStatus.sent_to_arr
    finally:
        _cleanup()
