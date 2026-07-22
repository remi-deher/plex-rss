from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_db_async as get_db
from app.dependencies import require_admin, require_auth
from app.main import app
from app.models import MediaRequest, PlexUser, Settings

API_TOKEN = "test-api-token"


def _client_with_db(db):
    """Client de test avec un token API valide (scope "*") en DB : les routes /api/v1/*
    exigent require_api_scope, qui vérifie l'en-tête X-Api-Key indépendamment de
    require_auth/require_admin (surchargés ici pour les autres dépendances des routes)."""
    db.add(Settings(api_token=API_TOKEN, api_token_scopes="*"))
    db.commit()
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app, raise_server_exceptions=False, headers={"X-Api-Key": API_TOKEN})
    return client


def _cleanup():
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides.pop(get_db, None)


def test_api_v1_requests_list(async_db):
    req = MediaRequest(
        id=1, plex_user_id="alice", plex_user="alice", title="Inception", media_type="movie", status="pending"
    )
    async_db.add(req)
    async_db.commit()
    client = _client_with_db(async_db)
    try:
        resp = client.get("/api/v1/requests?status=pending&media_type=movie")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Inception"
    finally:
        _cleanup()


def test_api_v1_users_list(async_db):
    user = PlexUser(
        id=1,
        plex_user_id="alice",
        display_name="Alice",
        enabled=True,
        notify_admin=True,
        notify_on_request=True,
        notify_on_available=True,
        created_at=None,
        sonarr_instance_id=None,
        radarr_instance_id=None,
    )
    async_db.add(user)
    async_db.commit()
    client = _client_with_db(async_db)
    try:
        resp = client.get("/api/v1/users")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["display_name"] == "Alice"
    finally:
        _cleanup()


def test_api_v1_requests_list_rejects_missing_credentials(async_db):
    """require_api_scope doit échouer fermé (401) sans session ni X-Api-Key — sans
    ce garde, /api/v1/* serait accessible sans aucune authentification."""
    async_db.add(Settings(api_token=API_TOKEN, api_token_scopes="*"))
    async_db.commit()
    app.dependency_overrides[get_db] = lambda: async_db
    client = TestClient(app, raise_server_exceptions=False)
    try:
        resp = client.get("/api/v1/requests")
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)
