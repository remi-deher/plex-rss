import pytest

from app.models import FulfillmentStatus, MediaRequest, RequestStatus
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
