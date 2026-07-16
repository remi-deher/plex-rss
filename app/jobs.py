"""ARQ worker settings and idempotent wrappers for all periodic work."""

import asyncio
import contextlib
import json
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy.future import select

from .database import AsyncSessionLocal, init_db
from .models import JobRunLog, PendingNotification, Settings
from .realtime import publish
from .utils import local_hour, now_utc, now_utc_naive

# Le worker ARQ est un process séparé (commande `arq app.jobs.WorkerSettings`) qui
# n'importe jamais app.main — sans ce basicConfig, aucun logger.info/warning/error de
# tout le code exécuté par les jobs (radarr/sonarr/notifications/vff/plex_sync...)
# n'apparaît dans `docker logs`, faute de handler sur le root logger.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)
LOCK_TTL = 60 * 60
STATE_TTL = 7 * 24 * 60 * 60
MIGRATION_LOCK_KEY = "plexarr:migration:lock"


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379/0"))


async def _state(redis, name: str, **changes: Any) -> dict[str, Any]:
    key = f"plexarr:jobs:state:{name}"
    current_raw = await redis.get(key)
    current = json.loads(current_raw) if current_raw else {"name": name}
    current.update(changes)
    await redis.set(key, json.dumps(current, ensure_ascii=True), ex=STATE_TTL)
    await publish("job.updated", current, admin_only=True)
    return current


async def _due(ctx: dict, name: str, interval_seconds: int, force: bool) -> bool:
    if force:
        return True
    key = f"plexarr:jobs:last-scheduled:{name}"
    return bool(await ctx["redis"].set(key, str(time.time()), ex=max(interval_seconds, 1), nx=True))


async def _log_job_run(name: str, started_at, duration_ms: float, status: str, error: str | None) -> None:
    """Persiste une exécution réelle dans job_run_logs (voir JobRunLog / onglet
    Réglages > Tâches planifiées). Best-effort : une erreur ici ne doit jamais faire
    échouer le job qu'elle journalise."""
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                JobRunLog(
                    job=name,
                    started_at=started_at,
                    duration_ms=round(duration_ms),
                    status=status,
                    error=error,
                )
            )
            await db.commit()
    except Exception as e:
        logger.warning("Impossible de journaliser l'execution de '%s' dans job_run_logs: %s", name, e)


async def _run(
    ctx: dict,
    name: str,
    function: Callable[[], Awaitable[Any]],
    *,
    force: bool = False,
    interval_seconds: int | None = None,
    event_type: str | None = None,
    log_history: bool = True,
) -> dict[str, Any]:
    redis = ctx["redis"]
    if await redis.exists(MIGRATION_LOCK_KEY):
        await _state(redis, name, status="skipped", progress=0, message="database migration in progress")
        return {"status": "skipped", "reason": "migration_in_progress"}
    if interval_seconds and not await _due(ctx, name, interval_seconds, force):
        return {"status": "not_due"}
    lock_key = f"plexarr:jobs:lock:{name}"
    token = uuid.uuid4().hex
    if not await redis.set(lock_key, token, ex=LOCK_TTL, nx=True):
        await _state(redis, name, status="skipped", progress=0, message="already running")
        return {"status": "skipped"}
    started = time.monotonic()
    started_at_naive = now_utc_naive()
    job_id = ctx.get("job_id")
    await _state(
        redis,
        name,
        job_id=job_id,
        status="running",
        progress=5,
        started_at=now_utc().isoformat(),
        finished_at=None,
        last_error=None,
    )
    try:
        result = await function()
        duration_ms = (time.monotonic() - started) * 1000
        state = await _state(
            redis,
            name,
            status="complete",
            progress=100,
            finished_at=now_utc().isoformat(),
            duration_ms=round(duration_ms, 1),
        )
        if log_history:
            await _log_job_run(name, started_at_naive, duration_ms, "complete", None)
        if event_type:
            public_signal = event_type in {"request.updated", "download.updated", "health.updated"}
            await publish(event_type, {"source": "worker"}, admin_only=not public_signal)
        return state | {"result": result}
    except Exception as exc:
        duration_ms = (time.monotonic() - started) * 1000
        await _state(
            redis,
            name,
            status="failed",
            progress=100,
            finished_at=now_utc().isoformat(),
            duration_ms=round(duration_ms, 1),
            last_error=str(exc),
        )
        if log_history:
            await _log_job_run(name, started_at_naive, duration_ms, "failed", str(exc))
        logger.exception("ARQ job %s failed", name)
        raise
    finally:
        await redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
            1,
            lock_key,
            token,
        )


async def _settings() -> Settings | None:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(Settings))).scalars().first()


async def _manual_result(run_id: str | None, action: str | None, operation):
    if not run_id or not action:
        return await operation
    from .job_queue import set_json

    key = f"plexarr:maintenance:{run_id}"
    try:
        result = await operation
        state = {
            "run_id": run_id,
            "action": action,
            "status": "done",
            "progress": 100,
            "logs": ["[OK] Job ARQ termine."],
            "started_at": "",
            "finished_at": now_utc().isoformat(),
        }
        await set_json(key, state)
        await publish("job.updated", state, admin_only=True)
        return result
    except Exception as exc:
        state = {
            "run_id": run_id,
            "action": action,
            "status": "error",
            "progress": 100,
            "logs": [f"[ERR] {exc}"],
            "started_at": "",
            "finished_at": now_utc().isoformat(),
        }
        await set_json(key, state)
        await publish("job.updated", state, admin_only=True)
        raise


async def job_watchlist(ctx: dict, force: bool = False, run_id: str | None = None, action: str | None = None):
    from .services.watchlist_poller import poll_watchlists

    settings = await _settings()
    interval = (settings.poll_interval_seconds if settings else None) or 300
    return await _manual_result(
        run_id,
        action,
        _run(ctx, "watchlist", poll_watchlists, force=force, interval_seconds=interval, event_type="request.updated"),
    )


async def job_arr_statuses(ctx: dict, force: bool = False, run_id: str | None = None, action: str | None = None):
    from .services.arr_tracker import check_arr_statuses

    settings = await _settings()
    interval = (settings.arr_poll_interval_seconds if settings else None) or 900
    return await _manual_result(
        run_id,
        action,
        _run(ctx, "arr-statuses", check_arr_statuses, force=force, interval_seconds=interval, event_type="request.updated"),
    )


async def job_torrent_statuses(ctx: dict, force: bool = False):
    from .services.arr_tracker import check_torrent_statuses

    return await _run(
        ctx,
        "torrent-statuses",
        check_torrent_statuses,
        force=force,
        interval_seconds=120,
        event_type="download.updated",
    )


async def job_vff_statuses(ctx: dict, force: bool = False):
    from .services.vff_scanner import check_vf_statuses

    settings = await _settings()
    interval = ((settings.vff_recheck_interval_minutes if settings else None) or 360) * 60
    return await _run(
        ctx, "vff-statuses", check_vf_statuses, force=force, interval_seconds=interval, event_type="request.updated"
    )


async def job_episode_tracking(ctx: dict, force: bool = False):
    from .services.vff_scanner import check_episode_tracking

    settings = await _settings()
    interval = ((settings.vff_recheck_interval_minutes if settings else None) or 360) * 60
    return await _run(
        ctx,
        "episode-tracking",
        check_episode_tracking,
        force=force,
        interval_seconds=interval,
        event_type="request.updated",
    )


async def job_new_vff(ctx: dict, force: bool = False):
    from .services.vff_scanner import check_new_vf_availability

    return await _run(
        ctx, "new-vff", check_new_vf_availability, force=force, interval_seconds=60, event_type="request.updated"
    )


async def job_seer_sync(ctx: dict, force: bool = False):
    from .services.seer_sync import _seer_full_sync

    return await _run(
        ctx, "seer-sync", _seer_full_sync, force=force, interval_seconds=3600, event_type="request.updated"
    )


async def job_plex_sync(ctx: dict, force: bool = False):
    from .services.plex_sync import sync_plex_media

    return await _run(
        ctx, "plex-sync", sync_plex_media, force=force, interval_seconds=86400, event_type="request.updated"
    )


async def job_notification_purge(ctx: dict, force: bool = False):
    from .services.notification_orchestrator import _purge_notification_logs

    return await _run(ctx, "notification-purge", _purge_notification_logs, force=force, interval_seconds=86400)


async def job_digest(ctx: dict, force: bool = False):
    from .services.notification_orchestrator import _send_digest

    settings = await _settings()
    # digest_hour est une heure murale (ex. "8h" saisie dans les réglages) — la comparer à
    # now_utc().hour la décale silencieusement de 1h/2h selon CET/CEST (incident réel :
    # réglé à 8h, mail reçu à 10h). local_hour() convertit dans le fuseau de l'app.
    if not force and (not settings or not settings.digest_enabled or settings.digest_hour != local_hour()):
        return {"status": "not_due"}
    return await _run(
        ctx, "digest", _send_digest, force=force, interval_seconds=3600, event_type="notification.updated"
    )


async def job_send_notification(ctx: dict, pending_id: int):
    from .notification_queue import process_pending_id

    async def send():
        return await process_pending_id(pending_id)

    result = await _run(ctx, f"notification-{pending_id}", send, log_history=False)
    user_id = result.get("result")
    await publish("notification.updated", {"pending_id": pending_id}, user_id=user_id)
    return result


async def job_maintenance(ctx: dict, run_id: str, action: str):
    from .job_queue import set_json
    from .routers.maintenance import _ACTION_RUNNERS, MaintenanceRun

    run = MaintenanceRun(action=action, status="running", started_at=now_utc().isoformat())
    key = f"plexarr:maintenance:{run_id}"
    await set_json(key, {"run_id": run_id, **run.__dict__})
    await publish("job.updated", {"run_id": run_id, "action": action, "status": "running"}, admin_only=True)

    async def monitor():
        last = None
        while run.status == "running":
            snapshot = {"run_id": run_id, **run.__dict__}
            marker = (run.progress, len(run.logs))
            if marker != last:
                await set_json(key, snapshot)
                await publish(
                    "job.updated",
                    {"run_id": run_id, "action": action, "status": run.status, "progress": run.progress},
                    admin_only=True,
                )
                last = marker
            await asyncio.sleep(0.5)

    monitor_task = asyncio.create_task(monitor())
    try:
        await _ACTION_RUNNERS[action](run)
        run.status = "done"
    except Exception as exc:
        run.status = "error"
        run.logs.append(f"[ERR] {exc}")
        raise
    finally:
        monitor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await monitor_task
        run.progress = 100
        run.finished_at = now_utc().isoformat()
        await set_json(key, {"run_id": run_id, **run.__dict__})
        await publish(
            "job.updated",
            {"run_id": run_id, "action": action, "status": run.status, "progress": 100},
            admin_only=True,
        )


async def startup(ctx: dict):
    await init_db()
    async with AsyncSessionLocal() as db:
        pending_ids = (await db.execute(select(PendingNotification.id))).scalars().all()
    for pending_id in pending_ids:
        await ctx["redis"].enqueue_job(
            "job_send_notification",
            pending_id,
            _job_id=f"notification:{pending_id}",
            _queue_name="plexarr:jobs",
        )
    logger.info("ARQ worker ready; recovered %d pending notification(s)", len(pending_ids))


# Cron wrappers have distinct names so the underlying jobs remain directly enqueueable.
async def cron_watchlist(ctx: dict):
    return await job_watchlist(ctx)


async def cron_arr_statuses(ctx: dict):
    return await job_arr_statuses(ctx)


async def cron_torrent_statuses(ctx: dict):
    return await job_torrent_statuses(ctx)


async def cron_vff_statuses(ctx: dict):
    return await job_vff_statuses(ctx)


async def cron_episode_tracking(ctx: dict):
    return await job_episode_tracking(ctx)


async def cron_new_vff(ctx: dict):
    return await job_new_vff(ctx)


async def cron_seer_sync(ctx: dict):
    return await job_seer_sync(ctx)


async def cron_plex_sync(ctx: dict):
    return await job_plex_sync(ctx)


async def cron_notification_purge(ctx: dict):
    return await job_notification_purge(ctx)


async def cron_digest(ctx: dict):
    return await job_digest(ctx)


class WorkerSettings:
    functions = [
        job_watchlist,
        job_arr_statuses,
        job_torrent_statuses,
        job_vff_statuses,
        job_episode_tracking,
        job_new_vff,
        job_seer_sync,
        job_plex_sync,
        job_notification_purge,
        job_digest,
        job_send_notification,
        job_maintenance,
    ]
    cron_jobs = [
        cron(cron_watchlist, second={0, 30}, unique=True, run_at_startup=True),
        cron(cron_arr_statuses, minute={0, 15, 30, 45}, unique=True),
        cron(cron_torrent_statuses, minute=set(range(0, 60, 2)), unique=True),
        cron(cron_vff_statuses, minute=None, unique=True),
        cron(cron_episode_tracking, minute=None, second=10, unique=True),
        cron(cron_new_vff, minute=None, second=20, unique=True),
        cron(cron_seer_sync, minute=5, unique=True),
        cron(cron_plex_sync, hour=3, minute=15, unique=True, run_at_startup=True),
        cron(cron_notification_purge, hour=3, minute=0, unique=True),
        cron(cron_digest, minute=0, unique=True),
    ]
    on_startup = startup
    redis_settings = redis_settings()
    queue_name = "plexarr:jobs"
    health_check_key = "plexarr:worker:health"
    health_check_interval = 30
    max_jobs = int(os.getenv("ARQ_MAX_JOBS", "4"))
    job_timeout = int(os.getenv("ARQ_JOB_TIMEOUT", "3600"))
    job_completion_wait = 30
    keep_result = 3600
    max_tries = 3
