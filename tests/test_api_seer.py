"""
Tests unitaires des endpoints API Seer.

Couvre :
- PUT  /api/users/{id}/custom-name
- POST /api/users/{id}/seer-complete
- POST /api/users/{id}/seer-automatch
- POST /api/users/{seer_only_id}/merge-into/{target_id}
- POST /api/seer/sync/users
- POST /api/seer/sync/requests
"""

from unittest.mock import AsyncMock, patch

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


def _settings(db) -> Settings:
    s = Settings(
        seer_enabled=True,
        seer_url="http://seer.local",
        seer_api_key="key",
    )
    db.add(s)
    db.commit()
    return s


def _user(db, plex_user_id="alice", display_name="Alice", **kwargs) -> PlexUser:
    u = PlexUser(plex_user_id=plex_user_id, enabled=True, display_name=display_name, **kwargs)
    db.add(u)
    db.commit()
    return u


# ---------------------------------------------------------------------------
# PUT /api/users/{id}/custom-name
# ---------------------------------------------------------------------------


def test_custom_name_set(client, db):
    u = _user(db)
    r = client.put(f"/api/users/{u.id}/custom-name", json={"custom_name": "Mon Pseudo"})
    assert r.status_code == 200
    assert r.json()["custom_name"] == "Mon Pseudo"
    db.refresh(u)
    assert u.custom_name == "Mon Pseudo"


def test_custom_name_clear(client, db):
    u = _user(db, custom_name="Ancien Pseudo")
    r = client.put(f"/api/users/{u.id}/custom-name", json={"custom_name": ""})
    assert r.status_code == 200
    assert r.json()["custom_name"] is None
    db.refresh(u)
    assert u.custom_name is None


def test_custom_name_not_found(client, db):
    r = client.put("/api/users/9999/custom-name", json={"custom_name": "Test"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/users/{id}/seer-complete
# ---------------------------------------------------------------------------

SEER_USERS_RESPONSE = {
    "alice@example.com": {
        "id": 3,
        "display_name": "Alice Wonderland",
        "request_count": 5,
        "plex_username": "alice",
        "plex_id": 1,
        "user_type": 4,
    }
}


def test_seer_complete_fills_missing_fields(client, db):
    _settings(db)
    u = _user(db, seer_user_id=3, plex_email=None, custom_name=None)

    with patch("app.routers.users_api.seer_get_users", new=AsyncMock(return_value=SEER_USERS_RESPONSE)):
        r = client.post(f"/api/users/{u.id}/seer-complete")

    assert r.status_code == 200
    db.refresh(u)
    assert u.custom_name == "Alice Wonderland"
    assert u.plex_email == "alice@example.com"


def test_seer_complete_not_linked(client, db):
    _settings(db)
    u = _user(db, seer_user_id=None)
    r = client.post(f"/api/users/{u.id}/seer-complete")
    assert r.status_code == 400


def test_seer_complete_no_settings(client, db):
    u = _user(db, seer_user_id=3)
    r = client.post(f"/api/users/{u.id}/seer-complete")
    assert r.status_code == 400


def test_seer_complete_not_found_user(client, db):
    _settings(db)
    r = client.post("/api/users/9999/seer-complete")
    assert r.status_code == 404


def test_seer_complete_preserves_existing_fields(client, db):
    """Ne doit pas écraser les champs déjà renseignés."""
    _settings(db)
    u = _user(db, seer_user_id=3, plex_email="deja@existant.fr", custom_name="Nom Existant")

    with patch("app.routers.users_api.seer_get_users", new=AsyncMock(return_value=SEER_USERS_RESPONSE)):
        r = client.post(f"/api/users/{u.id}/seer-complete")

    assert r.status_code == 200
    db.refresh(u)
    assert u.plex_email == "deja@existant.fr"
    assert u.custom_name == "Nom Existant"


# ---------------------------------------------------------------------------
# POST /api/users/{id}/seer-automatch
# ---------------------------------------------------------------------------


def test_automatch_by_email(client, db):
    _settings(db)
    u = _user(db, plex_email="alice@example.com", seer_user_id=None)

    with patch("app.routers.users_api.seer_get_users", new=AsyncMock(return_value=SEER_USERS_RESPONSE)):
        r = client.post(f"/api/users/{u.id}/seer-automatch")

    assert r.status_code == 200
    body = r.json()
    assert body["matched"] is True
    assert body["method"] == "email"
    assert body["seer_user_id"] == 3
    db.refresh(u)
    assert u.seer_user_id == 3


def test_automatch_by_plex_username(client, db):
    _settings(db)
    u = _user(db, plex_user_id="alice", display_name="alice", plex_email=None, seer_user_id=None)

    with patch("app.routers.users_api.seer_get_users", new=AsyncMock(return_value=SEER_USERS_RESPONSE)):
        r = client.post(f"/api/users/{u.id}/seer-automatch")

    assert r.status_code == 200
    body = r.json()
    assert body["matched"] is True
    assert body["method"] == "plex_username"


def test_automatch_no_match(client, db):
    _settings(db)
    u = _user(db, plex_email="nobody@example.com", display_name="nobody", seer_user_id=None)

    with (
        patch("app.routers.users_api.seer_get_users", new=AsyncMock(return_value=SEER_USERS_RESPONSE)),
        patch("app.routers.users_api.seer_get_user_requests", new=AsyncMock(return_value=[])),
    ):
        r = client.post(f"/api/users/{u.id}/seer-automatch")

    assert r.status_code == 200
    assert r.json()["matched"] is False


def test_automatch_already_matched_seer_id_not_reused(client, db):
    """Le seer_user_id 3 est déjà pris par un autre utilisateur → pas de match."""
    _settings(db)
    _user(db, plex_user_id="bob", seer_user_id=3)
    u = _user(db, plex_user_id="alice", plex_email="alice@example.com", seer_user_id=None)

    with patch("app.routers.users_api.seer_get_users", new=AsyncMock(return_value=SEER_USERS_RESPONSE)):
        r = client.post(f"/api/users/{u.id}/seer-automatch")

    assert r.status_code == 200
    assert r.json()["matched"] is False


def test_automatch_not_found(client, db):
    _settings(db)
    r = client.post("/api/users/9999/seer-automatch")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/users/{seer_only_id}/merge-into/{target_id}
# ---------------------------------------------------------------------------


def _seer_only_user(db, seer_id=99, display_name="Charlie Seer", **kwargs) -> PlexUser:
    u = PlexUser(
        plex_user_id=f"seer:{seer_id}",
        display_name=display_name,
        seer_user_id=seer_id,
        seer_active=True,
        source="seer",
        enabled=True,
        **kwargs,
    )
    db.add(u)
    db.commit()
    return u


def _req(db, plex_user_id: str, title="Inception") -> MediaRequest:
    r = MediaRequest(
        plex_user_id=plex_user_id, plex_user=plex_user_id, title=title, media_type="movie", status="pending"
    )
    db.add(r)
    db.commit()
    return r


def test_merge_seer_only_into_rss_transfers_requests(client, db):
    """Les MediaRequest du user seer-only sont réattribués au user RSS cible."""
    seer_user = _seer_only_user(db)
    rss_user = _user(db, plex_user_id="abc123", display_name="Alice")
    _req(db, plex_user_id=seer_user.plex_user_id)
    _req(db, plex_user_id=seer_user.plex_user_id, title="Dune")

    r = client.post(f"/api/users/{seer_user.id}/merge-into/{rss_user.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "merged"
    assert body["requests_moved"] == 2
    assert body["target_plex_user_id"] == "abc123"
    assert body["seer_user_id"] == 99


def test_merge_seer_only_sets_seer_link_on_target(client, db):
    """Le user RSS cible reçoit seer_user_id et seer_active après la fusion."""
    seer_user = _seer_only_user(db, seer_id=42)
    rss_user = _user(db, plex_user_id="abc123", seer_user_id=None, seer_active=None)

    client.post(f"/api/users/{seer_user.id}/merge-into/{rss_user.id}")

    db.refresh(rss_user)
    assert rss_user.seer_user_id == 42
    assert rss_user.seer_active is True


def test_merge_seer_only_deletes_synthetic_user(client, db):
    """L'entrée seer-only est supprimée après la fusion."""
    seer_user = _seer_only_user(db)
    rss_user = _user(db, plex_user_id="abc123")

    client.post(f"/api/users/{seer_user.id}/merge-into/{rss_user.id}")

    assert db.query(PlexUser).filter_by(plex_user_id="seer:99").first() is None


def test_merge_seer_only_requests_now_belong_to_rss_user(client, db):
    """Après fusion, les demandes sont bien portées par le plex_user_id RSS."""
    seer_user = _seer_only_user(db)
    rss_user = _user(db, plex_user_id="abc123")
    _req(db, plex_user_id=seer_user.plex_user_id)

    client.post(f"/api/users/{seer_user.id}/merge-into/{rss_user.id}")

    rows = db.query(MediaRequest).all()
    assert len(rows) == 1
    assert rows[0].plex_user_id == "abc123"


def test_merge_seer_only_fails_if_source_not_seer(client, db):
    """Un user RSS ne peut pas être la source d'une fusion (source != 'seer')."""
    rss_user1 = _user(db, plex_user_id="abc123")
    rss_user2 = _user(db, plex_user_id="def456")

    r = client.post(f"/api/users/{rss_user1.id}/merge-into/{rss_user2.id}")
    assert r.status_code == 400


def test_merge_seer_only_fails_if_target_is_seer(client, db):
    """La cible ne peut pas être un user seer-only."""
    seer1 = _seer_only_user(db, seer_id=1)
    seer2 = _seer_only_user(db, seer_id=2)

    r = client.post(f"/api/users/{seer1.id}/merge-into/{seer2.id}")
    assert r.status_code == 400


def test_merge_seer_only_not_found_source(client, db):
    rss_user = _user(db)
    r = client.post(f"/api/users/9999/merge-into/{rss_user.id}")
    assert r.status_code == 404


def test_merge_seer_only_not_found_target(client, db):
    seer_user = _seer_only_user(db)
    r = client.post(f"/api/users/{seer_user.id}/merge-into/9999")
    assert r.status_code == 404


def test_merge_seer_only_zero_requests(client, db):
    """Fusion sans demandes à transférer → requests_moved == 0, pas d'erreur."""
    seer_user = _seer_only_user(db)
    rss_user = _user(db, plex_user_id="abc123")

    r = client.post(f"/api/users/{seer_user.id}/merge-into/{rss_user.id}")
    assert r.status_code == 200
    assert r.json()["requests_moved"] == 0


# ---------------------------------------------------------------------------
# POST /api/seer/sync/users  et  /api/seer/sync/requests
# ---------------------------------------------------------------------------


def test_seer_sync_users_endpoint(client, db):
    with patch("app.scheduler.sync_seer_users", new=AsyncMock(return_value=None)) as mock_fn:
        r = client.post("/api/seer/sync/users")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    mock_fn.assert_awaited_once()


def test_seer_sync_requests_endpoint(client, db):
    with patch("app.scheduler.sync_seer_requests", new=AsyncMock(return_value=None)) as mock_fn:
        r = client.post("/api/seer/sync/requests")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    mock_fn.assert_awaited_once()
