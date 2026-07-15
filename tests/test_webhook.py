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
        stack.enter_context(patch("app.routers.webhook.has_plex_proof", new=AsyncMock(return_value=True)))
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
        patch("app.routers.webhook.has_plex_proof", new=AsyncMock(return_value=True)),
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
        patch("app.routers.webhook.has_plex_proof", new=AsyncMock(return_value=True)),
        patch("app.routers.webhook.scan_and_notify_availability", new=AsyncMock(return_value=False)),
        patch("app.routers.webhook.record_completed", new=AsyncMock()),
        patch("app.routers.webhook.resolve_and_notify_availability", new=AsyncMock()) as notify,
    ):
        await _mark_available_and_notify("Dune", "movie", 10, db, _settings())
    notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_available_and_notify_lookup_by_arr_id():
    db = _make_db(requests=[_req(title="X", media_type="show", arr_id=42)])
    with patch("app.routers.webhook.has_plex_proof", new=AsyncMock(return_value=False)):
        count = await _mark_available_and_notify("X", "show", 42, db, _settings())
    assert count == 1


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
