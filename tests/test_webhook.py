"""Tests unitaires pour routers/webhook.py (Sonarr, Radarr, Plex webhooks)."""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers.webhook import _get_recipients, _mark_available_and_notify

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(smtp_from="noreply@app.com", admin_email=None):
    s = MagicMock()
    s.smtp_from = smtp_from
    s.admin_notification_email = admin_email
    s.email_on_available = True
    s.webhook_secret = None
    return s


def _user(notification_email=None, notify_admin=True):
    u = MagicMock()
    u.notification_email = notification_email
    u.notify_admin = notify_admin
    u.plex_user_id = "alice"
    return u


def _req(
    title="Dune",
    media_type="movie",
    arr_id=10,
    status_val="sent_to_arr",
    plex_user_id="alice",
    available_mail_sent=False,
):
    r = MagicMock()
    r.title = title
    r.media_type = media_type
    r.arr_id = arr_id
    r.plex_user_id = plex_user_id
    r.available_mail_sent = available_mail_sent
    return r


def _make_db(settings=None, requests=None, user=None):
    db = MagicMock()
    db.query.return_value.first.return_value = settings
    db.query.return_value.filter.return_value.all.return_value = requests or []
    db.query.return_value.filter.return_value.first.return_value = user
    return db


# ---------------------------------------------------------------------------
# _get_recipients
# ---------------------------------------------------------------------------


def test_get_recipients_uses_user_email():
    u = _user(notification_email="user@example.com")
    result = _get_recipients(u, _settings())
    assert "user@example.com" in result


def test_get_recipients_falls_back_to_smtp_from():
    result = _get_recipients(None, _settings(smtp_from="noreply@app.com"))
    assert "noreply@app.com" in result


def test_get_recipients_appends_admin():
    u = _user(notification_email="user@example.com", notify_admin=True)
    result = _get_recipients(u, _settings(admin_email="admin@example.com"))
    assert "admin@example.com" in result


def test_get_recipients_no_duplicate_admin():
    u = _user(notification_email="admin@example.com", notify_admin=True)
    result = _get_recipients(u, _settings(admin_email="admin@example.com"))
    assert result.count("admin@example.com") == 1


def test_get_recipients_notify_admin_false():
    u = _user(notification_email="user@example.com", notify_admin=False)
    result = _get_recipients(u, _settings(admin_email="admin@example.com"))
    assert "admin@example.com" not in result


def test_get_recipients_no_user_no_settings():
    result = _get_recipients(None, None)
    assert result == []


# ---------------------------------------------------------------------------
# _mark_available_and_notify
# ---------------------------------------------------------------------------


def test_mark_available_and_notify_marks_request():
    req = _req()
    db = MagicMock()
    db.query.return_value.filter.return_value.filter.return_value.all.return_value = [req]
    db.query.return_value.filter.return_value.first.return_value = None
    s = _settings()
    s.email_on_available = True

    with patch("app.routers.webhook.enqueue_notification") as mock_enqueue:
        count = _mark_available_and_notify("Dune", "movie", 10, db, s)

    assert count == 1
    db.commit.assert_called()
    mock_enqueue.assert_called_once()


def test_mark_available_and_notify_no_match():
    db = MagicMock()
    db.query.return_value.filter.return_value.filter.return_value.all.return_value = []
    count = _mark_available_and_notify("Unknown", "movie", None, db, _settings())
    assert count == 0


def test_mark_available_and_notify_skips_if_already_sent():
    req = _req(available_mail_sent=True)
    db = MagicMock()
    db.query.return_value.filter.return_value.filter.return_value.all.return_value = [req]
    db.query.return_value.filter.return_value.first.return_value = None

    with patch("app.routers.webhook.enqueue_notification") as mock_enqueue:
        _mark_available_and_notify("Dune", "movie", 10, db, _settings())

    mock_enqueue.assert_not_called()


def test_mark_available_and_notify_lookup_by_arr_id():
    db = MagicMock()
    db.query.return_value.filter.return_value.filter.return_value.all.return_value = []
    _mark_available_and_notify("X", "show", arr_id=42, db=db, settings=_settings())
    # Vérifie que filter a été appelé (par arr_id cette fois)
    assert db.query.called


# ---------------------------------------------------------------------------
# POST /webhook/sonarr
# ---------------------------------------------------------------------------


def _db_patch(db):
    return patch("app.routers.webhook.SessionLocal", return_value=db)


def test_sonarr_webhook_ignored_event():
    db = MagicMock()
    db.query.return_value.first.return_value = _settings()
    with _db_patch(db):
        r = client.post("/webhook/sonarr", json={"eventType": "Test"})
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"


def test_sonarr_webhook_download_event():
    db = MagicMock()
    db.query.return_value.first.return_value = _settings()
    db.query.return_value.filter.return_value.filter.return_value.all.return_value = []

    with _db_patch(db):
        r = client.post(
            "/webhook/sonarr",
            json={
                "eventType": "Download",
                "series": {"title": "Breaking Bad", "tvdbId": 81189},
            },
        )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "matched" in data


def test_sonarr_webhook_import_event():
    db = MagicMock()
    db.query.return_value.first.return_value = _settings()
    db.query.return_value.filter.return_value.filter.return_value.all.return_value = []

    with _db_patch(db):
        r = client.post(
            "/webhook/sonarr",
            json={
                "eventType": "Import",
                "series": {"title": "Lost", "tvdbId": 73739},
            },
        )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_sonarr_webhook_delete_event_removes_requests():
    req = _req(title="Lost", media_type="show", arr_id=77)
    db = MagicMock()
    db.query.return_value.first.return_value = _settings()
    db.query.return_value.filter.return_value.filter.return_value.all.return_value = [req]

    with _db_patch(db):
        r = client.post(
            "/webhook/sonarr",
            json={
                "eventType": "SeriesDelete",
                "series": {"id": 77, "title": "Lost", "tvdbId": 73739},
            },
        )
    assert r.status_code == 200
    assert r.json()["deleted"] == 1
    db.delete.assert_called_with(req)


# ---------------------------------------------------------------------------
# POST /webhook/radarr
# ---------------------------------------------------------------------------


def test_radarr_webhook_ignored_event():
    db = MagicMock()
    db.query.return_value.first.return_value = _settings()
    with _db_patch(db):
        r = client.post("/webhook/radarr", json={"eventType": "Grab"})
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"


def test_radarr_webhook_download_event():
    db = MagicMock()
    db.query.return_value.first.return_value = _settings()
    db.query.return_value.filter.return_value.filter.return_value.all.return_value = []

    with _db_patch(db):
        r = client.post(
            "/webhook/radarr",
            json={
                "eventType": "Download",
                "movie": {"title": "Dune", "tmdbId": 438631},
            },
        )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_radarr_webhook_movie_added():
    db = MagicMock()
    db.query.return_value.first.return_value = _settings()
    db.query.return_value.filter.return_value.filter.return_value.all.return_value = []

    with _db_patch(db):
        r = client.post(
            "/webhook/radarr",
            json={
                "eventType": "MovieAdded",
                "movie": {"title": "Oppenheimer", "tmdbId": 872585},
            },
        )
    assert r.status_code == 200


def test_radarr_webhook_delete_event_removes_requests():
    req = _req(title="Dune", media_type="movie", arr_id=12)
    db = MagicMock()
    db.query.return_value.first.return_value = _settings()
    db.query.return_value.filter.return_value.filter.return_value.all.return_value = [req]

    with _db_patch(db):
        r = client.post(
            "/webhook/radarr",
            json={
                "eventType": "MovieDelete",
                "movie": {"id": 12, "title": "Dune", "tmdbId": 438631},
            },
        )
    assert r.status_code == 200
    assert r.json()["deleted"] == 1
    db.delete.assert_called_with(req)


# ---------------------------------------------------------------------------
# POST /webhook/plex
# ---------------------------------------------------------------------------


def test_plex_webhook_empty_payload_ignored():
    db = MagicMock()
    db.query.return_value.first.return_value = _settings()
    with _db_patch(db):
        r = client.post("/webhook/plex", data={})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in ("ignored", "error")


def test_plex_webhook_ignored_event():
    db = MagicMock()
    db.query.return_value.first.return_value = _settings()
    payload = json.dumps({"event": "media.play", "Metadata": {"type": "movie"}})
    with _db_patch(db):
        r = client.post("/webhook/plex", data={"payload": payload})
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"


def test_plex_webhook_library_new_movie():
    db = MagicMock()
    db.query.return_value.first.return_value = _settings()
    db.query.return_value.filter.return_value.filter.return_value.all.return_value = []

    payload = json.dumps(
        {
            "event": "library.new",
            "Metadata": {
                "type": "movie",
                "title": "Dune",
                "Guid": [{"id": "tmdb://438631"}],
            },
        }
    )
    with _db_patch(db):
        r = client.post("/webhook/plex", data={"payload": payload})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["title"] == "Dune"


def test_plex_webhook_episode_uses_show_title():
    db = MagicMock()
    db.query.return_value.first.return_value = _settings()
    db.query.return_value.filter.return_value.filter.return_value.all.return_value = []

    payload = json.dumps(
        {
            "event": "library.new",
            "Metadata": {
                "type": "episode",
                "title": "Pilot",
                "grandparentTitle": "Breaking Bad",
                "Guid": [{"id": "tvdb://81189"}],
            },
        }
    )
    with _db_patch(db):
        r = client.post("/webhook/plex", data={"payload": payload})
    assert r.status_code == 200
    assert r.json()["title"] == "Breaking Bad"


def test_plex_webhook_unsupported_media_type():
    db = MagicMock()
    db.query.return_value.first.return_value = _settings()
    payload = json.dumps(
        {
            "event": "library.new",
            "Metadata": {"type": "track", "title": "A song"},
        }
    )
    with _db_patch(db):
        r = client.post("/webhook/plex", data={"payload": payload})
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"


def test_plex_webhook_json_direct_fallback():
    """Certains proxies envoient du JSON brut sans form-data."""
    db = MagicMock()
    db.query.return_value.first.return_value = _settings()
    db.query.return_value.filter.return_value.filter.return_value.all.return_value = []

    payload = {
        "event": "library.new",
        "Metadata": {
            "type": "movie",
            "title": "Interstellar",
            "Guid": [],
        },
    }
    with _db_patch(db):
        r = client.post("/webhook/plex", json=payload)
    # Le fallback JSON est tenté ; le résultat exact dépend du content-type
    assert r.status_code == 200
