"""Tests de la logique de rôles : require_auth / require_admin / current_user."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.dependencies import current_user, require_admin, require_auth


def _request(session: dict | None = None, api_key: str | None = None):
    req = MagicMock()
    req.session = session or {}
    req.headers = {"X-Api-Key": api_key} if api_key else {}
    return req


def _db_with_token(token: str | None):
    db = MagicMock()
    settings = MagicMock()
    settings.api_token = token
    db.query.return_value.first.return_value = settings
    return db


def test_anonymous_is_rejected_by_require_auth():
    with pytest.raises(HTTPException) as exc:
        require_auth(_request(), _db_with_token(None))
    assert exc.value.status_code == 401


def test_owner_session_passes_auth_and_admin():
    req = _request({"authenticated": True, "is_owner": True, "role": "admin"})
    db = _db_with_token(None)
    require_auth(req, db)  # ne lève pas
    require_admin(req, db)  # ne lève pas


def test_plex_user_passes_auth_but_not_admin():
    req = _request({"authenticated": True, "is_owner": False, "role": "user", "plex_user_id": "alice"})
    db = _db_with_token(None)
    require_auth(req, db)  # ne lève pas
    with pytest.raises(HTTPException) as exc:
        require_admin(req, db)
    assert exc.value.status_code == 403


def test_admin_role_session_passes_admin():
    req = _request({"authenticated": True, "is_owner": False, "role": "admin", "plex_user_id": "bob"})
    require_admin(req, _db_with_token(None))  # ne lève pas


def test_api_key_no_longer_admin_level():
    req = _request(api_key="secret")
    db = _db_with_token("secret")
    require_auth(req, db)  # require_auth l'accepte toujours (pour api_v1)
    
    with pytest.raises(HTTPException) as exc:
        require_admin(req, db)
    assert exc.value.status_code == 401

    user = current_user(req, db)
    assert user is None


def test_current_user_none_when_anonymous():
    assert current_user(_request(), _db_with_token(None)) is None
