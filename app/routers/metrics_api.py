import asyncio
import json as _json
import json
import os
import time
from datetime import timedelta
from typing import Optional, cast

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import sqlalchemy

from .. import metrics as app_metrics
from ..cache import cache
from ..database import get_db_async
from ..dependencies import require_admin
from ..models import ArrInstance, MediaRequest, PlexUser, PollHistory, RequestStatus, Settings
from ..services import prowlarr, radarr, sonarr
from ..services.plex_api import check_connection as plex_test
from ..services.seer import check_connection as seer_test
from ..utils import now_utc, now_utc_naive

router = APIRouter(prefix="/api", tags=["metrics"], dependencies=[Depends(require_admin)])


async def _infrastructure_metrics() -> dict:
    result = {"redis_up": 0, "worker_up": 0, "queue_depth": 0, "jobs": []}
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return result
    try:
        from redis.asyncio import Redis

        redis = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
        try:
            await redis.ping()
            result["redis_up"] = 1
            result["worker_up"] = int(bool(await redis.get("plexarr:worker:health")))
            result["queue_depth"] = int(await redis.zcard("plexarr:jobs"))
            async for key in redis.scan_iter("plexarr:jobs:state:*"):
                raw = await redis.get(key)
                if raw:
                    result["jobs"].append(json.loads(raw))
        finally:
            await redis.aclose()
    except Exception:
        pass
    return result


async def _timed_check(coro) -> tuple[bool | None, str, float | None]:
    """Exécute une coroutine de connectivité et retourne (ok, message, latence_ms)."""
    t0 = time.monotonic()
    ok, msg = await coro
    return ok, msg, round((time.monotonic() - t0) * 1000, 1)


async def _preferred_instance(db: AsyncSession, arr_type: str) -> ArrInstance | None:
    inst = (
        (await db.execute(select(ArrInstance).filter(ArrInstance.arr_type == arr_type, ArrInstance.enabled, ArrInstance.is_default))).scalars().first()
    )
    if inst:
        return inst
    return (await db.execute(select(ArrInstance).filter(ArrInstance.arr_type == arr_type, ArrInstance.enabled))).scalars().first()


def _not_configured(message: str = "Non configure") -> dict:
    return {
        "ok": None,
        "state": "non_configured",
        "message": message,
        "response_ms": None,
        "action_url": "/settings#tab-connexions",
        "action_label": "Configurer",
    }


def _disabled(message: str = "Desactive") -> dict:
    return {
        "ok": None,
        "state": "disabled",
        "message": message,
        "response_ms": None,
        "action_url": "/settings#tab-connexions",
        "action_label": "Activer",
    }


async def _missing_arr_state(db: AsyncSession, arr_type: str) -> dict:
    exists = (await db.execute(select(ArrInstance).filter(ArrInstance.arr_type == arr_type))).scalars().first() is not None
    return _disabled("Instance configuree mais desactivee") if exists else _not_configured("Aucune instance configuree")


async def _timed_prowlarr_check(inst: ArrInstance) -> tuple[bool | None, str, float | None]:
    t0 = time.monotonic()
    ok = await prowlarr.check_connection(inst.url, inst.api_key)
    return ok, "OK" if ok else "Connexion impossible", round((time.monotonic() - t0) * 1000, 1)


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db_async)):
    """État structuré de tous les services connectés avec latences."""
    cached = await cache.get_json("plexarr:health")
    if cached:
        return cached
    s = (await db.execute(select(Settings))).scalars().first()
    checks: dict[str, tuple] = {}
    sonarr_inst = await _preferred_instance(db, "sonarr")
    radarr_inst = await _preferred_instance(db, "radarr")
    prowlarr_inst = await _preferred_instance(db, "prowlarr")
    if sonarr_inst:
        checks["sonarr"] = ("failed", _timed_check(sonarr.check_connection(sonarr_inst.url, sonarr_inst.api_key)))
    if radarr_inst:
        checks["radarr"] = ("failed", _timed_check(radarr.check_connection(radarr_inst.url, radarr_inst.api_key)))
    if prowlarr_inst:
        checks["prowlarr"] = ("degraded", _timed_prowlarr_check(prowlarr_inst))
    seer_disabled = bool(s and s.seer_url and s.seer_api_key and not s.seer_send_requests)
    if s and s.seer_url and s.seer_api_key and s.seer_send_requests:
        checks["seer"] = ("degraded", _timed_check(seer_test(s.seer_url, s.seer_api_key)))
    if s and s.plex_url and s.plex_token:
        checks["plex"] = ("failed", _timed_check(plex_test(s.plex_url, s.plex_token, verify_ssl=s.plex_verify_ssl)))

    results = dict(zip(checks.keys(), await asyncio.gather(*(coro for _, coro in checks.values()))))

    services: dict[str, dict] = {}
    failed = 0
    degraded = 0
    for name in ("sonarr", "radarr", "prowlarr", "seer", "plex"):
        if name not in checks:
            if name in ("sonarr", "radarr", "prowlarr"):
                services[name] = await _missing_arr_state(db, name)
            elif name == "seer" and seer_disabled:
                services[name] = _disabled("Demandes via Seer desactivees")
            elif name == "plex":
                services[name] = _not_configured("URL ou token Plex manquant")
            else:
                services[name] = _not_configured()
            continue
        severity, _ = checks[name]
        ok, msg, ms = results[name]
        services[name] = {
            "ok": ok,
            "state": "ok" if ok else "error",
            "message": msg,
            "response_ms": ms,
            "action_url": "/settings#tab-connexions",
            "action_label": "Corriger",
        }
        if not ok:
            if severity == "degraded":
                degraded += 1
            else:
                failed += 1

    services["smtp"] = {
        "ok": bool(s and s.smtp_host),
        "state": "ok" if s and s.smtp_host else "non_configured",
        "message": "Configure" if s and s.smtp_host else "Non configure",
        "response_ms": None,
        "action_url": "/settings#tab-notifications",
        "action_label": "Configurer",
    }
    services["rss"] = {
        "ok": bool(s and s.plex_rss_url),
        "state": "ok" if s and s.plex_rss_url else "non_configured",
        "message": "Configure" if s and s.plex_rss_url else "Non configure",
        "response_ms": None,
        "action_url": "/settings#tab-connexions",
        "action_label": "Configurer",
    }

    if failed > 0:
        overall = "down"
    elif degraded > 0:
        overall = "degraded"
    else:
        overall = "healthy"

    payload = {
        "status": overall,
        "checked_at": now_utc().isoformat(),
        "services": services,
    }
    await cache.set_json("plexarr:health", payload, ttl_seconds=20)
    from ..realtime import publish

    await publish("health.updated", {"checked_at": payload["checked_at"]})
    return payload


@router.get("/metrics")
async def get_metrics(db: AsyncSession = Depends(get_db_async)):
    """Métriques runtime (session courante) + agrégats DB (total historique)."""
    total = (await db.execute(select(sqlalchemy.func.count()).select_from(MediaRequest))).scalar()
    available = (await db.execute(select(sqlalchemy.func.count()).select_from(MediaRequest).filter(MediaRequest.status == "available"))).scalar()
    failed = (await db.execute(select(sqlalchemy.func.count()).select_from(MediaRequest).filter(MediaRequest.status == "failed"))).scalar()
    notif_sent = (await db.execute(select(sqlalchemy.func.count()).select_from(MediaRequest).filter(MediaRequest.available_mail_sent.is_(True)))).scalar()
    notif_missed = (
        await db.execute(
            select(sqlalchemy.func.count())
            .select_from(MediaRequest)
            .filter(
                MediaRequest.status == "available",
                MediaRequest.available_mail_sent.is_(False),
            )
        )
    ).scalar()
    notif_total = notif_sent + notif_missed
    notif_failure_pct_db = round(notif_missed / notif_total * 100, 1) if notif_total else None

    return {
        "runtime": app_metrics.snapshot(),
        "infrastructure": await _infrastructure_metrics(),
        "db": {
            "total_requests": total,
            "available": available,
            "failed": failed,
            "success_rate_pct": round(available / total * 100, 1) if total else None,
            "notifications": {
                "sent": notif_sent,
                "missed": notif_missed,
                "failure_rate_pct": notif_failure_pct_db,
            },
        },
    }


@router.get("/next-poll")
def next_poll_info():
    """Retourne le nombre de secondes avant le prochain polling (pour le countdown UI)."""
    from ..scheduler import scheduler

    job = scheduler.get_job("watchlist_poll")
    if not job or not job.next_run_time:
        return {"next_run_seconds": None, "next_run_iso": None}
    now = now_utc()
    delta = (job.next_run_time - now).total_seconds()
    return {
        "next_run_seconds": max(0, int(delta)),
        "next_run_iso": job.next_run_time.isoformat(),
    }


@router.get("/poll-history")
async def get_poll_history(limit: int = 50, job: Optional[str] = None, db: AsyncSession = Depends(get_db_async)):
    """Retourne l'historique des exécutions du scheduler."""
    q = select(PollHistory)
    if job:
        q = q.filter(PollHistory.job == job)
    items = (await db.execute(q.order_by(PollHistory.started_at.desc()).limit(limit))).scalars().all()
    from ..serializers import format_datetime

    return [
        {
            "id": h.id,
            "job": h.job,
            "started_at": format_datetime(h.started_at),
            "duration_ms": h.duration_ms,
            "items_processed": h.items_processed,
            "new_requests": h.new_requests,
            "newly_available": h.newly_available,
            "errors": h.errors,
            "error_detail": h.error_detail,
        }
        for h in items
    ]


@router.get("/metrics/prometheus", response_class=__import__("fastapi").responses.PlainTextResponse)
async def prometheus_metrics(db: AsyncSession = Depends(get_db_async)):
    """Expose les métriques au format Prometheus text (scraping externe)."""
    from fastapi.responses import PlainTextResponse

    snap = app_metrics.snapshot()
    infrastructure = await _infrastructure_metrics()

    total = (await db.execute(select(sqlalchemy.func.count()).select_from(MediaRequest))).scalar()
    available = (await db.execute(select(sqlalchemy.func.count()).select_from(MediaRequest).filter(MediaRequest.status == "available"))).scalar()
    failed_db = (await db.execute(select(sqlalchemy.func.count()).select_from(MediaRequest).filter(MediaRequest.status == "failed"))).scalar()
    pending = (await db.execute(select(sqlalchemy.func.count()).select_from(MediaRequest).filter(MediaRequest.status == "pending"))).scalar()
    sent = (await db.execute(select(sqlalchemy.func.count()).select_from(MediaRequest).filter(MediaRequest.status == "sent_to_arr"))).scalar()

    lines = [
        "# HELP plex_rss_poll_total Total number of watchlist polls since startup",
        "# TYPE plex_rss_poll_total counter",
        f"plex_rss_poll_total {snap['poll']['count']}",
        "# HELP plex_rss_poll_errors_total Total number of failed polls since startup",
        "# TYPE plex_rss_poll_errors_total counter",
        f"plex_rss_poll_errors_total {snap['poll']['errors']}",
        "# HELP plex_rss_arr_submissions_total Total submissions to Sonarr/Radarr/Seer since startup",
        "# TYPE plex_rss_arr_submissions_total counter",
        f"plex_rss_arr_submissions_total {snap['arr']['submissions']}",
        "# HELP plex_rss_arr_errors_total Total failed submissions since startup",
        "# TYPE plex_rss_arr_errors_total counter",
        f"plex_rss_arr_errors_total {snap['arr']['errors']}",
        "# HELP plex_rss_notifications_sent_total Total notifications sent since startup",
        "# TYPE plex_rss_notifications_sent_total counter",
        f"plex_rss_notifications_sent_total {snap['notifications']['sent']}",
        "# HELP plex_rss_notifications_failed_total Total failed notifications since startup",
        "# TYPE plex_rss_notifications_failed_total counter",
        f"plex_rss_notifications_failed_total {snap['notifications']['failed']}",
        "# HELP plex_rss_sonarr_response_ms Average Sonarr response time (ms, last 50 calls)",
        "# TYPE plex_rss_sonarr_response_ms gauge",
        f"plex_rss_sonarr_response_ms {snap['arr']['sonarr_avg_response_ms'] or 0}",
        "# HELP plex_rss_radarr_response_ms Average Radarr response time (ms, last 50 calls)",
        "# TYPE plex_rss_radarr_response_ms gauge",
        f"plex_rss_radarr_response_ms {snap['arr']['radarr_avg_response_ms'] or 0}",
        "# HELP plex_rss_requests_total Total media requests in database",
        "# TYPE plex_rss_requests_total gauge",
        f"plex_rss_requests_total {total}",
        "# HELP plex_rss_requests_by_status Media requests grouped by status",
        "# TYPE plex_rss_requests_by_status gauge",
        f'plex_rss_requests_by_status{{status="available"}} {available}',
        f'plex_rss_requests_by_status{{status="failed"}} {failed_db}',
        f'plex_rss_requests_by_status{{status="pending"}} {pending}',
        f'plex_rss_requests_by_status{{status="sent_to_arr"}} {sent}',
        "# HELP plex_rss_redis_up Whether Redis is reachable",
        "# TYPE plex_rss_redis_up gauge",
        f"plex_rss_redis_up {infrastructure['redis_up']}",
        "# HELP plex_rss_worker_up Whether the ARQ worker heartbeat is present",
        "# TYPE plex_rss_worker_up gauge",
        f"plex_rss_worker_up {infrastructure['worker_up']}",
        "# HELP plex_rss_job_queue_depth Number of queued ARQ jobs",
        "# TYPE plex_rss_job_queue_depth gauge",
        f"plex_rss_job_queue_depth {infrastructure['queue_depth']}",
    ]
    lines.extend(
        f'plex_rss_job_last_duration_ms{{job="{job.get("name", "unknown")}"}} {job.get("duration_ms", 0)}'
        for job in infrastructure["jobs"]
    )

    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@router.get("/stats/timeline")
async def stats_timeline(db: AsyncSession = Depends(get_db_async)):
    """Retourne le nombre de demandes par jour sur les 30 derniers jours."""
    from sqlalchemy import func

    days = 30
    start = now_utc_naive() - timedelta(days=days)
    rows = (await db.execute(select(func.date(MediaRequest.requested_at).label("day"), func.count().label("count")).filter(MediaRequest.requested_at >= start).group_by(func.date(MediaRequest.requested_at)))).all()
    data = {}
    for r in rows:
        if r.day is None:
            continue
        if hasattr(r.day, "strftime"):
            day_str = r.day.strftime("%Y-%m-%d")
        else:
            day_str = str(r.day).split(" ")[0]
        data[day_str] = r.count
    labels, values = [], []
    for i in range(days):
        d = (start + timedelta(days=i + 1)).strftime("%Y-%m-%d")
        labels.append(d)
        values.append(data.get(d, 0))
    return {"labels": labels, "values": values}


@router.get("/stats/by-user")
async def stats_by_user(db: AsyncSession = Depends(get_db_async)):
    """Retourne le nombre de demandes par utilisateur, trié par volume décroissant."""
    from sqlalchemy import func

    rows = (await db.execute(select(MediaRequest.plex_user_id, func.count().label("total")).group_by(MediaRequest.plex_user_id).order_by(func.count().desc()))).all()
    users = {u.plex_user_id: (u.display_name or u.plex_user_id) for u in (await db.execute(select(PlexUser))).scalars().all()}
    return [
        {"plex_user_id": r.plex_user_id, "display_name": users.get(r.plex_user_id, r.plex_user_id), "total": r.total}
        for r in rows
    ]


_ORPHAN_SONARR_PROGRESS_CACHE_KEY = "plexarr:stats:orphan_sonarr_progress"
_ORPHAN_SONARR_PROGRESS_CACHE_TTL = 120


async def _count_orphan_sonarr_progress(db: AsyncSession) -> int:
    """Séries surveillées par Sonarr mais jamais passées par une demande Plexarr
    (ajoutées directement dans Sonarr) et pas encore complètes.

    Sans `MediaRequest` les rattachant, ces séries sont invisibles du décompte
    ci-dessus alors qu'elles sont bien "en cours" côté Sonarr — d'où un compteur
    "Chez Sonarr" sous-évalué sur le dashboard. Résultat mis en cache (appel réseau
    vers Sonarr) : une fraîcheur à la minute près suffit pour un compteur de tableau
    de bord.
    """
    cached = await cache.get_json(_ORPHAN_SONARR_PROGRESS_CACHE_KEY)
    if cached is not None:
        return cached.get("count", 0)

    instances = (await db.execute(
        select(ArrInstance).filter(ArrInstance.enabled, ArrInstance.arr_type == "sonarr")
    )).scalars().all()

    count = 0
    if instances:
        known_arr_ids = set(
            (await db.execute(
                select(MediaRequest.arr_id).filter(MediaRequest.media_type == "show", MediaRequest.arr_id.isnot(None))
            )).scalars().all()
        )
        for inst in instances:
            try:
                series_list = await sonarr.get_all_series(inst.url, inst.api_key)
            except Exception:
                continue
            for series in series_list:
                if series.get("id") in known_arr_ids or not series.get("monitored", True):
                    continue
                stats = series.get("statistics") or {}
                file_count = stats.get("episodeFileCount", 0) or 0
                total_count = stats.get("totalEpisodeCount", 0) or 0
                if total_count and file_count < total_count:
                    count += 1

    await cache.set_json(_ORPHAN_SONARR_PROGRESS_CACHE_KEY, {"count": count}, ttl_seconds=_ORPHAN_SONARR_PROGRESS_CACHE_TTL)
    return count


@router.get("/stats/counts")
async def stats_counts(db: AsyncSession = Depends(get_db_async)):
    """Retourne les compteurs par statut, globaux et ventilés par type de média."""
    from sqlalchemy import func

    rows = (await db.execute(select(MediaRequest.media_type, MediaRequest.status, func.count().label("n")).group_by(MediaRequest.media_type, MediaRequest.status))).all()

    def _empty():
        return {"failed": 0, "pending": 0, "sent_to_arr": 0, "available": 0, "total": 0}

    by_type = {"movie": _empty(), "show": _empty()}
    globals_ = _empty()
    for media_type, status, n in rows:
        bucket = by_type.setdefault(media_type, _empty())
        if status in bucket:
            bucket[status] += n
        bucket["total"] += n
        if status in globals_:
            globals_[status] += n
        globals_["total"] += n

    orphan_shows = await _count_orphan_sonarr_progress(db)
    if orphan_shows:
        by_type["show"]["sent_to_arr"] += orphan_shows
        by_type["show"]["total"] += orphan_shows
        globals_["sent_to_arr"] += orphan_shows
        globals_["total"] += orphan_shows

    return {**globals_, "by_type": by_type}


@router.get("/stats/top-requested")
async def stats_top_requested(db: AsyncSession = Depends(get_db_async), limit: int = 5):
    """Retourne les demandes ayant le plus de co-demandeurs (les plus réclamées)."""
    rows = (await db.execute(
        select(MediaRequest).filter(MediaRequest.extra_requesters.isnot(None), MediaRequest.extra_requesters != "[]")
    )).scalars().all()
    items = []
    for r in rows:
        extras = _json.loads(r.extra_requesters or "[]")
        count = 1 + len(extras)
        if count < 2:
            continue
        items.append(
            {
                "id": r.id,
                "title": r.title,
                "media_type": r.media_type,
                "poster_url": r.poster_url,
                "status": r.status,
                "count": count,
            }
        )
    items.sort(key=lambda i: cast(int, i["count"]), reverse=True)
    return items[:limit]


@router.get("/stats/recently-available")
async def stats_recently_available(db: AsyncSession = Depends(get_db_async), limit: int = 5):
    """Retourne les dernieres demandes devenues disponibles."""
    items = (await db.execute(
        select(MediaRequest)
        .filter(MediaRequest.status == "available")
        .order_by(MediaRequest.available_at.desc(), MediaRequest.requested_at.desc())
        .limit(limit)
    )).scalars().all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "media_type": r.media_type,
            "poster_url": r.poster_url,
            "available_at": r.available_at.isoformat() if r.available_at else None,
        }
        for r in items
    ]


@router.get("/disk-space")
async def disk_space(db: AsyncSession = Depends(get_db_async)):
    """Retourne l'espace disque des volumes Sonarr/Radarr, dédupliqué par chemin."""
    volumes: dict[str, dict] = {}

    async def add(label: str, coro):
        try:
            for d in await coro:
                key = d["path"]
                if key not in volumes:
                    volumes[key] = {**d, "sources": [label]}
                elif label not in volumes[key]["sources"]:
                    volumes[key]["sources"].append(label)
        except Exception:
            pass

    instances = (
        (await db.execute(select(ArrInstance).filter(ArrInstance.enabled, ArrInstance.arr_type.in_(["sonarr", "radarr"])).order_by(ArrInstance.arr_type, ArrInstance.is_default.desc(), ArrInstance.name))).scalars().all()
    )
    for inst in instances:
        label = f"{inst.name} ({inst.arr_type.title()})"
        if inst.arr_type == "sonarr":
            await add(label, sonarr.get_disk_space(inst.url, inst.api_key))
        elif inst.arr_type == "radarr":
            await add(label, radarr.get_disk_space(inst.url, inst.api_key))

    return list(volumes.values())
