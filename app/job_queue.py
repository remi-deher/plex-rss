"""ARQ queue helpers shared by API routes and notification producers."""

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def arq_enabled() -> bool:
    return bool(os.getenv("REDIS_URL")) and os.getenv("ENABLE_ARQ", "1").lower() not in {"0", "false", "no"}


async def enqueue_job(function: str, *args: Any, job_id: str | None = None, **kwargs: Any) -> str | None:
    """Enqueue an ARQ job and return its id; failures remain visible to callers."""
    if not arq_enabled():
        return None
    from arq.connections import RedisSettings, create_pool

    redis = await create_pool(RedisSettings.from_dsn(os.environ["REDIS_URL"]))
    try:
        job = await redis.enqueue_job(function, *args, _job_id=job_id, _queue_name="plexarr:jobs", **kwargs)
        return job.job_id if job else job_id
    finally:
        await redis.aclose()


async def set_json(key: str, value: dict[str, Any], ttl: int = 86400) -> None:
    from redis.asyncio import Redis

    redis = Redis.from_url(os.environ["REDIS_URL"], encoding="utf-8", decode_responses=True)
    try:
        await redis.set(key, json.dumps(value, ensure_ascii=True), ex=ttl)
    finally:
        await redis.aclose()


async def get_json(key: str) -> dict[str, Any] | None:
    from redis.asyncio import Redis

    redis = Redis.from_url(os.environ["REDIS_URL"], encoding="utf-8", decode_responses=True)
    try:
        raw = await redis.get(key)
        return json.loads(raw) if raw else None
    finally:
        await redis.aclose()
