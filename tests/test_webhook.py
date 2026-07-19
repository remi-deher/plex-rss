"""Tests for the asynchronous Sonarr, Radarr and Plex webhooks."""

import json
from contextlib import ExitStack, contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import MediaRequest, PlexUser, RequestStatus, Settings
from app.routers.webhook import _get_recipients, _mark_available_and_notify
from tests.async_support import make_test_session

client = TestClient(app, raise_server_exceptions=False)


def _settings(smtp_from="noreply@app.com", admin_email=None):
    return Settings(
        smtp_from=smtp_from,
        admin_notification_email=admin_email,
        email_on_available=True,
        vff_enabled=False,
        webhook_secret=None,
    )


def _user(notification_email=None, notify_admin=True):
    return PlexUser(
        plex_user_id="alice",
        notification_email=notification_email,
        notify_admin=notify_admin,
    )


def _req(
    title="Dune",
    media_type="movie",
    arr_id=10,
    status_val=RequestStatus.sent_to_arr,
    plex_user_id="alice",
    available_mail_sent=False,
    **ids,
):
    return MediaRequest(
        title=title,
        media_type=media_type,
        arr_id=arr_id,
        status=status_val,
        plex_user_id=plex_user_id,
        available_mail_sent=available_mail_sent,
        **ids,
    )


def _make_db(settings=None, requests=None, user=None):
    db = make_test_session()
    for obj in [settings, user, *(requests or [])]:
        if obj is not None:
            db.add(obj)
    db.commit()
    return db


@contextmanager
def _db_patch(db):
    # Plex opens a short authentication session before its processing session.
    # Keeping this test session open lets both calls share the in-memory database.
    db.close = AsyncMock()
    with ExitStack() as stack:
        stack.enter_context(patch("app.routers.webhook.AsyncSessionLocal", return_value=db))
        stack.enter_context(patch("app.routers.webhook.should_confirm_available", new=AsyncMock(return_value=True)))
        stack.enter_context(patch("app.routers.webhook.trigger_plex_library_refresh", new=AsyncMock()))
        stack.enter_context(patch("app.routers.webhook.scan_and_notify_availability", new=AsyncMock(return_value=False)))
        stack.enter_context(patch("app.routers.webhook.record_completed", new=AsyncMock()))
        stack.enter_context(patch("app.routers.webhook.resolve_and_notify_availability", new=AsyncMock()))
        yield


def test_get_recipients_uses_user_email():
    assert "user@example.com" in _get_recipients(_user("user@example.com"), _settings())


def test_get_recipients_falls_back_to_smtp_from():
    assert "noreply@app.com" in _get_recipients(None, _settings())


def test_get_recipients_appends_admin():
    recipients = _get_recipients(_user("user@example.com"), _settings(admin_email="admin@example.com"))
    assert "admin@example.com" in recipients


def test_get_recipients_no_duplicate_admin():
    recipients = _get_recipients(_user("admin@example.com"), _settings(admin_email="admin@example.com"))
    assert recipients.count("admin@example.com") == 1


def test_get_recipients_notify_admin_false():
    recipients = _get_recipients(
        _user("user@example.com", notify_admin=False),
        _settings(admin_email="admin@example.com"),
    )
    assert "admin@example.com" not in recipients


def test_get_recipients_no_user_no_settings():
    assert _get_recipients(None, None) == []


@pytest.mark.asyncio
async def test_mark_available_and_notify_marks_request():
    req = _req()
    db = _make_db(requests=[req])
    with (
        patch("app.routers.webhook.should_confirm_available", new=AsyncMock(return_value=True)),
        patch("app.routers.webhook.scan_and_notify_availability", new=AsyncMock(return_value=False)),
        patch("app.routers.webhook.record_completed", new=AsyncMock()),
        patch("app.routers.webhook.resolve_and_notify_availability", new=AsyncMock()) as notify,
    ):
        count = await _mark_available_and_notify("Dune", "movie", 10, db, _settings())
    assert count == 1
    assert req.status == RequestStatus.available
    notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_available_and_notify_no_match():
    assert await _mark_available_and_notify("Unknown", "movie", None, _make_db(), _settings()) == 0


@pytest.mark.asyncio
async def test_mark_available_and_notify_skips_if_already_sent():
    req = _req(available_mail_sent=True)
    db = _make_db(requests=[req])
    with (
        patch("app.routers.webhook.should_confirm_available", new=AsyncMock(return_value=True)),
        patch("app.routers.webhook.scan_and_notify_availability", new=AsyncMock(return_value=False)),
        patch("app.routers.webhook.record_completed", new=AsyncMock()),
        patch("app.routers.webhook.resolve_and_notify_availability", new=AsyncMock()) as notify,
    ):
        await _mark_available_and_notify("Dune", "movie", 10, db, _settings())
    notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_available_and_notify_lookup_by_arr_id():
    db = _make_db(requests=[_req(title="X", media_type="show", arr_id=42)])
    with patch("app.routers.webhook.should_confirm_available", new=AsyncMock(return_value=False)):
        count = await _mark_available_and_notify("X", "show", 42, db, _settings())
    assert count == 1


@pytest.mark.asyncio
async def test_mark_available_and_notify_arr_detected_vf_sets_has_vf_immediately():
    """Signal rapide *arr (mediaInfo.audioLanguages) : has_vf doit passer a True des que
    la demande devient disponible, sans attendre le scan Plex qui suit (toujours execute
    en plus, il fait foi s'il contredit)."""
    req = _req()
    db = _make_db(requests=[req])
    with (
        patch("app.routers.webhook.should_confirm_available", new=AsyncMock(return_value=True)),
        patch("app.routers.webhook.scan_and_notify_availability", new=AsyncMock(return_value=True)) as scan_mock,
        patch("app.routers.webhook.record_completed", new=AsyncMock()),
        patch("app.routers.webhook.resolve_and_notify_availability", new=AsyncMock()),
    ):
        await _mark_available_and_notify("Dune", "movie", 10, db, _settings(), arr_detected_vf=True)
    assert req.has_vf is True
    assert req.vf_checked_at is not None
    scan_mock.assert_awaited_once()  # le scan Plex tourne quand meme, il n'est jamais court-circuite


@pytest.mark.asyncio
async def test_mark_available_and_notify_no_arr_signal_leaves_has_vf_untouched():
    req = _req()
    db = _make_db(requests=[req])
    with (
        patch("app.routers.webhook.should_confirm_available", new=AsyncMock(return_value=True)),
        patch("app.routers.webhook.scan_and_notify_availability", new=AsyncMock(return_value=False)),
        patch("app.routers.webhook.record_completed", new=AsyncMock()),
        patch("app.routers.webhook.resolve_and_notify_availability", new=AsyncMock()),
    ):
        await _mark_available_and_notify("Dune", "movie", 10, db, _settings(), arr_detected_vf=False)
    assert req.has_vf is None


@pytest.mark.asyncio
async def test_mark_available_and_notify_arr_signal_persists_even_without_plex_proof():
    """Meme si Plex n'a pas encore scanne le fichier (has_plex_proof=False, la demande
    reste 'Transmise'), le signal VF *arr ne doit pas etre perdu — voir incident 'Orange'
    (statut reste bloque en attente de Plex, mais on connait deja la VF des l'import)."""
    req = _req()
    db = _make_db(requests=[req])
    with patch("app.routers.webhook.should_confirm_available", new=AsyncMock(return_value=False)):
        await _mark_available_and_notify("Dune", "movie", 10, db, _settings(), arr_detected_vf=True)
    assert req.status == RequestStatus.sent_to_arr
    assert req.has_vf is True


def test_sonarr_webhook_ignored_event():
    db = _make_db(settings=_settings())
    with _db_patch(db):
        response = client.post("/webhook/sonarr", json={"eventType": "Test"})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.parametrize("event", ["Download", "Import"])
def test_sonarr_webhook_media_event(event):
    db = _make_db(settings=_settings())
    with _db_patch(db):
        response = client.post(
            "/webhook/sonarr",
            json={"eventType": event, "series": {"title": "Breaking Bad", "tvdbId": 81189}},
        )
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "matched": 0}


def test_sonarr_webhook_download_with_french_media_info_sets_has_vf():
    """Regression : le payload webhook Sonarr d'un Download inclut deja
    episodeFile.mediaInfo.audioLanguages (ffprobe execute par Sonarr a l'import) — doit
    etre lu et traduit en has_vf=True immediat, sans appel API supplementaire."""
    req = _req(title="Breaking Bad", media_type="show", tvdb_id="81189")
    db = _make_db(settings=_settings(), requests=[req])
    with _db_patch(db):
        response = client.post(
            "/webhook/sonarr",
            json={
                "eventType": "Download",
                "series": {"title": "Breaking Bad", "tvdbId": 81189},
                "episodeFile": {"mediaInfo": {"audioLanguages": ["French", "English"]}},
            },
        )
    assert response.status_code == 200
    assert req.has_vf is True


def test_sonarr_webhook_download_without_french_media_info_leaves_has_vf_untouched():
    req = _req(title="Breaking Bad", media_type="show", tvdb_id="81189")
    db = _make_db(settings=_settings(), requests=[req])
    with _db_patch(db):
        response = client.post(
            "/webhook/sonarr",
            json={
                "eventType": "Download",
                "series": {"title": "Breaking Bad", "tvdbId": 81189},
                "episodeFile": {"mediaInfo": {"audioLanguages": ["English"]}},
            },
        )
    assert response.status_code == 200
    assert req.has_vf is None


def test_sonarr_webhook_delete_event_removes_requests():
    req = _req(title="Lost", media_type="show", arr_id=77, tvdb_id="73739")
    db = _make_db(settings=_settings(), requests=[req])
    with _db_patch(db):
        response = client.post(
            "/webhook/sonarr",
            json={"eventType": "SeriesDelete", "series": {"id": 77, "title": "Lost", "tvdbId": 73739}},
        )
    assert response.status_code == 200
    assert response.json()["deleted"] == 1
    assert db.query(MediaRequest).count() == 0


def test_sonarr_episode_file_delete_recalculates_without_deleting_request():
    req = _req(
        title="Lost",
        media_type="show",
        arr_id=77,
        tvdb_id="73739",
        status_val=RequestStatus.available,
    )
    db = _make_db(settings=_settings(), requests=[req])
    stats = {
        "episode_file_count": 11,
        "episode_count": 12,
        "total_episode_count": 12,
    }
    with (
        _db_patch(db),
        patch(
            "app.routers.webhook._resolve_arr_connection",
            new=AsyncMock(return_value=("http://sonarr", "key", "sonarr:legacy")),
        ),
        patch("app.routers.webhook.sonarr.get_series_episode_stats", new=AsyncMock(return_value=stats)),
    ):
        response = client.post(
            "/webhook/sonarr",
            json={"eventType": "EpisodeFileDelete", "series": {"id": 77, "title": "Lost", "tvdbId": 73739}},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "reconciled": 1, "deleted": 0}
    assert db.query(MediaRequest).count() == 1
    assert req.status == RequestStatus.partially_available
    assert req.episodes_available_count == 11


def test_radarr_webhook_ignored_event():
    db = _make_db(settings=_settings())
    with _db_patch(db):
        response = client.post("/webhook/radarr", json={"eventType": "Grab"})
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


@pytest.mark.parametrize("event", ["Download", "MovieAdded"])
def test_radarr_webhook_media_event(event):
    db = _make_db(settings=_settings())
    with _db_patch(db):
        response = client.post(
            "/webhook/radarr",
            json={"eventType": event, "movie": {"title": "Dune", "tmdbId": 438631}},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_radarr_webhook_download_with_french_media_info_sets_has_vf():
    req = _req(title="Dune", tmdb_id="438631")
    db = _make_db(settings=_settings(), requests=[req])
    with _db_patch(db):
        response = client.post(
            "/webhook/radarr",
            json={
                "eventType": "Download",
                "movie": {"title": "Dune", "tmdbId": 438631},
                "movieFile": {"mediaInfo": {"audioLanguages": "French/English"}},
            },
        )
    assert response.status_code == 200
    assert req.has_vf is True


def test_radarr_webhook_delete_event_removes_requests():
    req = _req(arr_id=12, tmdb_id="438631")
    db = _make_db(settings=_settings(), requests=[req])
    with _db_patch(db):
        response = client.post(
            "/webhook/radarr",
            json={"eventType": "MovieDelete", "movie": {"id": 12, "title": "Dune", "tmdbId": 438631}},
        )
    assert response.status_code == 200
    assert response.json()["deleted"] == 1
    assert db.query(MediaRequest).count() == 0


def _post_plex(db, payload=None, *, direct=False):
    with _db_patch(db):
        if direct:
            return client.post("/webhook/plex", json=payload)
        data = {} if payload is None else {"payload": json.dumps(payload)}
        return client.post("/webhook/plex", data=data)


def test_plex_webhook_empty_payload_ignored():
    response = _post_plex(_make_db(settings=_settings()))
    assert response.status_code == 200
    assert response.json()["status"] in ("ignored", "error")


def test_plex_webhook_ignored_event():
    payload = {"event": "media.play", "Metadata": {"type": "movie"}}
    response = _post_plex(_make_db(settings=_settings()), payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_plex_webhook_library_new_movie():
    payload = {
        "event": "library.new",
        "Metadata": {"type": "movie", "title": "Dune", "Guid": [{"id": "tmdb://438631"}]},
    }
    response = _post_plex(_make_db(settings=_settings()), payload)
    assert response.status_code == 200
    assert response.json()["title"] == "Dune"


def test_plex_webhook_episode_uses_show_title():
    payload = {
        "event": "library.new",
        "Metadata": {
            "type": "episode",
            "title": "Pilot",
            "grandparentTitle": "Breaking Bad",
            "Guid": [{"id": "tvdb://81189"}],
        },
    }
    response = _post_plex(_make_db(settings=_settings()), payload)
    assert response.status_code == 200
    assert response.json()["title"] == "Breaking Bad"


def test_plex_webhook_library_new_marks_available_with_naive_datetime():
    """Régression : `available_at` doit être un datetime naïf (comme la colonne
    Postgres `TIMESTAMP WITHOUT TIME ZONE`). Un `now_utc()` (aware) faisait planter
    ce webhook en production avec asyncpg ("can't subtract offset-naive and
    offset-aware datetimes"), silencieusement côté SQLite des tests (qui n'a pas ce
    typage strict) — d'où l'assertion explicite sur `tzinfo` plutôt qu'un simple
    contrôle de statut HTTP.
    """
    req = _req(tmdb_id="438631", status_val=RequestStatus.sent_to_arr)
    db = _make_db(settings=_settings(), requests=[req])
    payload = {
        "event": "library.new",
        "Metadata": {"type": "movie", "title": "Dune", "Guid": [{"id": "tmdb://438631"}]},
    }
    response = _post_plex(db, payload)
    assert response.status_code == 200

    updated = db.query(MediaRequest).filter(MediaRequest.tmdb_id == "438631").first()
    assert updated.status == RequestStatus.available
    assert updated.available_at is not None
    assert updated.available_at.tzinfo is None


def test_plex_webhook_unsupported_media_type():
    payload = {"event": "library.new", "Metadata": {"type": "track", "title": "A song"}}
    response = _post_plex(_make_db(settings=_settings()), payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_plex_webhook_json_direct_fallback():
    payload = {"event": "library.new", "Metadata": {"type": "movie", "title": "Interstellar", "Guid": []}}
    response = _post_plex(_make_db(settings=_settings()), payload, direct=True)
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# POST /webhook/configure/{service} — auto-configuration du connecteur Sonarr/Radarr
# ---------------------------------------------------------------------------

from app.dependencies import require_admin
from app.models import ArrInstance


def _arr_instance(arr_type="sonarr"):
    return ArrInstance(name=arr_type.capitalize(), arr_type=arr_type, url="http://arr.local", api_key="key123")


@contextmanager
def _configure_db_patch(db):
    db.close = AsyncMock()
    with ExitStack() as stack:
        stack.enter_context(patch("app.routers.webhook.AsyncSessionLocal", return_value=db))
        stack.enter_context(patch.dict(app.dependency_overrides, {require_admin: lambda: None}))
        yield


def test_configure_webhook_invalid_service():
    with patch.dict(app.dependency_overrides, {require_admin: lambda: None}):
        response = client.post("/webhook/configure/plex", json={"webhook_url": "https://app.local/webhook/plex"})
    assert response.status_code == 400


def test_configure_webhook_no_instance_configured():
    db = _make_db()
    with _configure_db_patch(db):
        response = client.post("/webhook/configure/sonarr", json={"webhook_url": "https://app.local/webhook/sonarr"})
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["success"] is False
    assert "Aucune instance" in result["message"]


def test_configure_webhook_fixes_existing_connector_missing_events():
    """Régression : le connecteur webhook réel avait 'On Download' désactivé, ce qui
    empêchait toute notification lors d'un import automatique classique (voir incident
    'Orange' — statut resté bloqué sur Transmise pendant 18 minutes). L'auto-config doit
    détecter ce connecteur existant et corriger les événements manquants en place."""
    db = _make_db(requests=[_arr_instance("sonarr")])
    existing = {
        "id": 6,
        "name": "RSS",
        "implementation": "Webhook",
        "onDownload": False,
        "onUpgrade": True,
        "onImportComplete": True,
        "fields": [{"name": "url", "value": "https://app.local/webhook/sonarr?secret=old"}],
    }
    with (
        _configure_db_patch(db),
        patch("app.services.sonarr.get_notifications", new=AsyncMock(return_value=[existing])),
        patch("app.services.sonarr.update_notification", new=AsyncMock(return_value=existing)) as update_mock,
        patch("app.services.sonarr.create_notification", new=AsyncMock()) as create_mock,
    ):
        response = client.post("/webhook/configure/sonarr", json={"webhook_url": "https://app.local/webhook/sonarr?secret=new"})
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["success"] is True
    assert "corrigé" in result["message"]
    update_mock.assert_awaited_once()
    create_mock.assert_not_awaited()
    updated_payload = update_mock.call_args[0][2]
    assert updated_payload["onDownload"] is True


def test_configure_webhook_already_correct_skips_update():
    db = _make_db(requests=[_arr_instance("sonarr")])
    existing = {
        "id": 6,
        "name": "RSS",
        "implementation": "Webhook",
        "onGrab": False,
        "onDownload": True,
        "onUpgrade": True,
        "onImportComplete": True,
        "onRename": False,
        "onSeriesAdd": False,
        "onSeriesDelete": True,
        "onEpisodeFileDelete": True,
        "onEpisodeFileDeleteForUpgrade": False,
        "onHealthIssue": False,
        "onApplicationUpdate": False,
        "fields": [{"name": "url", "value": "https://app.local/webhook/sonarr?secret=new"}],
    }
    with (
        _configure_db_patch(db),
        patch("app.services.sonarr.get_notifications", new=AsyncMock(return_value=[existing])),
        patch("app.services.sonarr.update_notification", new=AsyncMock()) as update_mock,
    ):
        response = client.post("/webhook/configure/sonarr", json={"webhook_url": "https://app.local/webhook/sonarr?secret=new"})
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["success"] is True
    assert "correctement configuré" in result["message"]
    update_mock.assert_not_awaited()


def test_configure_webhook_radarr_ignores_unsupported_import_complete_field():
    """Régression : Radarr n'expose pas "On Import Complete" (contrairement à Sonarr) —
    son API renvoie systématiquement `onImportComplete: None` quoi qu'on écrive, ce qui
    faisait boucler l'auto-config sur "corrigé" à chaque clic (None != True en
    permanence) alors que le connecteur était déjà correctement configuré."""
    db = _make_db(requests=[_arr_instance("radarr")])
    existing = {
        "id": 4,
        "name": "RSS",
        "implementation": "Webhook",
        "onGrab": False,
        "onDownload": True,
        "onUpgrade": True,
        "onImportComplete": None,  # jamais supporté par Radarr, doit être ignoré
        "onRename": False,
        "onMovieAdded": False,
        "onMovieDelete": True,
        "onMovieFileDelete": True,
        "onMovieFileDeleteForUpgrade": False,
        "onHealthIssue": False,
        "onApplicationUpdate": False,
        "fields": [{"name": "url", "value": "https://app.local/webhook/radarr?secret=new"}],
    }
    with (
        _configure_db_patch(db),
        patch("app.services.radarr.get_notifications", new=AsyncMock(return_value=[existing])),
        patch("app.services.radarr.update_notification", new=AsyncMock()) as update_mock,
    ):
        response = client.post("/webhook/configure/radarr", json={"webhook_url": "https://app.local/webhook/radarr?secret=new"})
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["success"] is True
    assert "correctement configuré" in result["message"]
    update_mock.assert_not_awaited()


def test_configure_webhook_creates_new_connector_when_missing():
    db = _make_db(requests=[_arr_instance("radarr")])
    schema = {"implementation": "Webhook", "fields": [{"name": "url", "value": ""}, {"name": "method", "value": 0}]}
    with (
        _configure_db_patch(db),
        patch("app.services.radarr.get_notifications", new=AsyncMock(return_value=[])),
        patch("app.services.radarr.get_webhook_schema", new=AsyncMock(return_value=schema)),
        patch("app.services.radarr.create_notification", new=AsyncMock(return_value={"id": 9})) as create_mock,
    ):
        response = client.post("/webhook/configure/radarr", json={"webhook_url": "https://app.local/webhook/radarr?secret=new"})
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["success"] is True
    assert "créé" in result["message"]
    create_mock.assert_awaited_once()
    created_payload = create_mock.call_args[0][2]
    assert created_payload["onDownload"] is True
    assert any(f["name"] == "url" and f["value"] == "https://app.local/webhook/radarr?secret=new" for f in created_payload["fields"])
