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
_ORPHAN_RADARR_MISSING_CACHE_KEY = "plexarr:stats:orphan_radarr_missing"
_ORPHAN_ARR_CACHE_TTL = 120


def _is_show_genuinely_incomplete(file_count: int, aired_count: int, total_count: int) -> bool:
    """Une série est "non complète" si des épisodes déjà diffusés manquent au
    téléchargement (`file_count < aired_count`).

    Une série "à venir" (`aired_count == 0`, rien diffusé pour l'instant) n'est PAS
    en retard au sens strict — elle est exclue ici par choix (catégorie distincte
    "à venir" côté page Demandes, pas dans ce compteur "en cours").

    Ne PAS comparer systématiquement à `total_count` (diffusés + à venir) : une série
    en cours de diffusion mais à jour sur tout ce qui est déjà sorti aurait alors
    presque toujours un total supérieur au nombre de fichiers, la faisant compter à
    tort comme "non complète" tant qu'elle continue simplement d'être diffusée.
    """
    return bool(aired_count) and file_count < aired_count


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
        # `arr_id` peut être périmé (check_arr_statuses ne le corrige que s'il est NULL,
        # jamais s'il pointe vers un ID Sonarr qui n'existe plus après une réorganisation
        # côté Sonarr) — tvdb_id est l'identifiant stable, à privilégier pour ne pas
        # recompter en "orpheline" une série déjà suivie par une demande.
        known_rows = (await db.execute(
            select(MediaRequest.arr_id, MediaRequest.tvdb_id).filter(MediaRequest.media_type == "show")
        )).all()
        known_arr_ids = {r.arr_id for r in known_rows if r.arr_id is not None}
        known_tvdb_ids = {str(r.tvdb_id) for r in known_rows if r.tvdb_id}
        for inst in instances:
            try:
                series_list = await sonarr.get_all_series(inst.url, inst.api_key)
            except Exception:
                continue
            for series in series_list:
                if (
                    series.get("id") in known_arr_ids
                    or str(series.get("tvdbId")) in known_tvdb_ids
                    or not series.get("monitored", True)
                ):
                    continue
                # Agrégation sur les seules saisons surveillées (exclut les spéciaux non
                # surveillés) — utiliser les statistiques brutes de haut niveau les inclurait
                # à tort (ex: une saison 0 de spéciaux non surveillée gonfle le total).
                stats = sonarr.aggregate_monitored_episode_stats(series)
                if _is_show_genuinely_incomplete(
                    stats["episode_file_count"], stats["episode_count"], stats["total_episode_count"]
                ):
                    count += 1

    await cache.set_json(_ORPHAN_SONARR_PROGRESS_CACHE_KEY, {"count": count}, ttl_seconds=_ORPHAN_ARR_CACHE_TTL)
    return count


async def _count_orphan_radarr_missing(db: AsyncSession) -> int:
    """Films surveillés par Radarr mais jamais passés par une demande Plexarr
    (ajoutés directement dans Radarr) et sans fichier.

    Pendant Sonarr, pas de notion de disponibilité partielle ici : un film a un
    fichier ou n'en a pas.
    """
    cached = await cache.get_json(_ORPHAN_RADARR_MISSING_CACHE_KEY)
    if cached is not None:
        return cached.get("count", 0)

    instances = (await db.execute(
        select(ArrInstance).filter(ArrInstance.enabled, ArrInstance.arr_type == "radarr")
    )).scalars().all()

    count = 0
    if instances:
        # Même précaution que pour Sonarr (voir _count_orphan_sonarr_progress) : arr_id
        # peut être périmé, tmdb_id/imdb_id sont les identifiants stables.
        known_rows = (await db.execute(
            select(MediaRequest.arr_id, MediaRequest.tmdb_id, MediaRequest.imdb_id).filter(MediaRequest.media_type == "movie")
        )).all()
        known_arr_ids = {r.arr_id for r in known_rows if r.arr_id is not None}
        known_tmdb_ids = {str(r.tmdb_id) for r in known_rows if r.tmdb_id}
        known_imdb_ids = {r.imdb_id for r in known_rows if r.imdb_id}
        for inst in instances:
            try:
                movies_list = await radarr.get_all_movies(inst.url, inst.api_key)
            except Exception:
                continue
            for movie in movies_list:
                if (
                    movie.get("id") in known_arr_ids
                    or str(movie.get("tmdbId")) in known_tmdb_ids
                    or movie.get("imdbId") in known_imdb_ids
                    or not movie.get("monitored", True)
                ):
                    continue
                if not movie.get("hasFile", False):
                    count += 1

    await cache.set_json(_ORPHAN_RADARR_MISSING_CACHE_KEY, {"count": count}, ttl_seconds=_ORPHAN_ARR_CACHE_TTL)
    return count


async def _count_incomplete_show_requests(db: AsyncSession) -> int:
    """Demandes séries "non complètes" : jamais envoyées à Sonarr (`sent_to_arr`), ou
    partiellement disponibles avec un vrai manque d'épisodes déjà diffusés.

    `partially_available` seul ne suffit pas : ce statut reste posé tant que la série
    n'a pas fini de diffuser (comparaison à `episodes_total_count`, diffusés + à venir
    — voir `arr_tracker.is_show_partial`), pour ne jamais afficher un badge
    "Disponible" trompeur. La plupart des séries encore en diffusion sont donc déjà à
    jour sur tout ce qui est réellement sorti ; ne les compter que si des épisodes
    déjà diffusés (`episodes_aired_count`) manquent encore au téléchargement (voir
    `_is_show_genuinely_incomplete`) évite de gonfler ce compteur avec des séries qui
    ne sont, en pratique, pas "en retard". Une série "à venir" (rien diffusé pour
    l'instant) n'est volontairement pas comptée ici — catégorie distincte "à venir".
    """
    from sqlalchemy import and_, func, or_

    return (await db.execute(
        select(func.count()).select_from(MediaRequest).filter(
            MediaRequest.media_type == "show",
            or_(
                MediaRequest.status == RequestStatus.sent_to_arr,
                and_(
                    MediaRequest.status == RequestStatus.partially_available,
                    MediaRequest.episodes_aired_count.isnot(None),
                    MediaRequest.episodes_aired_count > 0,
                    MediaRequest.episodes_available_count < MediaRequest.episodes_aired_count,
                ),
            ),
        )
    )).scalar() or 0


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
        # "partially_available" est recompté ci-dessous via _count_incomplete_show_requests
        # (seul un vrai manque d'épisodes déjà diffusés compte comme "non complet") — on
        # l'exclut ici du bucket "sent_to_arr" pour ne pas le compter deux fois, mais il
        # reste dans "total".
        bucket = by_type.setdefault(media_type, _empty())
        if status in bucket:
            bucket[status] += n
        bucket["total"] += n
        if status in globals_:
            globals_[status] += n
        globals_["total"] += n

    show_in_progress = await _count_incomplete_show_requests(db)
    orphan_shows = await _count_orphan_sonarr_progress(db)
    orphan_movies = await _count_orphan_radarr_missing(db)

    by_type["show"]["sent_to_arr"] = show_in_progress + orphan_shows
    by_type["show"]["total"] += orphan_shows
    by_type["movie"]["sent_to_arr"] += orphan_movies
    by_type["movie"]["total"] += orphan_movies
    globals_["sent_to_arr"] = by_type["movie"]["sent_to_arr"] + by_type["show"]["sent_to_arr"]
    globals_["total"] += orphan_shows + orphan_movies

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
