import asyncio
import json as _json
import time
from datetime import timedelta
from typing import Optional, cast

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import metrics as app_metrics
from ..database import get_db
from ..dependencies import require_auth
from ..models import ArrInstance, MediaRequest, PlexUser, PollHistory, RequestStatus, Settings
from ..services import prowlarr, radarr, sonarr
from ..services.plex_api import check_connection as plex_test
from ..services.seer import check_connection as seer_test
from ..utils import now_utc, now_utc_naive

router = APIRouter(prefix="/api", tags=["metrics"], dependencies=[Depends(require_auth)])


async def _timed_check(coro) -> tuple[bool | None, str, float | None]:
    """Exécute une coroutine de connectivité et retourne (ok, message, latence_ms)."""
    t0 = time.monotonic()
    ok, msg = await coro
    return ok, msg, round((time.monotonic() - t0) * 1000, 1)


def _preferred_instance(db: Session, arr_type: str) -> ArrInstance | None:
    inst = (
        db.query(ArrInstance)
        .filter(ArrInstance.arr_type == arr_type, ArrInstance.enabled, ArrInstance.is_default)
        .first()
    )
    if inst:
        return inst
    return db.query(ArrInstance).filter(ArrInstance.arr_type == arr_type, ArrInstance.enabled).first()


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


def _missing_arr_state(db: Session, arr_type: str) -> dict:
    exists = db.query(ArrInstance).filter(ArrInstance.arr_type == arr_type).first() is not None
    return _disabled("Instance configuree mais desactivee") if exists else _not_configured("Aucune instance configuree")


async def _timed_prowlarr_check(inst: ArrInstance) -> tuple[bool | None, str, float | None]:
    t0 = time.monotonic()
    ok = await prowlarr.check_connection(inst.url, inst.api_key)
    return ok, "OK" if ok else "Connexion impossible", round((time.monotonic() - t0) * 1000, 1)


@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """État structuré de tous les services connectés avec latences."""
    s = db.query(Settings).first()
    checks: dict[str, tuple] = {}
    sonarr_inst = _preferred_instance(db, "sonarr")
    radarr_inst = _preferred_instance(db, "radarr")
    prowlarr_inst = _preferred_instance(db, "prowlarr")
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
                services[name] = _missing_arr_state(db, name)
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

    return {
        "status": overall,
        "checked_at": now_utc().isoformat(),
        "services": services,
    }


@router.get("/metrics")
def get_metrics(db: Session = Depends(get_db)):
    """Métriques runtime (session courante) + agrégats DB (total historique)."""
    total = db.query(MediaRequest).count()
    available = db.query(MediaRequest).filter(MediaRequest.status == "available").count()
    failed = db.query(MediaRequest).filter(MediaRequest.status == "failed").count()
    notif_sent = db.query(MediaRequest).filter(MediaRequest.available_mail_sent.is_(True)).count()
    notif_missed = (
        db.query(MediaRequest)
        .filter(
            MediaRequest.status == "available",
            MediaRequest.available_mail_sent.is_(False),
        )
        .count()
    )
    notif_total = notif_sent + notif_missed
    notif_failure_pct_db = round(notif_missed / notif_total * 100, 1) if notif_total else None

    return {
        "runtime": app_metrics.snapshot(),
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
def get_poll_history(limit: int = 50, job: Optional[str] = None, db: Session = Depends(get_db)):
    """Retourne l'historique des exécutions du scheduler."""
    q = db.query(PollHistory)
    if job:
        q = q.filter(PollHistory.job == job)
    items = q.order_by(PollHistory.started_at.desc()).limit(limit).all()
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
def prometheus_metrics(db: Session = Depends(get_db)):
    """Expose les métriques au format Prometheus text (scraping externe)."""
    from fastapi.responses import PlainTextResponse

    snap = app_metrics.snapshot()

    total = db.query(MediaRequest).count()
    available = db.query(MediaRequest).filter(MediaRequest.status == "available").count()
    failed_db = db.query(MediaRequest).filter(MediaRequest.status == "failed").count()
    pending = db.query(MediaRequest).filter(MediaRequest.status == "pending").count()
    sent = db.query(MediaRequest).filter(MediaRequest.status == "sent_to_arr").count()

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
    ]

    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@router.get("/stats/timeline")
def stats_timeline(db: Session = Depends(get_db)):
    """Retourne le nombre de demandes par jour sur les 30 derniers jours."""
    from sqlalchemy import func

    days = 30
    start = now_utc() - timedelta(days=days)
    rows = (
        db.query(
            func.date(MediaRequest.requested_at).label("day"),
            func.count().label("count"),
        )
        .filter(MediaRequest.requested_at >= start)
        .group_by(func.date(MediaRequest.requested_at))
        .all()
    )
    data = {r.day: r.count for r in rows}
    labels, values = [], []
    for i in range(days):
        d = (start + timedelta(days=i + 1)).strftime("%Y-%m-%d")
        labels.append(d)
        values.append(data.get(d, 0))
    return {"labels": labels, "values": values}


@router.get("/stats/by-user")
def stats_by_user(db: Session = Depends(get_db)):
    """Retourne le nombre de demandes par utilisateur, trié par volume décroissant."""
    from sqlalchemy import func

    rows = (
        db.query(MediaRequest.plex_user_id, func.count().label("total"))
        .group_by(MediaRequest.plex_user_id)
        .order_by(func.count().desc())
        .all()
    )
    users = {u.plex_user_id: (u.display_name or u.plex_user_id) for u in db.query(PlexUser).all()}
    return [
        {"plex_user_id": r.plex_user_id, "display_name": users.get(r.plex_user_id, r.plex_user_id), "total": r.total}
        for r in rows
    ]


@router.get("/stats/counts")
def stats_counts(db: Session = Depends(get_db)):
    """Retourne les compteurs par statut, globaux et ventilés par type de média."""
    from sqlalchemy import func

    rows = (
        db.query(MediaRequest.media_type, MediaRequest.status, func.count().label("n"))
        .group_by(MediaRequest.media_type, MediaRequest.status)
        .all()
    )

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

    return {**globals_, "by_type": by_type}


@router.get("/stats/top-requested")
def stats_top_requested(db: Session = Depends(get_db), limit: int = 5):
    """Retourne les demandes ayant le plus de co-demandeurs (les plus réclamées)."""
    rows = (
        db.query(MediaRequest)
        .filter(MediaRequest.extra_requesters.isnot(None), MediaRequest.extra_requesters != "[]")
        .all()
    )
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


@router.get("/disk-space")
async def disk_space(db: Session = Depends(get_db)):
    """Retourne l'espace disque des volumes Sonarr/Radarr, dédupliqué par chemin."""
    s = db.query(Settings).first()
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
        db.query(ArrInstance)
        .filter(ArrInstance.enabled, ArrInstance.arr_type.in_(["sonarr", "radarr"]))
        .order_by(ArrInstance.arr_type, ArrInstance.is_default.desc(), ArrInstance.name)
        .all()
    )
    for inst in instances:
        label = f"{inst.name} ({inst.arr_type.title()})"
        if inst.arr_type == "sonarr":
            await add(label, sonarr.get_disk_space(inst.url, inst.api_key))
        elif inst.arr_type == "radarr":
            await add(label, radarr.get_disk_space(inst.url, inst.api_key))

    return list(volumes.values())
