import asyncio
import os
import json
import pytest
from unittest import mock

from app.realtime import publish, subscribe, STREAM_KEY, EVENT_TYPES

pytestmark = pytest.mark.asyncio

@pytest.fixture
async def redis_client():
    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    from redis.asyncio import Redis
    try:
        client = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
        await client.ping()
        yield client
        await client.flushdb()
        await client.aclose()
    except Exception:
        pytest.skip("Redis server not available for test")

@pytest.fixture
def mock_env():
    with mock.patch.dict(os.environ, {"REDIS_URL": "redis://127.0.0.1:6379/0"}):
        yield

async def test_publish_and_subscribe(redis_client, mock_env):
    user = {"role": "admin"}
    
    # Subscribe in the background
    events = []
    
    async def subscriber():
        async for event in subscribe("$", user):
            if event is not None:
                events.append(event)
                break
                
    sub_task = asyncio.create_task(subscriber())
    
    # Wait a bit to ensure subscription starts
    await asyncio.sleep(0.1)
    
    # Publish an event
    event_id = await publish("request.updated", {"test": "data"})
    
    # Wait for the event
    await asyncio.wait_for(sub_task, timeout=2.0)
    
    assert len(events) == 1
    assert events[0]["type"] == "request.updated"
    assert events[0]["payload"] == {"test": "data"}
    assert events[0]["id"] == event_id

async def test_publish_invalid_type(mock_env):
    with pytest.raises(ValueError, match="Unsupported event type"):
        await publish("invalid.type")

async def test_subscribe_permissions(redis_client, mock_env):
    admin_user = {"role": "admin"}
    normal_user = {"id": 123, "role": "user"}
    
    # Publish an admin-only event
    await publish("health.updated", {"status": "ok"}, admin_only=True)
    
    # Test admin can read
    admin_iterator = subscribe("0-0", admin_user)
    admin_event = await asyncio.wait_for(anext(admin_iterator), timeout=2.0)
    assert admin_event is not None
    assert admin_event["type"] == "health.updated"
    
    # Test normal user cannot read
    normal_iterator = subscribe("0-0", normal_user)
    try:
        await asyncio.wait_for(anext(normal_iterator), timeout=0.5)
        pytest.fail("Normal user should not receive admin event")
    except asyncio.TimeoutError:
        pass # Expected
