"""Small async cache facade with an in-memory fallback.

Redis is optional for local development.  A transient Redis outage must never
make an API request fail, so callers keep the same behaviour with a process
local cache until the connection is available again.
"""

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)


class Cache:
    def __init__(self) -> None:
        self._memory: dict[str, tuple[str, float]] = {}
        self._redis = None
        self._attempted_connection = False

    async def _client(self):
        if self._attempted_connection:
            return self._redis
        self._attempted_connection = True
        url = os.getenv("REDIS_URL")
        if not url:
            return None
        try:
            from redis.asyncio import Redis

            client = Redis.from_url(url, encoding="utf-8", decode_responses=True)
            await client.ping()
            self._redis = client
            logger.info("Redis cache connected")
        except Exception as exc:
            logger.warning("Redis unavailable; using process-local cache: %s", exc)
        return self._redis

    async def get_json(self, key: str) -> dict[str, Any] | None:
        raw = None
        client = await self._client()
        if client:
            try:
                raw = await client.get(key)
            except Exception as exc:
                logger.warning("Redis read failed: %s", exc)
        if raw is None:
            memory_item = self._memory.get(key)
            if memory_item and memory_item[1] > time.monotonic():
                raw = memory_item[0]
            elif memory_item:
                self._memory.pop(key, None)
        if not raw:
            return None
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None

    async def set_json(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        raw = json.dumps(value)
        self._memory[key] = (raw, time.monotonic() + ttl_seconds)
        client = await self._client()
        if client:
            try:
                await client.set(key, raw, ex=ttl_seconds)
            except Exception as exc:
                logger.warning("Redis write failed: %s", exc)

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()


cache = Cache()
