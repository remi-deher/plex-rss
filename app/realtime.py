"""Versioned real-time events backed by Redis Streams with a local fallback."""

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

from .utils import now_utc

logger = logging.getLogger(__name__)
STREAM_KEY = "plexarr:events:v1"
CHANNEL = "plexarr:events"
EVENT_TYPES = {
    "request.updated",
    "download.updated",
    "health.updated",
    "job.updated",
    "notification.updated",
}
_subscribers: set[asyncio.Queue] = set()


def _allowed(event: dict[str, Any], user: dict[str, Any]) -> bool:
    is_admin = bool(user.get("is_owner") or user.get("role") == "admin")
    if event.get("admin_only"):
        return is_admin
    target = event.get("user_id")
    if target is None or is_admin:
        return True
    return str(target) in {str(user.get("id")), str(user.get("plex_user_id"))}


async def publish(
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    user_id: str | int | None = None,
    admin_only: bool = False,
) -> str:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unsupported event type: {event_type}")
    event = {
        "version": 1,
        "type": event_type,
        "occurred_at": now_utc().isoformat(),
        "user_id": user_id,
        "admin_only": admin_only,
        "payload": payload or {},
    }
    raw = json.dumps(event, ensure_ascii=True)
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        try:
            from redis.asyncio import Redis

            redis = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
            try:
                event_id = await redis.xadd(STREAM_KEY, {"event": raw}, maxlen=1000, approximate=True)
                event["id"] = event_id
                await redis.publish(CHANNEL, json.dumps(event, ensure_ascii=True))
                return str(event_id)
            finally:
                await redis.aclose()
        except Exception as exc:
            logger.warning("Redis event publish failed; using local subscribers: %s", exc)
    event_id = f"local-{int(now_utc().timestamp() * 1000)}"
    event["id"] = event_id
    for queue in tuple(_subscribers):
        queue.put_nowait(event)
    return event_id


async def subscribe(last_event_id: str | None, user: dict[str, Any]) -> AsyncIterator[dict[str, Any] | None]:
    """Yield permitted events; ``None`` is a heartbeat."""
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        from redis.asyncio import Redis

        redis = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
        cursor = last_event_id if last_event_id and not last_event_id.startswith("local-") else "$"
        try:
            while True:
                rows = await redis.xread({STREAM_KEY: cursor}, count=100, block=15000)
                if not rows:
                    yield None
                    continue
                for _, messages in rows:
                    for event_id, fields in messages:
                        cursor = event_id
                        try:
                            event = json.loads(fields["event"])
                        except (KeyError, json.JSONDecodeError):
                            continue
                        event["id"] = event_id
                        if _allowed(event, user):
                            yield event
        finally:
            await redis.aclose()
    else:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        _subscribers.add(queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    if _allowed(event, user):
                        yield event
                except asyncio.TimeoutError:
                    yield None
        finally:
            _subscribers.discard(queue)
