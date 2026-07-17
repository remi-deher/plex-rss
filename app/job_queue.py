"""ARQ queue helpers shared by API routes and notification producers."""

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

RESYNC_NOTIFICATION_BASELINE_PREFIX = "plexarr:resync:availability-baseline:"
RESYNC_EXTERNAL_EVENT_PREFIX = "plexarr:resync:external-event:"
_local_resync_notification_baselines: dict[int, dict[str, Any]] = {}


def availability_notification_signature(request: Any) -> dict[str, Any]:
    """État minimal permettant de distinguer un ancien état d'un vrai progrès."""
    status = getattr(request, "status", None)
    return {
        "status": status.value if hasattr(status, "value") else str(status),
        "episodes_available_count": getattr(request, "episodes_available_count", None),
        "episodes_aired_count": getattr(request, "episodes_aired_count", None),
        "episodes_total_count": getattr(request, "episodes_total_count", None),
        "has_vf": getattr(request, "has_vf", None),
    }


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


async def set_resync_notification_baselines(
    baselines: dict[int, dict[str, Any]], ttl: int = 7200
) -> None:
    """Enregistre les états historiques ciblés par un resync, partagés via Redis."""
    global _local_resync_notification_baselines
    _local_resync_notification_baselines = dict(baselines)
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return
    from redis.asyncio import Redis

    redis = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    try:
        for request_id, baseline in baselines.items():
            await redis.set(
                f"{RESYNC_NOTIFICATION_BASELINE_PREFIX}{request_id}",
                json.dumps(baseline, ensure_ascii=True),
                ex=ttl,
            )
    finally:
        await redis.aclose()


async def clear_resync_notification_baselines(request_ids: list[int]) -> None:
    """Supprime les références du resync ; les nouveaux états sont alors libres."""
    for request_id in request_ids:
        _local_resync_notification_baselines.pop(int(request_id), None)
    redis_url = os.getenv("REDIS_URL")
    if not redis_url or not request_ids:
        return
    from redis.asyncio import Redis

    redis = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    try:
        await redis.delete(*[
            f"{RESYNC_NOTIFICATION_BASELINE_PREFIX}{int(request_id)}"
            for request_id in request_ids
        ])
    finally:
        await redis.aclose()


async def availability_notification_is_historical(
    request_id: int, current_signature: dict[str, Any] | None = None
) -> bool:
    """Indique si la série est ciblée par un resync silencieux en cours."""
    request_id = int(request_id)
    baseline = _local_resync_notification_baselines.get(request_id)
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        from redis.asyncio import Redis

        redis = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
        try:
            if await redis.exists(f"{RESYNC_EXTERNAL_EVENT_PREFIX}{request_id}"):
                return False
            raw = await redis.get(f"{RESYNC_NOTIFICATION_BASELINE_PREFIX}{request_id}")
            baseline = json.loads(raw) if raw else None
        except Exception as exc:
            logger.error("Impossible de vérifier l'état du resync pour req#%s: %s", request_id, exc)
            return True
        finally:
            await redis.aclose()
    if baseline is None:
        return False
    return True


async def mark_external_availability_event(request_id: int, ttl: int = 300) -> None:
    """Marque un vrai événement externe (webhook) comme prioritaire sur le resync."""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return
    from redis.asyncio import Redis

    redis = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    try:
        await redis.set(f"{RESYNC_EXTERNAL_EVENT_PREFIX}{int(request_id)}", "1", ex=ttl)
    finally:
        await redis.aclose()
