"""Routing contracts for the root Vue SPA and public authentication pages."""

import pytest
from fastapi.testclient import TestClient

from app.database import get_db_async
from app.dependencies import require_admin
from app.main import app
from app.models import PlexUser, Settings
from app.services.auth import hash_password


@pytest.fixture()
def db(async_db):
    return async_db


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db_async] = lambda: db
    app.dependency_overrides[require_admin] = lambda: None
    browser = TestClient(app, raise_server_exceptions=True, follow_redirects=False)
    yield browser
    app.dependency_overrides.pop(get_db_async, None)
    app.dependency_overrides.pop(require_admin, None)


def _seed_account(db, username="admin", password="password123"):
    password_hash = hash_password(password)
    db.add(Settings(id=1, auth_username=username, auth_password_hash=password_hash))
    db.add(
        PlexUser(
            plex_user_id=username,
            display_name="Administrateur",
            role="admin",
            can_login=True,
            enabled=True,
            source="local",
            password_hash=password_hash,
        )
    )
    db.commit()


def _login(client, username="admin", password="password123"):
    return client.post("/login", data={"username": username, "password": password, "otp_code": ""})


def test_root_redirects_anonymous_user_to_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_spa_is_served_at_root_after_login(client, db):
    _seed_account(db)
    login = _login(client)
    assert login.status_code == 302

    response = client.get("/")
    assert response.status_code == 200
    assert '<div id="app"></div>' in response.text
    assert "/vue/assets/" in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/dashboard",
        "/discover",
        "/downloads",
        "/requests",
        "/library",
        "/calendar",
        "/users",
        "/notifications",
        "/logs",
        "/settings",
        "/maintenance",
        "/profile",
        "/releases/42",
    ],
)
def test_vue_history_routes_return_spa(client, db, path):
    _seed_account(db)
    _login(client)
    response = client.get(path)
    assert response.status_code == 200
    assert '<div id="app"></div>' in response.text


def test_old_app_prefix_redirects_to_root_route(client):
    response = client.get("/app/requests")
    assert response.status_code == 308
    assert response.headers["location"] == "/requests"


@pytest.mark.parametrize(
    ("path", "destination"),
    [
        ("/templates", "/settings?tab=templates"),
        ("/setup/wizard", "/settings?tab=connections"),
    ],
)
def test_old_page_bookmarks_redirect_to_vue(client, path, destination):
    response = client.get(path)
    assert response.status_code == 308
    assert response.headers["location"] == destination


def test_unknown_api_route_stays_404(client, db):
    _seed_account(db)
    _login(client)
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_login_page_remains_public(client, db):
    _seed_account(db)
    response = client.get("/login")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_setup_page_remains_public_on_empty_database(client):
    response = client.get("/setup")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_login_rejects_wrong_password(client, db):
    _seed_account(db)
    response = _login(client, password="wrong-password")
    assert response.status_code == 200
    assert "Identifiants incorrects" in response.text


def test_logout_returns_to_login(client, db):
    _seed_account(db)
    _login(client)
    response = client.get("/logout")
    assert response.status_code == 302
    assert response.headers["location"] == "/login"
