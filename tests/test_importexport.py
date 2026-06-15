"""Tests unitaires pour routers/importexport.py (export et import de données)."""

import io
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base, MediaRequest, PlexUser, Settings
from app.routers.importexport import require_auth as ie_require_auth


# ---------------------------------------------------------------------------
# Base de données en mémoire partagée entre les tests du module
# StaticPool : toutes les connexions (y compris le thread du TestClient)
# utilisent la même connexion SQLite → même DB en mémoire.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[ie_require_auth] = lambda: None
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    app.dependency_overrides.pop(ie_require_auth, None)
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# GET /api/export
# ---------------------------------------------------------------------------


def test_export_returns_json_with_version(client, db_session):
    r = client.get("/api/export")
    assert r.status_code == 200
    data = r.json()
    assert data["version"] == 1
    assert "exported_at" in data
    assert "settings" in data
    assert "users" in data
    assert "requests" in data


def test_export_includes_settings(client, db_session):
    db_session.query(Settings).delete()
    s = Settings(id=1, smtp_host="smtp.example.com", smtp_from="noreply@example.com")
    db_session.add(s)
    db_session.commit()

    r = client.get("/api/export")
    assert r.status_code == 200
    data = r.json()
    assert data["settings"]["smtp_host"] == "smtp.example.com"


def test_export_includes_users(client, db_session):
    db_session.query(PlexUser).delete()
    u = PlexUser(plex_user_id="alice", display_name="Alice", enabled=True)
    db_session.add(u)
    db_session.commit()

    r = client.get("/api/export")
    users = r.json()["users"]
    assert any(u["plex_user_id"] == "alice" for u in users)


def test_export_content_disposition(client, db_session):
    r = client.get("/api/export")
    assert "attachment" in r.headers.get("content-disposition", "")
    assert ".json" in r.headers.get("content-disposition", "")


# ---------------------------------------------------------------------------
# POST /api/import — erreurs
# ---------------------------------------------------------------------------


def test_import_invalid_json_returns_400(client):
    r = client.post("/api/import", files={"file": ("export.json", b"NOT JSON", "application/json")})
    assert r.status_code == 400


def test_import_wrong_version_returns_400(client):
    payload = json.dumps({"version": 99, "settings": {}, "users": [], "requests": []}).encode()
    r = client.post("/api/import", files={"file": ("export.json", payload, "application/json")})
    assert r.status_code == 400
    assert "version" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /api/import — succès
# ---------------------------------------------------------------------------


def test_import_creates_settings(client, db_session):
    db_session.query(Settings).delete()
    db_session.commit()

    payload = json.dumps({
        "version": 1,
        "settings": {"smtp_host": "smtp.test.com", "smtp_from": "test@test.com"},
        "users": [],
        "requests": [],
    }).encode()
    r = client.post("/api/import", files={"file": ("export.json", payload, "application/json")})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["stats"]["settings"] is True

    s = db_session.query(Settings).first()
    assert s is not None
    assert s.smtp_host == "smtp.test.com"


def test_import_upserts_users(client, db_session):
    db_session.query(PlexUser).delete()
    db_session.commit()

    payload = json.dumps({
        "version": 1,
        "settings": {},
        "users": [
            {"plex_user_id": "bob", "display_name": "Bob", "enabled": True},
            {"plex_user_id": "carol", "display_name": "Carol", "enabled": False},
        ],
        "requests": [],
    }).encode()
    r = client.post("/api/import", files={"file": ("export.json", payload, "application/json")})
    assert r.status_code == 200
    assert r.json()["stats"]["users_upserted"] == 2

    users = db_session.query(PlexUser).all()
    assert any(u.plex_user_id == "bob" for u in users)


def test_import_upserts_requests(client, db_session):
    db_session.query(MediaRequest).delete()
    db_session.query(PlexUser).delete()
    db_session.commit()

    payload = json.dumps({
        "version": 1,
        "settings": {},
        "users": [],
        "requests": [
            {
                "plex_user_id": "alice",
                "title": "Dune",
                "media_type": "movie",
                "status": "sent_to_arr",
            }
        ],
    }).encode()
    r = client.post("/api/import", files={"file": ("export.json", payload, "application/json")})
    assert r.status_code == 200
    assert r.json()["stats"]["requests_upserted"] == 1

    req = db_session.query(MediaRequest).filter(MediaRequest.title == "Dune").first()
    assert req is not None


def test_import_does_not_overwrite_smtp_password_if_empty(client, db_session):
    db_session.query(Settings).delete()
    s = Settings(id=1, smtp_password="secret123")
    db_session.add(s)
    db_session.commit()

    payload = json.dumps({
        "version": 1,
        "settings": {"smtp_password": ""},
        "users": [],
        "requests": [],
    }).encode()
    client.post("/api/import", files={"file": ("export.json", payload, "application/json")})

    db_session.expire_all()
    s = db_session.query(Settings).first()
    assert s.smtp_password == "secret123"


def test_import_idempotent_on_second_call(client, db_session):
    """Importer deux fois le même payload ne doit pas créer de doublons."""
    db_session.query(PlexUser).delete()
    db_session.commit()

    payload = json.dumps({
        "version": 1,
        "settings": {},
        "users": [{"plex_user_id": "dave", "display_name": "Dave"}],
        "requests": [],
    }).encode()

    client.post("/api/import", files={"file": ("export.json", payload, "application/json")})
    client.post("/api/import", files={"file": ("export.json", payload, "application/json")})

    count = db_session.query(PlexUser).filter(PlexUser.plex_user_id == "dave").count()
    assert count == 1
