import pytest

from app.models import FulfillmentStatus, MediaRequest, PlexUser, RequestStatus, Settings
from app.services.notification_policy import (
    dispatch_transition_notification,
    has_transition_notification_intent,
    request_notification_is_eligible,
)
from app.services.request_lifecycle import transition_request


def _request(**kwargs):
    values = {
        "plex_user_id": "alice",
        "title": "Dune",
        "media_type": "movie",
        "status": RequestStatus.pending,
    }
    values.update(kwargs)
    return MediaRequest(**values)


@pytest.mark.asyncio
async def test_transition_separates_business_and_fulfillment_state(async_db):
    req = _request()
    async_db.add(req)
    async_db.commit()

    await transition_request(async_db, req, "submitted", source="radarr")
    await transition_request(async_db, req, "download_started", source="radarr")
    await async_db.commit()

    assert req.status == RequestStatus.sent_to_arr
    assert req.fulfillment_status == FulfillmentStatus.downloading
    assert req.is_downloading is True
    assert req.arr_processed_at is not None


@pytest.mark.asyncio
async def test_available_transition_is_idempotent(async_db):
    req = _request(status=RequestStatus.sent_to_arr)
    async_db.add(req)
    async_db.commit()

    first = await transition_request(async_db, req, "available", source="plex")
    available_at = req.available_at
    second = await transition_request(async_db, req, "available", source="plex")

    assert first is True
    assert second is False
    assert req.status == RequestStatus.available
    assert req.fulfillment_status == FulfillmentStatus.completed
    assert req.available_at == available_at


@pytest.mark.asyncio
async def test_failure_and_retry_preserve_structured_error(async_db):
    req = _request(status=RequestStatus.sent_to_arr)
    async_db.add(req)
    async_db.commit()

    await transition_request(async_db, req, "failed", source="radarr", error="HTTP 503")
    assert req.status == RequestStatus.failed
    assert req.fulfillment_status == FulfillmentStatus.failed
    assert req.fulfillment_error == "HTTP 503"

    await transition_request(async_db, req, "retry", source="manual")
    assert req.status == RequestStatus.pending
    assert req.fulfillment_status == FulfillmentStatus.awaiting_submission
    assert req.fulfillment_error is None


@pytest.mark.asyncio
async def test_transition_produces_notification_intent_only_when_state_changes(async_db):
    req = _request(source="rss")
    async_db.add(req)
    async_db.commit()

    first = await transition_request(async_db, req, "submitted", source="radarr")
    second = await transition_request(async_db, req, "submitted", source="radarr")

    assert first is True
    assert second is False
    assert has_transition_notification_intent(req, "submitted") is True


@pytest.mark.asyncio
async def test_technical_origins_and_pseudo_requesters_cannot_notify(async_db):
    real_user = PlexUser(plex_user_id="alice", enabled=True)
    arr_origin = _request(plex_user_id="alice", source="arr_sync")
    pseudo = _request(plex_user_id="manual", source="manual_search")
    user_request = _request(plex_user_id="alice", source="rss")
    async_db.add_all([real_user, arr_origin, pseudo, user_request])
    async_db.commit()

    assert await request_notification_is_eligible(arr_origin, async_db) is False
    assert await request_notification_is_eligible(pseudo, async_db) is False
    assert await request_notification_is_eligible(user_request, async_db) is True


@pytest.mark.asyncio
async def test_dispatch_uses_transition_intent_and_origin_policy(async_db, monkeypatch):
    from unittest.mock import AsyncMock

    notify = AsyncMock()
    monkeypatch.setattr("app.services.notification_orchestrator._notify", notify)
    settings = Settings()
    user = PlexUser(plex_user_id="alice", enabled=True)
    req = _request(plex_user_id="alice", source="rss")
    async_db.add_all([settings, user, req])
    async_db.commit()

    await transition_request(async_db, req, "submitted", source="radarr")
    await async_db.commit()
    dispatched = await dispatch_transition_notification(settings, req, async_db, "submitted")
    dispatched_again = await dispatch_transition_notification(settings, req, async_db, "submitted")

    assert dispatched is True
    assert dispatched_again is False
    notify.assert_awaited_once()
