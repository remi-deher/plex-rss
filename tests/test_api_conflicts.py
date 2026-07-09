"""
Tests unitaires des endpoints /api/conflicts.

Couvre :
- GET  /api/conflicts             : tmdb_conflicts, orphaned, long_pending
- POST /api/conflicts/resolve     : fusion + suppression
- POST /api/conflicts/auto-resolve: résolution automatique (garde Seer)
- POST /api/conflicts/ignore      : persistance des conflits ignorés
- DELETE /api/conflicts/ignore/{key}
- DELETE /api/conflicts/no-tmdb/{id}
- DELETE /api/conflicts/orphan/{id}
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.dependencies import require_auth
from app.main import app
from app.models import Base, MediaRequest, PlexUser, RequestStatus, Settings
from app.routers import email_templates as email_templates_router
from app.routers import pages as pages_router

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
    app.dependency_overrides[pages_router.require_auth] = lambda: None
    app.dependency_overrides[email_templates_router.require_auth] = lambda: None
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app, raise_server_exceptions=True, follow_redirects=False)
    yield c
    app.dependency_overrides.clear()


def _user(db, plex_user_id="alice", **kwargs) -> PlexUser:
    u = PlexUser(plex_user_id=plex_user_id, enabled=True, **kwargs)
    db.add(u)
    db.commit()
    return u


def _req(
    db,
    plex_user_id="alice",
    title="Liar Game",
    media_type="show",
    tmdb_id="13967",
    tvdb_id="81763",
    source="rss",
    status=RequestStatus.sent_to_arr,
    requested_at=None,
    **kwargs,
) -> MediaRequest:
    r = MediaRequest(
        plex_user_id=plex_user_id,
        plex_user=plex_user_id,
        title=title,
        media_type=media_type,
        tmdb_id=tmdb_id,
        tvdb_id=tvdb_id,
        source=source,
        status=status,
        requested_at=requested_at or datetime(2026, 1, 15),
        **kwargs,
    )
    db.add(r)
    db.commit()
    return r


# Patch ignore file I/O pour ne pas toucher le disque
def _no_ignored():
    return patch("app.routers.misc_api._load_ignored", return_value=set())


# ---------------------------------------------------------------------------
# GET /api/conflicts — tmdb_conflicts
# ---------------------------------------------------------------------------


def test_conflicts_tmdb_detected(client, db):
    """Deux entrées avec même tvdb_id mais tmdb_ids différents → conflit détecté."""
    _user(db, plex_user_id="alice")
    _req(db, plex_user_id="alice", tmdb_id="300126", tvdb_id="81763", source="rss")
    _req(db, plex_user_id="alice", tmdb_id="13967", tvdb_id="81763", source="seer")

    with _no_ignored():
        r = client.get("/api/conflicts")

    assert r.status_code == 200
    data = r.json()
    assert len(data["tmdb_conflicts"]) == 1
    conflict = data["tmdb_conflicts"][0]
    assert conflict["tvdb_id"] == "81763"
    assert len(conflict["entries"]) == 2


def test_conflicts_recommended_id_is_seer_entry(client, db):
    """L'entrée Seer est recommandée dans un conflit tmdb."""
    _user(db, plex_user_id="alice")
    _req(db, plex_user_id="alice", tmdb_id="300126", tvdb_id="81763", source="rss")
    seer = _req(db, plex_user_id="alice", tmdb_id="13967", tvdb_id="81763", source="seer")

    with _no_ignored():
        r = client.get("/api/conflicts")

    conflict = r.json()["tmdb_conflicts"][0]
    assert conflict["recommended_id"] == seer.id


def test_conflicts_no_conflict_same_tmdb(client, db):
    """Même tvdb_id ET même tmdb_id → pas de conflit."""
    _user(db, plex_user_id="alice")
    _user(db, plex_user_id="bob")
    _req(db, plex_user_id="alice", tmdb_id="13967", tvdb_id="81763")
    _req(db, plex_user_id="bob", tmdb_id="13967", tvdb_id="81763")

    with _no_ignored():
        r = client.get("/api/conflicts")

    assert r.json()["tmdb_conflicts"] == []


def test_conflicts_no_conflict_no_tvdb(client, db):
    """Sans tvdb_id, pas de groupe → pas de conflit tmdb."""
    _user(db, plex_user_id="alice")
    _req(db, plex_user_id="alice", tmdb_id="27205", tvdb_id=None)

    with _no_ignored():
        r = client.get("/api/conflicts")

    assert r.json()["tmdb_conflicts"] == []


# ---------------------------------------------------------------------------
# GET /api/conflicts — orphaned
# ---------------------------------------------------------------------------


def test_conflicts_orphaned_user_deleted(client, db):
    """Demande d'un utilisateur absent de PlexUser → orpheline."""
    # Pas d'utilisateur en base pour "ghost"
    db.add(
        MediaRequest(
            plex_user_id="ghost",
            plex_user="ghost",
            title="Ghost Show",
            media_type="show",
            status=RequestStatus.pending,
            requested_at=datetime(2026, 1, 1),
        )
    )
    db.commit()

    with _no_ignored():
        r = client.get("/api/conflicts")

    orphaned = r.json()["orphaned"]
    assert len(orphaned) == 1
    assert orphaned[0]["plex_user_id"] == "ghost"


def test_conflicts_orphaned_not_shown_for_known_user(client, db):
    """Demande d'un utilisateur connu → pas orpheline."""
    _user(db, plex_user_id="alice")
    _req(db, plex_user_id="alice")

    with _no_ignored():
        r = client.get("/api/conflicts")

    assert r.json()["orphaned"] == []


# ---------------------------------------------------------------------------
# GET /api/conflicts — long_pending
# ---------------------------------------------------------------------------


def test_conflicts_long_pending_detected(client, db):
    """Demande en statut 'pending' depuis >30 jours → long_pending."""
    _user(db, plex_user_id="alice")
    old_date = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=45)
    _req(db, plex_user_id="alice", status=RequestStatus.pending, requested_at=old_date)

    with _no_ignored():
        r = client.get("/api/conflicts")

    lp = r.json()["long_pending"]
    assert len(lp) == 1
    assert lp[0]["age_days"] >= 45


def test_conflicts_long_pending_excludes_sent_to_arr(client, db):
    """sent_to_arr (ex : média pas encore sorti) ne doit pas apparaître dans long_pending."""
    _user(db, plex_user_id="alice")
    old_date = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=60)
    _req(db, plex_user_id="alice", status=RequestStatus.sent_to_arr, requested_at=old_date)

    with _no_ignored():
        r = client.get("/api/conflicts")

    assert r.json()["long_pending"] == []


def test_conflicts_long_pending_excludes_recent(client, db):
    """En attente depuis <30 jours → pas dans long_pending."""
    _user(db, plex_user_id="alice")
    recent = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)
    _req(db, plex_user_id="alice", status=RequestStatus.pending, requested_at=recent)

    with _no_ignored():
        r = client.get("/api/conflicts")

    assert r.json()["long_pending"] == []


# ---------------------------------------------------------------------------
# POST /api/conflicts/resolve
# ---------------------------------------------------------------------------


def test_resolve_merges_and_deletes(client, db):
    """Résoudre un conflit : keeper conservé, dup supprimé, co-demandeur transféré."""
    _user(db, plex_user_id="alice")
    keeper = _req(db, plex_user_id="alice", tmdb_id="300126", tvdb_id="81763", source="rss")
    dup = _req(db, plex_user_id="bob", tmdb_id="13967", tvdb_id="81763", source="seer")

    r = client.post("/api/conflicts/resolve", json={"keep_id": keeper.id, "delete_ids": [dup.id]})

    assert r.status_code == 200
    assert r.json()["kept"] == keeper.id
    assert db.query(MediaRequest).count() == 1
    db.refresh(keeper)
    extras = json.loads(keeper.extra_requesters or "[]")
    assert any(e["plex_user_id"] == "bob" for e in extras)


def test_resolve_seer_tmdb_wins(client, db):
    """Le tmdb_id de l'entrée Seer remplace celui du keeper RSS."""
    _user(db, plex_user_id="alice")
    keeper = _req(db, plex_user_id="alice", tmdb_id="300126", source="rss")
    dup = _req(db, plex_user_id="alice", tmdb_id="13967", source="seer")

    client.post("/api/conflicts/resolve", json={"keep_id": keeper.id, "delete_ids": [dup.id]})

    db.refresh(keeper)
    assert keeper.tmdb_id == "13967"


def test_resolve_missing_keep_id_returns_400(client, db):
    r = client.post("/api/conflicts/resolve", json={"delete_ids": [1]})
    assert r.status_code == 400


def test_resolve_unknown_keep_id_returns_404(client, db):
    r = client.post("/api/conflicts/resolve", json={"keep_id": 9999, "delete_ids": [1]})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/conflicts/auto-resolve
# ---------------------------------------------------------------------------


def test_auto_resolve_keeps_seer_entry(client, db):
    """Auto-resolve : l'entrée Seer est conservée, l'entrée RSS supprimée."""
    _user(db, plex_user_id="alice")
    _req(db, plex_user_id="alice", tmdb_id="300126", tvdb_id="81763", source="rss")
    seer = _req(db, plex_user_id="alice", tmdb_id="13967", tvdb_id="81763", source="seer")

    r = client.post("/api/conflicts/auto-resolve")

    assert r.status_code == 200
    assert r.json()["resolved"] == 1
    remaining = db.query(MediaRequest).all()
    assert len(remaining) == 1
    assert remaining[0].id == seer.id


def test_auto_resolve_no_conflicts_returns_zero(client, db):
    """Sans conflit, auto-resolve retourne resolved=0."""
    _user(db, plex_user_id="alice")
    _req(db, plex_user_id="alice", tmdb_id="13967", tvdb_id="81763")

    r = client.post("/api/conflicts/auto-resolve")

    assert r.status_code == 200
    assert r.json()["resolved"] == 0


def test_auto_resolve_merges_co_requesters(client, db):
    """L'utilisateur RSS est ajouté en co-demandeur sur l'entrée Seer après auto-resolve."""
    _user(db, plex_user_id="alice")
    _req(db, plex_user_id="alice", tmdb_id="300126", tvdb_id="81763", source="rss")
    seer = _req(db, plex_user_id="bob", tmdb_id="13967", tvdb_id="81763", source="seer")

    client.post("/api/conflicts/auto-resolve")

    db.refresh(seer)
    extras = json.loads(seer.extra_requesters or "[]")
    assert any(e["plex_user_id"] == "alice" for e in extras)


# ---------------------------------------------------------------------------
# POST /api/conflicts/ignore  et  DELETE /api/conflicts/ignore/{key}
# ---------------------------------------------------------------------------


def test_ignore_conflict_persisted(client, db):
    """Ignorer un conflit sauvegarde la clé dans le fichier."""
    saved = {}

    def fake_save(keys):
        saved["keys"] = keys

    with (
        patch("app.routers.misc_api._load_ignored", return_value=set()),
        patch("app.routers.misc_api._save_ignored", side_effect=fake_save),
    ):
        r = client.post("/api/conflicts/ignore", json={"key": "tmdb:show:81763"})

    assert r.status_code == 200
    assert "tmdb:show:81763" in saved["keys"]


def test_ignore_missing_key_returns_400(client, db):
    r = client.post("/api/conflicts/ignore", json={})
    assert r.status_code == 400


def test_unignore_removes_key(client, db):
    """Supprimer l'ignore retire la clé du fichier."""
    saved = {}

    def fake_save(keys):
        saved["keys"] = keys

    with (
        patch("app.routers.misc_api._load_ignored", return_value={"tmdb:show:81763"}),
        patch("app.routers.misc_api._save_ignored", side_effect=fake_save),
    ):
        r = client.delete("/api/conflicts/ignore/tmdb:show:81763")

    assert r.status_code == 200
    assert "tmdb:show:81763" not in saved.get("keys", set())


def test_ignored_conflict_not_returned(client, db):
    """Un conflit ignoré n'apparaît pas dans GET /api/conflicts."""
    _user(db, plex_user_id="alice")
    _req(db, plex_user_id="alice", tmdb_id="300126", tvdb_id="81763", source="rss")
    _req(db, plex_user_id="alice", tmdb_id="13967", tvdb_id="81763", source="seer")

    with patch("app.routers.misc_api._load_ignored", return_value={"tmdb:show:81763"}):
        r = client.get("/api/conflicts")

    assert r.json()["tmdb_conflicts"] == []


# ---------------------------------------------------------------------------
# DELETE /api/conflicts/no-tmdb/{id}
# ---------------------------------------------------------------------------


def test_delete_no_tmdb_removes_entry(client, db):
    _user(db, plex_user_id="alice")
    r_obj = _req(db, plex_user_id="alice", tmdb_id=None, tvdb_id=None)

    r = client.delete(f"/api/conflicts/no-tmdb/{r_obj.id}")

    assert r.status_code == 200
    assert db.query(MediaRequest).count() == 0


def test_delete_no_tmdb_rejects_if_tmdb_present(client, db):
    _user(db, plex_user_id="alice")
    r_obj = _req(db, plex_user_id="alice", tmdb_id="27205")

    r = client.delete(f"/api/conflicts/no-tmdb/{r_obj.id}")

    assert r.status_code == 400


def test_delete_no_tmdb_not_found(client, db):
    r = client.delete("/api/conflicts/no-tmdb/9999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/conflicts/orphan/{id}
# ---------------------------------------------------------------------------


def test_delete_orphan_removes_entry(client, db):
    db.add(
        MediaRequest(
            plex_user_id="ghost",
            plex_user="ghost",
            title="Ghost Show",
            media_type="show",
            status=RequestStatus.pending,
        )
    )
    db.commit()
    orphan = db.query(MediaRequest).first()

    r = client.delete(f"/api/conflicts/orphan/{orphan.id}")

    assert r.status_code == 200
    assert db.query(MediaRequest).count() == 0


def test_delete_orphan_not_found(client, db):
    r = client.delete("/api/conflicts/orphan/9999")
    assert r.status_code == 404
