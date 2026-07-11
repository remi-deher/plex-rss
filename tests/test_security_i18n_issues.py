from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.dependencies import require_admin, require_api_scope, require_auth
from app.main import app
from app.models import Base, LibraryItem, MediaIssue, Settings
from app.services.totp import _totp_at, generate_secret, verify_code


def _db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _client(db):
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, raise_server_exceptions=False)


def _cleanup():
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides.pop(get_db, None)


def test_totp_verifies_current_code():
    secret = generate_secret()
    code = _totp_at(secret, 1_700_000_000 // 30)
    assert verify_code(secret, code, at=1_700_000_000)
    assert not verify_code(secret, "000000", at=1_700_000_000)


def test_api_scope_rejects_missing_scope():
    db = _db()
    try:
        db.add(Settings(api_token="secret", api_token_scopes="requests:read"))
        db.commit()
        req = type("Req", (), {"headers": {"X-Api-Key": "secret"}, "session": {}})()
        dep = require_api_scope("requests:write")
        try:
            dep(req, db)
            raised = None
        except HTTPException as exc:
            raised = exc
        assert raised is not None
        assert raised.status_code == 403
    finally:
        db.close()


def test_create_media_issue_for_library_item():
    db = _db()
    client = _client(db)
    try:
        item = LibraryItem(title="Dune", media_type="movie", year=2021, tmdb_id="438631")
        db.add(item)
        db.commit()
        resp = client.post(
            "/api/media/issues",
            json={"library_id": item.id, "issue_type": "audio", "message": "VF absente"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Dune"
        assert data["status"] == "open"
        assert db.query(MediaIssue).count() == 1
    finally:
        _cleanup()
        db.close()


def test_i18n_catalog_english():
    db = _db()
    client = _client(db)
    try:
        db.add(Settings(default_locale="fr"))
        db.commit()
        resp = client.get("/api/i18n/catalog?locale=en")
        assert resp.status_code == 200
        data = resp.json()
        assert data["locale"] == "en"
        assert data["messages"]["media.issue.report"] == "Report an issue"
    finally:
        _cleanup()
        db.close()


def test_api_docs_requires_authentication():
    # Without dependency overrides (require_admin, require_auth), they should fail / redirect
    db = _db()
    # Create client without overrides
    from fastapi.testclient import TestClient

    from app.dependencies import require_admin
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app, raise_server_exceptions=False)
    try:
        resp = client.get("/api/docs")
        # should redirect or return 401/403
        assert resp.status_code in (401, 403, 302)
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()


@patch("app.routers.library_api.sonarr.search_series", new_callable=AsyncMock)
def test_retry_issue_media_search_endpoint(mock_search_series):
    mock_search_series.return_value = True
    db = _db()
    client = _client(db)
    try:
        from app.models import ArrInstance, MediaRequest
        inst = ArrInstance(name="Sonarr", arr_type="sonarr", url="http://sonarr", api_key="key", enabled=True)
        db.add(inst)
        db.commit()

        req = MediaRequest(
            title="Silo",
            media_type="show",
            status="failed",
            arr_id=12,
            arr_instance_id=inst.id,
            plex_user_id="alice"
        )
        db.add(req)
        db.commit()

        issue = MediaIssue(
            title="Silo",
            media_type="show",
            issue_type="audio",
            status="open",
            request_id=req.id
        )
        db.add(issue)
        db.commit()

        resp = client.post(f"/api/media/issues/{issue.id}/retry")
        assert resp.status_code == 200
        assert resp.json() == {"success": True}
        mock_search_series.assert_called_once_with("http://sonarr", "key", 12)
    finally:
        _cleanup()
        db.close()


@patch("app.services.plex_api.check_auth_pin", new_callable=AsyncMock)
@patch("app.routers.auth.get_plex_account", new_callable=AsyncMock)
@patch("app.routers.auth.has_server_access", new_callable=AsyncMock)
def test_plex_sso_server_access_control(mock_has_access, mock_get_account, mock_check_pin):
    mock_check_pin.return_value = "token123"
    mock_get_account.return_value = {
        "uuid": "uuid123",
        "username": "user123",
        "email": "user123@gmail.com",
        "thumb": "http://thumb"
    }

    db = _db()
    s = db.query(Settings).first()
    if not s:
        s = Settings(id=1, plex_token="admin_plex_token")
        db.add(s)
    else:
        s.plex_token = "admin_plex_token"
    db.commit()

    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app, raise_server_exceptions=False)

    try:
        # Case 1: Unauthorized user
        mock_has_access.return_value = False
        resp = client.get("/login/plex/check/123")
        assert resp.status_code == 403
        assert "n'a pas accès au serveur" in resp.json()["detail"]

        # Case 2: Authorized user
        mock_has_access.return_value = True
        resp = client.get("/login/plex/check/123")
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is True
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
