"""Rôle "moderator" et garde anti-auto-verrouillage sur /api/users.

Un admin qui se retire son propre rôle admin (ou se supprime lui-même) via
update_user/bulk_update_permissions/delete_user/bulk_delete_users ne devait rien en
empêcher jusque-là — risque de verrouillage silencieux hors de son propre compte.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, PlexUser
from app.routers.users_api import (
    BulkDeleteUpdate,
    BulkPermissionsUpdate,
    UserCreate,
    bulk_delete_users,
    bulk_update_permissions,
    delete_user,
    update_user,
)
from tests.async_support import TestSession


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = TestSession(sessionmaker(bind=engine)())
    yield session
    session.close()


def _request(user_id: int | None = None):
    request = MagicMock()
    request.session = {"authenticated": True, "is_owner": False, "role": "admin", "user_id": user_id}
    return request


def _user(db, **kwargs) -> PlexUser:
    defaults = dict(plex_user_id="alice", display_name="Alice", role="admin")
    defaults.update(kwargs)
    u = PlexUser(**defaults)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _payload(**overrides) -> UserCreate:
    base = dict(plex_user_id="alice", display_name="Alice", role="user")
    base.update(overrides)
    return UserCreate(**base)


@pytest.mark.asyncio
async def test_update_user_accepts_moderator_role(db):
    """`role="moderator"` doit être accepté par la validation (whitelist élargie)."""
    admin = _user(db)
    result = await update_user(admin.id, _payload(role="moderator"), _request(user_id=999), db)
    assert result.role == "moderator"


@pytest.mark.asyncio
async def test_update_user_blocks_self_demotion(db):
    admin = _user(db)
    with pytest.raises(HTTPException) as exc:
        await update_user(admin.id, _payload(role="user"), _request(user_id=admin.id), db)
    assert exc.value.status_code == 400
    db.refresh(admin)
    assert admin.role == "admin"


@pytest.mark.asyncio
async def test_update_user_allows_demoting_someone_else(db):
    caller = _user(db, plex_user_id="caller", role="admin")
    other = _user(db, plex_user_id="other", role="admin")
    result = await update_user(other.id, _payload(plex_user_id="other", role="user"), _request(user_id=caller.id), db)
    assert result.role == "user"


@pytest.mark.asyncio
async def test_update_user_allows_other_self_edits(db):
    admin = _user(db)
    result = await update_user(
        admin.id, _payload(role="admin", display_name="Alice B"), _request(user_id=admin.id), db
    )
    assert result.display_name == "Alice B"
    assert result.role == "admin"


@pytest.mark.asyncio
async def test_delete_user_blocks_self_delete(db):
    admin = _user(db)
    with pytest.raises(HTTPException) as exc:
        await delete_user(admin.id, _request(user_id=admin.id), db)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_delete_user_allows_deleting_someone_else(db):
    caller = _user(db, plex_user_id="caller")
    other = _user(db, plex_user_id="other")
    result = await delete_user(other.id, _request(user_id=caller.id), db)
    assert result["status"] == "deleted"


@pytest.mark.asyncio
async def test_bulk_update_permissions_blocks_self_demotion(db):
    admin = _user(db)
    with pytest.raises(HTTPException) as exc:
        await bulk_update_permissions(
            BulkPermissionsUpdate(user_ids=[admin.id], role="moderator"), _request(user_id=admin.id), db
        )
    assert exc.value.status_code == 400
    db.refresh(admin)
    assert admin.role == "admin"


@pytest.mark.asyncio
async def test_bulk_update_permissions_allows_others(db):
    caller = _user(db, plex_user_id="caller")
    other = _user(db, plex_user_id="other")
    result = await bulk_update_permissions(
        BulkPermissionsUpdate(user_ids=[other.id], role="moderator"), _request(user_id=caller.id), db
    )
    assert result["updated"] == 1
    db.refresh(other)
    assert other.role == "moderator"


@pytest.mark.asyncio
async def test_bulk_delete_users_blocks_self(db):
    admin = _user(db)
    with pytest.raises(HTTPException) as exc:
        await bulk_delete_users(BulkDeleteUpdate(user_ids=[admin.id]), _request(user_id=admin.id), db)
    assert exc.value.status_code == 400
