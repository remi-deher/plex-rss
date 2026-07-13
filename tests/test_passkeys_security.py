from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# In-memory SQLite DB for tests
from sqlalchemy.pool import StaticPool

from app.database import get_db_async as get_db
from app.dependencies import current_user
from app.main import app
from app.models import Base, PasskeyCredential, PlexUser, Settings
from app.services.auth import hash_password, verify_password
from tests.async_support import TestSession

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _db():
    Base.metadata.create_all(bind=engine)
    db = TestSession(TestingSessionLocal())
    # Seed default settings
    s = Settings(id=1, auth_username="admin", auth_password_hash=hash_password("adminpass"))
    db.add(s)
    db.commit()
    return db


def _cleanup():
    Base.metadata.drop_all(bind=engine)


def test_password_and_totp_security():
    db = _db()
    # Add local users
    user1 = PlexUser(
        plex_user_id="user1",
        display_name="User One",
        role="user",
        source="local",
        password_hash=hash_password("oldpass"),
    )
    user2 = PlexUser(
        plex_user_id="user2",
        display_name="User Two",
        role="user",
        source="local",
        password_hash=hash_password("user2pass"),
    )
    db.add(user1)
    db.add(user2)
    db.commit()

    # Refresh objects
    db.refresh(user1)
    db.refresh(user2)

    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app, raise_server_exceptions=True)

    try:
        # Case 1: Unauthorized password change (no session)
        resp = client.post(f"/api/users/{user1.id}/password", json={"password": "newpass"})
        assert resp.status_code == 401

        # Case 2: Unauthorized password change (different user)
        app.dependency_overrides[current_user] = lambda: {"id": user2.id, "role": "user"}
        resp = client.post(f"/api/users/{user1.id}/password", json={"password": "newpass"})
        assert resp.status_code == 403

        # Case 3: Authorized password change (self)
        app.dependency_overrides[current_user] = lambda: {"id": user1.id, "role": "user"}
        resp = client.post(f"/api/users/{user1.id}/password", json={"password": "newpass"})
        assert resp.status_code == 200

        # Verify password changed
        db.refresh(user1)
        assert verify_password("newpass", user1.password_hash)

        # Case 4: TOTP Setup (self)
        resp = client.post(f"/api/users/{user1.id}/totp/setup")
        assert resp.status_code == 200
        data = resp.json()
        assert "secret" in data
        assert "uri" in data

        db.refresh(user1)
        assert user1.totp_secret == data["secret"]
        assert user1.totp_enabled is False

        # Case 5: TOTP Enable with bad code
        resp = client.post(f"/api/users/{user1.id}/totp/enable", json={"code": "111111"})
        assert resp.status_code == 400

        # Case 6: TOTP Enable with correct code
        with patch("app.routers.security_api.verify_code", return_value=True):
            resp = client.post(f"/api/users/{user1.id}/totp/enable", json={"code": "123456"})
            assert resp.status_code == 200
            db.refresh(user1)
            assert user1.totp_enabled is True

        # Case 7: TOTP Disable
        resp = client.delete(f"/api/users/{user1.id}/totp")
        assert resp.status_code == 200
        db.refresh(user1)
        assert user1.totp_secret is None
        assert user1.totp_enabled is False

    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(current_user, None)
        _cleanup()
        db.close()


def current_user_override(user_id, role):
    return lambda: {"id": user_id, "role": role}


@patch("app.routers.security_api.generate_registration_options")
def test_webauthn_registration_options(mock_gen):
    db = _db()
    user1 = PlexUser(plex_user_id="user1", display_name="User One", role="user", source="local")
    db.add(user1)
    db.commit()
    db.refresh(user1)

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: {"id": user1.id, "role": "user"}
    client = TestClient(app, raise_server_exceptions=False)

    try:
        mock_opts = MagicMock()
        mock_opts.challenge = b"challenge_bytes"
        mock_gen.return_value = mock_opts

        with patch(
            "app.routers.security_api.options_to_json",
            return_value='{"challenge": "challenge_str", "rp": {}, "user": {}}',
        ):
            resp = client.post("/api/users/webauthn/register/options", json={"user_id": user1.id})
            assert resp.status_code == 200
            assert resp.json()["challenge"] == "challenge_str"

    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(current_user, None)
        _cleanup()
        db.close()
