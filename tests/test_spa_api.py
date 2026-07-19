from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.database import get_db_async
from app.dependencies import require_admin, require_auth
from app.main import app
from app.models import ArrInstance, DownloadClient, LibraryItem, MediaRequest, RequestStatus, Settings
from app.routers import arr_api
from app.services.email_service import DEFAULT_HEADER_BRAND, DEFAULT_REQUEST_TEMPLATE


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
                "custom_name": None,
                "plex_user": None,
                "plex_user_id": None,
            }
        ]
        metrics = client.get("/api/library-metrics")
        assert metrics.status_code == 200
        assert metrics.json()["total"] == 3
        assert metrics.json()["vf"]["complete"] == 1
    finally:
        _cleanup()


def test_spa_library_list_paginates_with_offset(async_db):
    """Regression : /api/library plafonnait a 200 resultats sans offset ni indication de
    troncature, et LibraryView.vue ne paginait jamais -> la majorite d'une grosse
    bibliotheque (ex: 1339 medias en prod) restait invisible dans l'UI alors que
    /api/library-metrics affichait le vrai total, sans lien apparent entre les deux."""
    async_db.add_all(
        [LibraryItem(title=f"Movie {i:02d}", media_type="movie", year=2000 + i) for i in range(5)]
    )
    async_db.commit()
    client = _client(async_db)
    try:
        page1 = client.get("/api/library?limit=2&offset=0").json()
        page2 = client.get("/api/library?limit=2&offset=2").json()
        page3 = client.get("/api/library?limit=2&offset=4").json()
        # Tri par added_at desc puis titre asc, en tie-break sur added_at=None partout ici.
        assert [i["title"] for i in page1] == ["Movie 00", "Movie 01"]
        assert [i["title"] for i in page2] == ["Movie 02", "Movie 03"]
        assert [i["title"] for i in page3] == ["Movie 04"]
        # Aucun doublon ni item manquant entre les pages.
        all_ids = [i["id"] for i in page1 + page2 + page3]
        assert len(all_ids) == len(set(all_ids)) == 5
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


def test_spa_email_templates_resolve_defaults_and_header(async_db):
    async_db.add(Settings(email_header_brand="Mon Plex"))
    async_db.commit()
    client = _client(async_db)
    try:
        response = client.get("/api/email-templates")
        assert response.status_code == 200
        data = response.json()
        assert data["email_request_template"] == DEFAULT_REQUEST_TEMPLATE
        assert data["email_header_brand"] == "Mon Plex"
        assert data["email_header_brand"] != DEFAULT_HEADER_BRAND
        assert data["email_header_subtitle"] == "Notification Plex"
        assert data["email_show_header_subtitle"] is True
        assert data["email_media_layout"] == "left"
        assert data["has_previous_version"] is False
        assert data["email_series_complete_template"]
        assert data["simulation_settings"]["email_enabled"] is True
        assert data["simulation_settings"]["series_notify_granularity"] == "jalons"
    finally:
        _cleanup()


def test_spa_email_preview_supports_series_scenarios(async_db):
    async_db.add(Settings(email_enabled=True, smtp_from="plex@example.com"))
    async_db.commit()
    client = _client(async_db)
    try:
        response = client.post(
            "/api/email-preview",
            json={
                "type": "series_partial",
                "template": "{resume_disponibilite}",
                "subject": "Saisons : {titre}",
                "preview_variant": "default",
            },
        )
        assert response.status_code == 200
        assert "3 saisons completes" in response.text
        assert "Saisons : Breaking Bad" in response.text
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


def test_spa_media_detail_matches_requests_by_title(async_db):
    item = LibraryItem(title="Arrival", media_type="movie", year=2016)
    request = MediaRequest(
        plex_user_id="alice",
        title="Arrival",
        media_type="movie",
        year=2016,
        status=RequestStatus.available,
    )
    async_db.add_all([item, request])
    async_db.commit()
    client = _client(async_db)
    try:
        response = client.get(f"/api/media/detail?library_id={item.id}")
        assert response.status_code == 200
        assert response.json()["requests"][0]["id"] == request.id
    finally:
        _cleanup()


def test_spa_media_detail_exposes_plex_origin_without_request(async_db):
    item = LibraryItem(title="Plex only", media_type="movie", year=2025)
    async_db.add(item)
    async_db.commit()
    client = _client(async_db)
    try:
        response = client.get(f"/api/media/detail?library_id={item.id}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["requests"] == []
        assert payload["media"]["origin_kind"] == "plex"
        assert payload["media"]["operational_status"] == "completed"
        assert payload["media"]["origin_label"] == "Deja present dans Plex"
    finally:
        _cleanup()


def test_spa_media_detail_exposes_last_mail_history(async_db):
    """/api/media/detail expose la dernière notification par événement (demande/dispo),
    avec l'horodatage et si l'envoi était manuel ou automatique — utilisé par la fiche
    détail pour proposer un renvoi de mail et afficher l'historique."""
    from datetime import datetime

    from app.models import NotificationLog

    request = MediaRequest(
        plex_user_id="alice", title="Dune", media_type="movie", year=2021, status=RequestStatus.available,
    )
    async_db.add(request)
    async_db.flush()
    async_db.add_all([
        NotificationLog(
            sent_at=datetime(2026, 1, 1, 10, 0, 0), event="request", channel="email", recipient="a@b.c",
            req_id=request.id, success=True, triggered_by="auto",
        ),
        NotificationLog(
            sent_at=datetime(2026, 1, 2, 10, 0, 0), event="available", channel="email", recipient="a@b.c",
            req_id=request.id, success=True, triggered_by="manual",
        ),
        # Log push (non-email) sur le même req_id : ne doit pas polluer l'historique mail.
        NotificationLog(
            sent_at=datetime(2026, 1, 3, 10, 0, 0), event="available", channel="discord", recipient="webhook",
            req_id=request.id, success=True, triggered_by="auto",
        ),
    ])
    async_db.commit()
    client = _client(async_db)
    try:
        response = client.get(f"/api/media/detail?request_id={request.id}")
        assert response.status_code == 200
        payload = response.json()["requests"][0]
        assert payload["last_request_mail"]["triggered_by"] == "auto"
        assert payload["last_available_mail"]["triggered_by"] == "manual"
        assert payload["last_available_mail"]["success"] is True
    finally:
        _cleanup()


def test_spa_media_detail_exposes_per_requester_notification_status(async_db):
    """Régression : /api/media/detail doit indiquer, PAR PERSONNE (pas juste
    globalement), si le mail demande/disponibilité a été envoyé avec succès — sert à
    l'indicateur "déjà notifié" et à "Rattraper tout le monde" dans MediaDetailDrawer."""
    from datetime import datetime

    from app.models import NotificationLog, PlexUser

    alice = PlexUser(plex_user_id="alice", notification_email="alice@example.com")
    bob = PlexUser(plex_user_id="bob", notification_email="bob@example.com")
    request = MediaRequest(
        plex_user_id="alice",
        title="Dune",
        media_type="movie",
        year=2021,
        status=RequestStatus.available,
        extra_requesters='[{"plex_user_id": "bob", "display_name": "Bob"}]',
    )
    async_db.add_all([alice, bob, request])
    async_db.flush()
    async_db.add_all([
        NotificationLog(
            sent_at=datetime(2026, 1, 1, 10, 0, 0), event="request", channel="email", recipient="alice@example.com",
            req_id=request.id, success=True, triggered_by="auto",
        ),
        NotificationLog(
            sent_at=datetime(2026, 1, 2, 10, 0, 0), event="available", channel="email", recipient="alice@example.com",
            req_id=request.id, success=True, triggered_by="auto",
        ),
        # Envoi echoue pour bob : ne doit pas compter comme "notifie".
        NotificationLog(
            sent_at=datetime(2026, 1, 2, 10, 0, 0), event="request", channel="email", recipient="bob@example.com",
            req_id=request.id, success=False, triggered_by="manual",
        ),
    ])
    async_db.commit()
    client = _client(async_db)
    try:
        response = client.get(f"/api/media/detail?request_id={request.id}")
        assert response.status_code == 200
        notifications = response.json()["requests"][0]["requester_notifications"]
        assert notifications["alice"] == {"request": True, "available": True}
        assert notifications["bob"] == {"request": False, "available": False}
    finally:
        _cleanup()


def test_spa_media_detail_requester_without_email_is_untracked(async_db):
    request = MediaRequest(plex_user_id="ghost", title="Dune", media_type="movie", status=RequestStatus.pending)
    async_db.add(request)
    async_db.commit()
    client = _client(async_db)
    try:
        response = client.get(f"/api/media/detail?request_id={request.id}")
        assert response.status_code == 200
        notifications = response.json()["requests"][0]["requester_notifications"]
        assert notifications["ghost"] == {"request": None, "available": None}
    finally:
        _cleanup()


def test_spa_manual_import_links_existing_request(async_db):
    instance = ArrInstance(name="Radarr", arr_type="radarr", url="http://radarr", api_key="secret", enabled=True)
    async_db.add(instance)
    async_db.flush()
    request = MediaRequest(
        plex_user_id="manual",
        title="Arrival",
        media_type="movie",
        arr_id=10,
        arr_instance_id=instance.id,
        status=RequestStatus.sent_to_arr,
    )
    async_db.add(request)
    async_db.commit()
    client = _client(async_db)
    try:
        response = client.post(
            "/api/downloads/manual-import",
            json={"instance_id": instance.id, "media_type": "movie", "title": "Arrival", "arr_id": 10},
        )
        assert response.status_code == 200
        assert response.json() == {"status": "linked", "request_id": request.id}
    finally:
        _cleanup()


def test_spa_direct_downloads_reads_tracked_requests(async_db):
    client_model = DownloadClient(
        name="qBittorrent",
        client_type="qbittorrent",
        url="http://qbittorrent",
        enabled=True,
    )
    async_db.add(client_model)
    async_db.flush()
    request = MediaRequest(
        plex_user_id="alice",
        title="Arrival",
        media_type="movie",
        status=RequestStatus.sent_to_arr,
        torrent_hash="abc123",
        download_client_id=client_model.id,
    )
    async_db.add(request)
    async_db.commit()
    client = _client(async_db)
    arr_api._direct_cache.update({"data": None, "ts": 0.0})
    try:
        status = {"progress": 42.5, "eta": 600}
        with patch("app.services.download_clients.get_torrent_status", new=AsyncMock(return_value=status)):
            response = client.get("/api/downloads/direct")
        assert response.status_code == 200
        assert response.json()[0]["title"] == "Arrival"
        assert response.json()[0]["progress"] == 42.5
    finally:
        arr_api._direct_cache.update({"data": None, "ts": 0.0})
        _cleanup()


def test_sonarr_episode_targets_are_available_without_download_id(async_db):
    instance = ArrInstance(name="Sonarr", arr_type="sonarr", url="http://sonarr", api_key="secret", enabled=True)
    async_db.add(instance)
    async_db.commit()
    client = _client(async_db)
    episodes = [{"id": 12, "seasonNumber": 2, "episodeNumber": 3, "title": "Episode 3"}]
    try:
        with (
            patch("app.routers.arr_api.sonarr.get_episodes", new=AsyncMock(return_value=episodes)),
            patch("app.routers.arr_api.sonarr.get_manual_import_candidates", new=AsyncMock()) as candidates,
        ):
            response = client.get(
                f"/api/downloads/sonarr-manual-import?instance_id={instance.id}&series_id=42"
            )
        assert response.status_code == 200
        assert response.json() == {"candidates": [], "episodes": episodes}
        candidates.assert_not_awaited()
    finally:
        _cleanup()


def test_media_detail_schedule_is_cached_between_calls(async_db):
    """Deuxieme appel : ne doit pas retaper Sonarr -- c'est le seul appel *arr en
    direct de la fiche detaillee, il ne doit plus bloquer la page a chaque ouverture
    (voir cache.get_or_refresh dans library_api._media_schedule_payload)."""
    from app.cache import cache
    cache._memory.clear()

    instance = ArrInstance(name="Sonarr", arr_type="sonarr", url="http://sonarr", api_key="secret", enabled=True)
    async_db.add(instance)
    async_db.commit()
    async_db.refresh(instance)
    item = LibraryItem(title="Breaking Bad", media_type="show", tvdb_id="81189", arr_instance_id=instance.id, arr_id=42)
    async_db.add(item)
    async_db.commit()
    async_db.refresh(item)

    with patch(
        "app.routers.library_api.sonarr.lookup_series",
        new=AsyncMock(return_value={"id": 42, "firstAired": "2008-01-20T00:00:00Z", "status": "ended"}),
    ) as mock_lookup, patch(
        "app.routers.library_api.sonarr.get_episodes", new=AsyncMock(return_value=[]),
    ):
        client = _client(async_db)
        try:
            first = client.get(f"/api/media/detail?library_id={item.id}")
            second = client.get(f"/api/media/detail?library_id={item.id}")
        finally:
            _cleanup()

    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["timeline"] == second.json()["timeline"]
    assert first.json()["timeline"]["first_aired"] == "2008-01-20T00:00:00Z"
    mock_lookup.assert_awaited_once()
