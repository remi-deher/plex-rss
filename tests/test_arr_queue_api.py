from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cache import cache
from app.models import ArrInstance, Base, MediaRequest
from app.routers.arr_queue_api import arr_download_queue
from tests.async_support import TestSession


@pytest.mark.asyncio
async def test_arr_queue_links_only_current_remote_records():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = TestSession(sessionmaker(bind=engine)())
    instance = ArrInstance(
        id=1, name="Sonarr", arr_type="sonarr", url="http://sonarr", api_key="key", enabled=True
    )
    linked = MediaRequest(
        id=10, plex_user_id="alice", title="Linked", media_type="show",
        arr_instance_id=1, arr_id=42, status="sent_to_arr",
    )
    db.add_all([instance, linked])
    db.commit()
    cache._memory.clear()
    remote = [{"arr_media_id": 42, "title": "Linked", "progress": 50, "poster_url": None}]

    with patch(
        "app.routers.arr_queue_api.fetch_instance_queue", new=AsyncMock(return_value=remote)
    ) as fetch:
        rows = await arr_download_queue(db)

    assert rows[0]["linked_request_id"] == 10
    fetch.assert_awaited_once()
