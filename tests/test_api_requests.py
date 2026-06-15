"""Tests unitaires pour les endpoints /api/requests et /api/stats/counts."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base, MediaRequest, PlexUser, RequestStatus, Settings
from app.routers.api import require_auth

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def client(db):
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(get_db, None)


def _req(**kwargs) -> MediaRequest:
    defaults = dict(
        plex_user_id="alice",
        plex_user="Alice",
        title="Inception",
        media_type="movie",
        status=RequestStatus.sent_to_arr,
        arr_id=42,
    )
    defaults.update(kwargs)
    return MediaRequest(**defaults)


# ---------------------------------------------------------------------------
# GET /api/requests
# ---------------------------------------------------------------------------


def test_list_requests_empty(client, db):
    """Liste vide si aucune demande en DB."""
    resp = client.get("/api/requests")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_requests_returns_all(client, db):
    """Retourne toutes les demandes présentes."""
    db.add(_req(title="Inception"))
    db.add(_req(title="Breaking Bad", media_type="show"))
    db.commit()

    resp = client.get("/api/requests")
    assert resp.status_code == 200
    titles = {r["title"] for r in resp.json()}
    assert titles == {"Inception", "Breaking Bad"}


def test_list_requests_ordered_by_date_desc(client, db):
    """Les demandes sont triées par requested_at décroissant."""
    from datetime import datetime, timedelta, timezone

    older = _req(title="Old Movie")
    older.requested_at = datetime.now(timezone.utc) - timedelta(hours=2)
    newer = _req(title="New Movie")
    newer.requested_at = datetime.now(timezone.utc)
    db.add(older)
    db.add(newer)
    db.commit()

    resp = client.get("/api/requests")
    titles = [r["title"] for r in resp.json()]
    assert titles[0] == "New Movie"
    assert titles[1] == "Old Movie"


# ---------------------------------------------------------------------------
# GET /api/requests/{id}
# ---------------------------------------------------------------------------


def test_get_request_returns_detail(client, db):
    """Retourne les champs du média + _user_emails / _admin_emails."""
    db.add(Settings(smtp_from="admin@example.com", admin_notification_email=None))
    db.add(PlexUser(plex_user_id="alice", notification_email="alice@example.com", notify_admin=False))
    req = _req()
    db.add(req)
    db.commit()
    db.refresh(req)

    resp = client.get(f"/api/requests/{req.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Inception"
    assert "alice@example.com" in data["_user_emails"]
    assert data["_admin_emails"] == []


def test_get_request_not_found(client, db):
    """404 si l'id n'existe pas."""
    resp = client.get("/api/requests/9999")
    assert resp.status_code == 404


def test_get_request_admin_copy_included_when_notify_admin(client, db):
    """notify_admin=True → admin email dans _admin_emails."""
    db.add(Settings(smtp_from="user@x.com", admin_notification_email="boss@x.com"))
    db.add(PlexUser(plex_user_id="alice", notification_email="alice@x.com", notify_admin=True))
    req = _req()
    db.add(req)
    db.commit()
    db.refresh(req)

    resp = client.get(f"/api/requests/{req.id}")
    assert "boss@x.com" in resp.json()["_admin_emails"]


# ---------------------------------------------------------------------------
# POST /api/requests/{id}/retry
# ---------------------------------------------------------------------------


def test_retry_failed_request_sets_pending(client, db):
    """Retry d'une demande failed → status pending avant le re-poll."""
    req = _req(status=RequestStatus.failed)
    db.add(req)
    db.commit()
    db.refresh(req)

    with patch("app.routers.api.poll_watchlists", new=AsyncMock()):
        resp = client.post(f"/api/requests/{req.id}/retry")

    assert resp.status_code == 200
    assert resp.json()["status"] == "retrying"
    db.refresh(req)
    assert req.status == RequestStatus.pending


def test_retry_calls_poll_watchlists(client, db):
    """Retry déclenche poll_watchlists."""
    req = _req(status=RequestStatus.failed)
    db.add(req)
    db.commit()
    db.refresh(req)

    with patch("app.routers.api.poll_watchlists", new=AsyncMock()) as mock_poll:
        client.post(f"/api/requests/{req.id}/retry")

    mock_poll.assert_called_once()


def test_retry_sent_to_arr_returns_400(client, db):
    """Retry d'une demande sent_to_arr → 400."""
    req = _req(status=RequestStatus.sent_to_arr)
    db.add(req)
    db.commit()
    db.refresh(req)

    with patch("app.routers.api.poll_watchlists", new=AsyncMock()):
        resp = client.post(f"/api/requests/{req.id}/retry")

    assert resp.status_code == 400


def test_retry_not_found_returns_404(client, db):
    """Retry sur id inexistant → 404."""
    with patch("app.routers.api.poll_watchlists", new=AsyncMock()):
        resp = client.post("/api/requests/9999/retry")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/requests/{id}
# ---------------------------------------------------------------------------


def test_delete_request_removes_from_db(client, db):
    """DELETE supprime la demande et retourne status deleted."""
    req = _req()
    db.add(req)
    db.commit()
    db.refresh(req)

    resp = client.delete(f"/api/requests/{req.id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    assert db.query(MediaRequest).filter(MediaRequest.id == req.id).first() is None


def test_delete_request_not_found(client, db):
    """DELETE sur id inexistant → 404."""
    resp = client.delete("/api/requests/9999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/requests/poll
# ---------------------------------------------------------------------------


def test_trigger_poll_calls_both_jobs(client, db):
    """POST /requests/poll déclenche poll_watchlists ET check_arr_statuses."""
    with (
        patch("app.routers.api.poll_watchlists", new=AsyncMock()) as mock_poll,
        patch("app.routers.api.check_arr_statuses", new=AsyncMock()) as mock_check,
    ):
        resp = client.post("/api/requests/poll")

    assert resp.status_code == 200
    mock_poll.assert_called_once()
    mock_check.assert_called_once()


def test_get_request_dates_are_serialized_with_utc_timezone(client, db):
    """Vérifie que les dates retournées ont bien un suffixe Z/timezone offset."""
    from datetime import datetime

    req = _req(requested_at=datetime(2026, 6, 15, 21, 30, 0))  # naive UTC datetime
    db.add(req)
    db.commit()
    db.refresh(req)

    resp = client.get(f"/api/requests/{req.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["requested_at"].endswith("Z") or "+00:00" in data["requested_at"]


def test_mark_request_processed_skips_emails(client, db):
    """POST /requests/{id}/mark-processed passe la demande en available et marque les mails comme envoyés."""
    req = _req(status=RequestStatus.pending, request_mail_sent=False, available_mail_sent=False)
    db.add(req)
    db.commit()
    db.refresh(req)

    resp = client.post(f"/api/requests/{req.id}/mark-processed")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    db.refresh(req)
    assert req.status == RequestStatus.available
    assert req.request_mail_sent is True
    assert req.available_mail_sent is True
    assert req.available_at is not None
