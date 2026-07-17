"""ARQ queue helpers shared by API routes and notification producers."""

import json
import logging
import os
import uuid
from typing import Any

logger = logging.getLogger(__name__)

AVAILABILITY_NOTIFICATION_SUPPRESSION_KEY = "plexarr:lock:suppress-availability-notifications"
_local_availability_notifications_suppressed = False


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


async def acquire_availability_notification_suppression(ttl: int = 7200) -> str | None:
    """Suspend les notifications de disponibilité dans tous les processus.

    Le verrou est Redis-backed car le resync est lancé dans l'API alors que les
    cron/jobs et la livraison des mails tournent dans le worker. Sans Redis, le
    repli local garde les tests et les installations mono-process cohérents.
    """
    global _local_availability_notifications_suppressed
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        _local_availability_notifications_suppressed = True
        return "no-redis"

    from redis.asyncio import Redis

    token = uuid.uuid4().hex
    redis = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    try:
        acquired = await redis.set(
            AVAILABILITY_NOTIFICATION_SUPPRESSION_KEY, token, nx=True, ex=ttl
        )
        return token if acquired else None
    finally:
        await redis.aclose()


async def release_availability_notification_suppression(token: str | None) -> None:
    """Libère le verrou uniquement si ce processus en est toujours propriétaire."""
    global _local_availability_notifications_suppressed
    if token == "no-redis":
        _local_availability_notifications_suppressed = False
        return
    if not token or not os.getenv("REDIS_URL"):
        return

    from redis.asyncio import Redis

    redis = Redis.from_url(os.environ["REDIS_URL"], encoding="utf-8", decode_responses=True)
    try:
        script = (
            "if redis.call('get', KEYS[1]) == ARGV[1] "
            "then return redis.call('del', KEYS[1]) else return 0 end"
        )
        await redis.eval(script, 1, AVAILABILITY_NOTIFICATION_SUPPRESSION_KEY, token)
    finally:
        await redis.aclose()


async def availability_notifications_suppressed() -> bool:
    """Retourne l'état global de suspension, en échouant fermé si Redis est indisponible."""
    if _local_availability_notifications_suppressed:
        return True
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return False

    from redis.asyncio import Redis

    redis = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    try:
        return bool(await redis.exists(AVAILABILITY_NOTIFICATION_SUPPRESSION_KEY))
    except Exception as exc:
        logger.error("Impossible de vérifier la suspension des notifications: %s", exc)
        return True
    finally:
        await redis.aclose()
