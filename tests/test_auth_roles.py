"""Tests for asynchronous authentication and role dependencies."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.dependencies import current_user, require_admin, require_auth
from app.models import Settings
from tests.async_support import make_test_session


def _request(session: dict | None = None, api_key: str | None = None):
    request = MagicMock()
    request.session = session or {}
    request.headers = {"X-Api-Key": api_key} if api_key else {}
    return request


def _db_with_token(token: str | None):
    db = make_test_session()
    db.add(Settings(api_token=token))
    db.commit()
    return db


@pytest.mark.asyncio
async def test_anonymous_is_rejected_by_require_auth():
    with pytest.raises(HTTPException) as exc:
        await require_auth(_request(), _db_with_token(None))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_owner_session_passes_auth_and_admin():
    request = _request({"authenticated": True, "is_owner": True, "role": "admin"})
    db = _db_with_token(None)
    await require_auth(request, db)
    await require_admin(request, db)


@pytest.mark.asyncio
async def test_plex_user_passes_auth_but_not_admin():
    request = _request(
        {"authenticated": True, "is_owner": False, "role": "user", "plex_user_id": "alice"}
    )
    db = _db_with_token(None)
    await require_auth(request, db)
    with pytest.raises(HTTPException) as exc:
        await require_admin(request, db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_role_session_passes_admin():
    request = _request(
        {"authenticated": True, "is_owner": False, "role": "admin", "plex_user_id": "bob"}
    )
    await require_admin(request, _db_with_token(None))


@pytest.mark.asyncio
async def test_api_key_no_longer_admin_level():
    request = _request(api_key="secret")
    db = _db_with_token("secret")
    await require_auth(request, db)

    with pytest.raises(HTTPException) as exc:
        await require_admin(request, db)
    assert exc.value.status_code == 401
    assert current_user(request, db) is None


def test_current_user_none_when_anonymous():
    assert current_user(_request(), _db_with_token(None)) is None
