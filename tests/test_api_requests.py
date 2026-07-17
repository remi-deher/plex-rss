"""Tests unitaires pour les endpoints /api/requests et /api/stats/counts."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db_async as get_db
from app.dependencies import require_admin, require_auth
from app.main import app
from app.models import ArrInstance, Base, MediaRequest, PlexUser, RequestStatus, Settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(async_db):
    return async_db


@pytest.fixture()
def client(db):
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(require_admin, None)
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


def test_list_requests_does_not_truncate_old_open_requests(client, db):
    """Regression production : une demande encore ouverte (sent_to_arr) plus ancienne
    que les 200 lignes les plus recentes ne doit pas disparaitre silencieusement de la
    liste -- l'app charge tout cote client et filtre par statut, une limite trop basse
    cachait des films toujours reellement en cours cote Radarr."""
    from datetime import datetime, timedelta, timezone

    very_old_open = _req(title="Very Old Still Pending", status="sent_to_arr")
    very_old_open.requested_at = datetime.now(timezone.utc) - timedelta(days=365)
    db.add(very_old_open)
    for i in range(210):
        recent = _req(title=f"Recent {i}", status="available")
        recent.requested_at = datetime.now(timezone.utc) - timedelta(minutes=i)
        db.add(recent)
    db.commit()

    resp = client.get("/api/requests")
    titles = {r["title"] for r in resp.json()}
    assert "Very Old Still Pending" in titles


# ---------------------------------------------------------------------------
# GET /api/requests/orphans, DELETE /api/requests/orphans/{arr_type}/{instance_id}/{arr_id}
# ---------------------------------------------------------------------------


def _sonarr_series(**kwargs) -> dict:
    defaults = dict(
        id=501, title="Orphan Show", year=2020, tvdbId=999, monitored=True,
        images=[{"coverType": "poster", "remoteUrl": "https://example/poster.jpg"}],
        seasons=[{"seasonNumber": 1, "monitored": True, "statistics": {
            "episodeFileCount": 5, "episodeCount": 10, "totalEpisodeCount": 12,
        }}],
    )
    defaults.update(kwargs)
    return defaults


def _radarr_movie(**kwargs) -> dict:
    defaults = dict(
        id=601, title="Orphan Movie", year=2021, tmdbId=777, imdbId=None, monitored=True, hasFile=False,
        images=[{"coverType": "poster", "remoteUrl": "https://example/movie.jpg"}],
    )
    defaults.update(kwargs)
    return defaults


def test_list_orphan_requests_returns_sonarr_and_radarr(client, db):
    """Les series/films surveilles sans MediaRequest associee remontent bien, avec
    leur badge de source et leur progression."""
    db.add(ArrInstance(name="Sonarr", arr_type="sonarr", url="http://sonarr", api_key="x", enabled=True))
    db.add(ArrInstance(name="Radarr", arr_type="radarr", url="http://radarr", api_key="x", enabled=True))
    db.commit()

    with (
        patch("app.services.arr_orphans.sonarr.get_all_series", new=AsyncMock(return_value=[_sonarr_series()])),
        patch("app.services.arr_orphans.radarr.get_all_movies", new=AsyncMock(return_value=[_radarr_movie()])),
    ):
        resp = client.get("/api/requests/orphans")
    assert resp.status_code == 200
    data = resp.json()
    by_title = {r["title"]: r for r in data}
    assert by_title["Orphan Show"]["orphan"] is True
    assert by_title["Orphan Show"]["orphan_source"] == "sonarr"
    assert by_title["Orphan Show"]["episodes_available_count"] == 5
    assert by_title["Orphan Movie"]["orphan_source"] == "radarr"


def test_list_orphan_requests_excludes_known_show(client, db):
    """Une serie deja liee a une demande (par tvdb_id) n'apparait pas comme orpheline."""
    db.add(ArrInstance(name="Sonarr", arr_type="sonarr", url="http://sonarr", api_key="x", enabled=True))
    db.add(_req(title="Already Requested", media_type="show", tvdb_id="999", arr_id=None))
    db.commit()

    with patch("app.services.arr_orphans.sonarr.get_all_series", new=AsyncMock(return_value=[_sonarr_series(tvdbId=999)])):
        resp = client.get("/api/requests/orphans")
    assert resp.status_code == 200
    assert resp.json() == []


def test_delete_orphan_calls_sonarr_delete_series(client, db):
    """La suppression d'une serie orpheline appelle bien sonarr.delete_series avec
    l'arr_id et l'instance corrects -- c'est ce qui retire reellement l'entree de Sonarr."""
    inst = ArrInstance(name="Sonarr", arr_type="sonarr", url="http://sonarr", api_key="x", enabled=True)
    db.add(inst)
    db.commit()
    db.refresh(inst)

    with patch(
        "app.routers.requests_api.sonarr.delete_series", new=AsyncMock(return_value=(True, "Supprime de Sonarr"))
    ) as mock_delete:
        resp = client.delete(f"/api/requests/orphans/sonarr/{inst.id}/501")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    mock_delete.assert_awaited_once_with("http://sonarr", "x", 501, delete_files=False)


def test_delete_orphan_calls_radarr_delete_movie_with_files(client, db):
    """delete_files=true est bien transmis a radarr.delete_movie."""
    inst = ArrInstance(name="Radarr", arr_type="radarr", url="http://radarr", api_key="x", enabled=True)
    db.add(inst)
    db.commit()
    db.refresh(inst)

    with patch(
        "app.routers.requests_api.radarr.delete_movie", new=AsyncMock(return_value=(True, "Supprime de Radarr"))
    ) as mock_delete:
        resp = client.delete(f"/api/requests/orphans/radarr/{inst.id}/601?delete_files=true")
    assert resp.status_code == 200
    mock_delete.assert_awaited_once_with("http://radarr", "x", 601, delete_files=True)


def test_delete_orphan_propagates_arr_failure(client, db):
    """Si Sonarr/Radarr refuse la suppression, l'endpoint remonte une erreur -- il ne
    doit jamais faire croire a un succes si le media est toujours present cote *arr."""
    inst = ArrInstance(name="Sonarr", arr_type="sonarr", url="http://sonarr", api_key="x", enabled=True)
    db.add(inst)
    db.commit()
    db.refresh(inst)

    with patch(
        "app.routers.requests_api.sonarr.delete_series", new=AsyncMock(return_value=(False, "Sonarr indisponible"))
    ):
        resp = client.delete(f"/api/requests/orphans/sonarr/{inst.id}/501")
    assert resp.status_code == 502


def test_delete_orphan_invalid_arr_type_rejected(client, db):
    resp = client.delete("/api/requests/orphans/plex/1/501")
    assert resp.status_code == 400


def test_delete_orphan_unknown_instance_404(client, db):
    resp = client.delete("/api/requests/orphans/sonarr/999/501")
    assert resp.status_code == 404


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

    with patch("app.routers.requests_api.poll_watchlists", new=AsyncMock()):
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

    with patch("app.routers.requests_api.poll_watchlists", new=AsyncMock()) as mock_poll:
        client.post(f"/api/requests/{req.id}/retry")

    mock_poll.assert_called_once()


def test_retry_sent_to_arr_returns_400(client, db):
    """Retry d'une demande sent_to_arr → 400."""
    req = _req(status=RequestStatus.sent_to_arr)
    db.add(req)
    db.commit()
    db.refresh(req)

    with patch("app.routers.requests_api.poll_watchlists", new=AsyncMock()):
        resp = client.post(f"/api/requests/{req.id}/retry")

    assert resp.status_code == 400


def test_retry_not_found_returns_404(client, db):
    """Retry sur id inexistant → 404."""
    with patch("app.routers.requests_api.poll_watchlists", new=AsyncMock()):
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
        patch("app.routers.requests_api.poll_watchlists", new=AsyncMock()) as mock_poll,
        patch("app.routers.requests_api.check_arr_statuses", new=AsyncMock()) as mock_check,
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


def test_mark_request_processed_default_sends_available_and_closes(client, db):
    """POST /requests/{id}/mark-processed (défaut event=available) envoie le mail dispo et clôture."""
    settings = Settings(id=1, smtp_host="smtp.example.com")
    req = _req(status=RequestStatus.pending, request_mail_sent=False, available_mail_sent=False)
    db.add_all([settings, req])
    db.commit()
    db.refresh(req)

    with patch("app.routers.requests_api._notify") as mock_notify:
        resp = client.post(f"/api/requests/{req.id}/mark-processed")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["notified"] is True
    assert data["event"] == "available"

    db.refresh(req)
    assert req.status == RequestStatus.available
    assert req.available_mail_sent is True
    assert req.available_at is not None
    mock_notify.assert_called_once_with("available", settings, req, db, force=True, triggered_by="manual")


def test_mark_request_processed_stop_vf_tracking(client, db):
    """stop_vf_tracking=true pose vf_tracking_disabled — la demande sort du scan VF."""
    settings = Settings(id=1, smtp_host="smtp.example.com")
    req = _req(status=RequestStatus.available, has_vf=False, available_mail_sent=True)
    db.add_all([settings, req])
    db.commit()
    db.refresh(req)

    with patch("app.routers.requests_api._notify", new_callable=AsyncMock):
        resp = client.post(
            f"/api/requests/{req.id}/mark-processed?event=available&notify=false&stop_vf_tracking=true"
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["vf_tracking_disabled"] is True

    db.refresh(req)
    assert req.vf_tracking_disabled is True


def test_mark_request_processed_without_stop_vf_tracking_leaves_it_enabled(client, db):
    settings = Settings(id=1, smtp_host="smtp.example.com")
    req = _req(status=RequestStatus.pending)
    db.add_all([settings, req])
    db.commit()
    db.refresh(req)

    with patch("app.routers.requests_api._notify", new_callable=AsyncMock):
        resp = client.post(f"/api/requests/{req.id}/mark-processed")

    assert resp.status_code == 200
    assert resp.json()["vf_tracking_disabled"] is False
    db.refresh(req)
    assert req.vf_tracking_disabled is False


def test_mark_request_processed_event_request_resends_without_closing(client, db):
    """event=request renvoie le mail de demande sans clôturer la demande, même si déjà envoyé."""
    settings = Settings(id=1, smtp_host="smtp.example.com")
    req = _req(status=RequestStatus.pending, request_mail_sent=True, available_mail_sent=False)
    db.add_all([settings, req])
    db.commit()
    db.refresh(req)

    with patch("app.routers.requests_api._notify") as mock_notify:
        resp = client.post(f"/api/requests/{req.id}/mark-processed?event=request")

    assert resp.status_code == 200
    data = resp.json()
    assert data["event"] == "request"

    db.refresh(req)
    assert req.status == RequestStatus.pending  # Pas de clôture
    assert req.request_mail_sent is True
    mock_notify.assert_called_once_with("request", settings, req, db, force=True, triggered_by="manual")


# ---------------------------------------------------------------------------
# POST /api/requests/{id}/resend-mail
# ---------------------------------------------------------------------------


def test_resend_mail_available_does_not_change_status(client, db):
    """resend-mail(event=available) renvoie le mail sans modifier le statut ni les flags."""
    settings = Settings(id=1, smtp_host="smtp.example.com")
    req = _req(status=RequestStatus.sent_to_arr, available_mail_sent=True)
    db.add_all([settings, req])
    db.commit()
    db.refresh(req)

    with patch("app.routers.requests_api._notify") as mock_notify:
        resp = client.post(f"/api/requests/{req.id}/resend-mail?event=available")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    assert data["event"] == "available"
    mock_notify.assert_called_once_with("available", settings, req, db, force=True, triggered_by="manual")

    db.refresh(req)
    assert req.status == RequestStatus.sent_to_arr  # statut inchangé


def test_resend_mail_request_event(client, db):
    settings = Settings(id=1, smtp_host="smtp.example.com")
    req = _req(status=RequestStatus.pending)
    db.add_all([settings, req])
    db.commit()
    db.refresh(req)

    with patch("app.routers.requests_api._notify") as mock_notify:
        resp = client.post(f"/api/requests/{req.id}/resend-mail?event=request")

    assert resp.status_code == 200
    assert resp.json()["event"] == "request"
    mock_notify.assert_called_once_with("request", settings, req, db, force=True, triggered_by="manual")


def test_resend_mail_invalid_event_rejected(client, db):
    req = _req()
    db.add(req)
    db.commit()
    db.refresh(req)

    resp = client.post(f"/api/requests/{req.id}/resend-mail?event=bogus")
    assert resp.status_code == 400


def test_resend_mail_missing_request_404(client, db):
    resp = client.post("/api/requests/999/resend-mail?event=request")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/requests/{id}/requesters
# ---------------------------------------------------------------------------


def test_update_requesters_sets_primary_and_extras(client, db):
    req = _req(plex_user_id="alice", plex_user="Alice")
    bob = PlexUser(plex_user_id="bob", display_name="Bob")
    db.add_all([req, bob])
    db.commit()
    db.refresh(req)

    resp = client.put(f"/api/requests/{req.id}/requesters", json={"requester_ids": ["alice", "bob"]})
    assert resp.status_code == 200
    assert resp.json()["requester_ids"] == ["alice", "bob"]

    db.refresh(req)
    assert req.plex_user_id == "alice"
    import json as _json
    assert _json.loads(req.extra_requesters) == [{"plex_user_id": "bob", "display_name": "Bob"}]


def test_update_requesters_does_not_send_any_mail(client, db):
    """Modification silencieuse par design — voir notify-user pour le renvoi ciblé."""
    req = _req(plex_user_id="alice", plex_user="Alice", request_mail_sent=True)
    bob = PlexUser(plex_user_id="bob", display_name="Bob")
    db.add_all([req, bob])
    db.commit()
    db.refresh(req)

    with patch("app.routers.requests_api._notify") as mock_notify, patch(
        "app.routers.requests_api.notify_single_user"
    ) as mock_notify_single:
        resp = client.put(f"/api/requests/{req.id}/requesters", json={"requester_ids": ["alice", "bob"]})

    assert resp.status_code == 200
    mock_notify.assert_not_called()
    mock_notify_single.assert_not_called()


def test_update_requesters_empty_list_rejected(client, db):
    req = _req()
    db.add(req)
    db.commit()
    db.refresh(req)

    resp = client.put(f"/api/requests/{req.id}/requesters", json={"requester_ids": ["", "  "]})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/requests/{id}/notify-user
# ---------------------------------------------------------------------------


def test_notify_user_queues_requested_events(client, db):
    settings = Settings(id=1, smtp_host="smtp.example.com")
    req = _req(plex_user_id="alice", available_mail_sent=True)
    db.add_all([settings, req])
    db.commit()
    db.refresh(req)

    with patch("app.routers.requests_api.notify_single_user", new=AsyncMock(side_effect=[True, True])) as mock_notify:
        resp = client.post(
            f"/api/requests/{req.id}/notify-user",
            json={"plex_user_id": "bob", "events": ["request", "available"]},
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "queued": ["request", "available"]}
    assert mock_notify.await_count == 2
    mock_notify.assert_any_await("request", settings, req, db, "bob")
    mock_notify.assert_any_await("available", settings, req, db, "bob")


def test_notify_user_reports_which_events_actually_queued(client, db):
    """Si un des deux events echoue (ex: utilisateur introuvable/desactive), seul celui
    qui a reellement ete mis en queue doit apparaitre dans la reponse."""
    settings = Settings(id=1, smtp_host="smtp.example.com")
    req = _req(plex_user_id="alice")
    db.add_all([settings, req])
    db.commit()
    db.refresh(req)

    with patch("app.routers.requests_api.notify_single_user", new=AsyncMock(side_effect=[True, False])):
        resp = client.post(
            f"/api/requests/{req.id}/notify-user",
            json={"plex_user_id": "bob", "events": ["request", "available"]},
        )

    assert resp.status_code == 200
    assert resp.json()["queued"] == ["request"]


def test_notify_user_invalid_events_rejected(client, db):
    req = _req()
    db.add(req)
    db.commit()
    db.refresh(req)

    resp = client.post(f"/api/requests/{req.id}/notify-user", json={"plex_user_id": "bob", "events": ["bogus"]})
    assert resp.status_code == 400


def test_notify_user_missing_request_404(client, db):
    resp = client.post("/api/requests/999/notify-user", json={"plex_user_id": "bob", "events": ["request"]})
    assert resp.status_code == 404


def test_bulk_retry_requests(client, db):
    """POST /api/requests/bulk/retry repasse les demandes failed/pending en pending."""
    r1 = _req(status=RequestStatus.failed)
    r2 = _req(status=RequestStatus.pending)
    r3 = _req(status=RequestStatus.sent_to_arr)
    db.add_all([r1, r2, r3])
    db.commit()
    db.refresh(r1)
    db.refresh(r2)
    db.refresh(r3)

    with patch("app.routers.requests_api.poll_watchlists", new=AsyncMock()) as mock_poll:
        resp = client.post("/api/requests/bulk/retry", json={"ids": [r1.id, r2.id, r3.id]})
    assert resp.status_code == 200
    assert resp.json()["count"] == 2

    db.refresh(r1)
    db.refresh(r2)
    db.refresh(r3)
    assert r1.status == RequestStatus.pending
    assert r2.status == RequestStatus.pending
    assert r3.status == RequestStatus.sent_to_arr
    mock_poll.assert_called_once()


def test_bulk_mark_requests_processed(client, db):
    """POST /api/requests/bulk/mark-processed marque plusieurs demandes comme disponibles."""
    r1 = _req(status=RequestStatus.pending, request_mail_sent=False, available_mail_sent=False)
    r2 = _req(status=RequestStatus.failed, request_mail_sent=False, available_mail_sent=False)
    db.add_all([r1, r2])
    db.commit()
    db.refresh(r1)
    db.refresh(r2)

    resp = client.post("/api/requests/bulk/mark-processed", json={"ids": [r1.id, r2.id]})
    assert resp.status_code == 200
    assert resp.json()["count"] == 2

    db.refresh(r1)
    db.refresh(r2)
    assert r1.status == RequestStatus.available
    assert r1.request_mail_sent is True
    assert r1.available_mail_sent is True
    assert r1.available_at is not None

    assert r2.status == RequestStatus.available
    assert r2.request_mail_sent is True
    assert r2.available_mail_sent is True
    assert r2.available_at is not None


def test_bulk_resolve_requests_uses_filters(client, db):
    """POST /api/requests/bulk/resolve retourne toutes les demandes du filtre, pas seulement la page visible."""
    r1 = _req(title="Dune", status=RequestStatus.sent_to_arr, media_type="movie", source="seer")
    r2 = _req(title="Dune Part Two", status=RequestStatus.sent_to_arr, media_type="movie", source="seer")
    r3 = _req(title="Dune Show", status=RequestStatus.sent_to_arr, media_type="show", source="seer")
    r4 = _req(title="Inception", status=RequestStatus.failed, media_type="movie", source="rss")
    db.add_all([r1, r2, r3, r4])
    db.commit()

    resp = client.post(
        "/api/requests/bulk/resolve",
        json={"type": "movie", "search": "Dune", "status": "sent_to_arr", "source": "seer"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert set(data["ids"]) == {r1.id, r2.id}


def test_bulk_delete_requests(client, db):
    """POST /api/requests/bulk/delete supprime plusieurs demandes."""
    r1 = _req()
    r2 = _req()
    db.add_all([r1, r2])
    db.commit()
    db.refresh(r1)
    db.refresh(r2)

    resp = client.post("/api/requests/bulk/delete", json={"ids": [r1.id, r2.id]})
    assert resp.status_code == 200
    assert resp.json()["count"] == 2

    assert db.query(MediaRequest).filter(MediaRequest.id == r1.id).first() is None
    assert db.query(MediaRequest).filter(MediaRequest.id == r2.id).first() is None
