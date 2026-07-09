"""
Router de maintenance — exécution asynchrone avec suivi en temps réel.

POST /api/maintenance/run/{action}  → démarre l'action, retourne run_id
GET  /api/maintenance/run/{run_id}  → status, progress (0-100), logs
GET  /api/maintenance/actions       → liste des actions disponibles
"""

import asyncio
import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ..database import SessionLocal
from ..dependencies import require_admin
from ..models import ArrInstance, Settings
from ..utils import now_utc, now_utc_naive

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])

# ---------------------------------------------------------------------------
# Store en mémoire des runs
# ---------------------------------------------------------------------------


@dataclass
class MaintenanceRun:
    action: str
    status: str = "running"  # running | done | error
    progress: float = 0.0
    logs: list = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""


_runs: dict[str, MaintenanceRun] = {}
_last_runs: dict[str, MaintenanceRun] = {}  # action → dernier run terminé
_MAX_RUNS = 30


def _new_run(action: str) -> tuple[str, MaintenanceRun]:
    run_id = uuid.uuid4().hex[:12]
    run = MaintenanceRun(action=action, started_at=now_utc().isoformat())
    _runs[run_id] = run
    if len(_runs) > _MAX_RUNS:
        del _runs[next(iter(_runs))]
    return run_id, run


class _Emit:
    """Envoie un message dans le run ET dans le logger Python."""

    _PREFIXES = {"info": "[INFO]", "ok": "[OK]", "warn": "[WARN]", "err": "[ERR]"}

    def __init__(self, run: MaintenanceRun, logger: logging.Logger):
        self._run = run
        self._log = logger

    def _push(self, level: str, msg: str):
        self._run.logs.append(f"{self._PREFIXES[level]} {msg}")
        getattr(self._log, "warning" if level == "warn" else ("error" if level == "err" else "info"))(msg)

    def info(self, msg: str):
        self._push("info", msg)

    def ok(self, msg: str):
        self._push("ok", msg)

    def warn(self, msg: str):
        self._push("warn", msg)

    def err(self, msg: str):
        self._push("err", msg)


# ---------------------------------------------------------------------------
# Actions disponibles (métadonnées UI)
# ---------------------------------------------------------------------------

ACTIONS_META = {
    "check-arr-statuses": {
        "label": "Vérifier les statuts arr",
        "description": "Force la vérification Sonarr/Radarr/Seer pour toutes les demandes en attente.",
        "icon": "bi-search",
        "color": "info",
    },
    "health-check": {
        "label": "Santé globale",
        "description": "Teste la connectivité de tous les services configurés (Plex, Sonarr, Radarr, Seer).",
        "icon": "bi-heart-pulse",
        "color": "success",
    },
    "seer-sync-users": {
        "label": "Synchroniser utilisateurs Seer",
        "description": "Relie les utilisateurs Plex à leurs comptes Seer et crée les Seer-only.",
        "icon": "bi-people",
        "color": "info",
    },
    "seer-sync-requests": {
        "label": "Synchroniser demandes Seer",
        "description": "Importe toutes les demandes Seer dans le suivi local.",
        "icon": "bi-cloud-arrow-down",
        "color": "info",
    },
    "discover-users": {
        "label": "Sync RSS",
        "description": "Lit le flux RSS Plex et découvre les nouveaux utilisateurs.",
        "icon": "bi-arrow-repeat",
        "color": "secondary",
    },
    "retry-failed": {
        "label": "Relancer les échouées",
        "description": "Repasse toutes les demandes en échec en attente et déclenche un poll.",
        "icon": "bi-arrow-clockwise",
        "color": "warning",
    },
    "recalculate-dates": {
        "label": "Recalculer les dates",
        "description": "Corrige requested_at et available_at depuis les données Seer.",
        "icon": "bi-calendar-check",
        "color": "secondary",
    },
    "merge-duplicates": {
        "label": "Fusionner les doublons",
        "description": "Détecte et consolide les demandes en double (même tmdb_id).",
        "icon": "bi-intersect",
        "color": "secondary",
    },
    "enrich-and-merge": {
        "label": "Enrichir & Fusionner",
        "description": "Résout les tmdb_id manquants (films : IMDB→TMDB via Radarr, sinon Seer par titre), puis fusionne tous les doublons. Corrige les doublons RSS ↔ Seer dus à des identifiants différents.",
        "icon": "bi-magic",
        "color": "primary",
    },
}


# ---------------------------------------------------------------------------
# Exécuteurs d'actions
# ---------------------------------------------------------------------------


async def _run_check_arr_statuses(run: MaintenanceRun):
    emit = _Emit(run, logging.getLogger("app.maintenance"))
    db = SessionLocal()
    try:
        from ..models import MediaRequest, RequestStatus
        from ..scheduler import (
            check_arr_statuses,
            is_movie_available,
            is_series_available,
        )
        from ..services.seer import is_request_available as seer_available

        settings = db.query(Settings).first()
        if not settings:
            emit.warn("Aucun paramètre configuré.")
            return

        candidates = db.query(MediaRequest).filter(MediaRequest.status == RequestStatus.sent_to_arr).all()

        if not candidates:
            emit.info("Aucune demande en statut 'sent_to_arr' à vérifier.")
            run.progress = 100
            return

        emit.info(f"{len(candidates)} demande(s) à vérifier…")
        newly_available = 0

        for i, req in enumerate(candidates):
            run.progress = round((i / len(candidates)) * 95)
            available = False
            try:
                if req.source == "seer" and settings.seer_url and settings.seer_api_key and req.arr_id:
                    available, *_ = await seer_available(settings.seer_url, settings.seer_api_key, req.arr_id)
                elif req.media_type == "show" and settings.sonarr_url and settings.sonarr_api_key:
                    available, *_ = await is_series_available(
                        settings.sonarr_url,
                        settings.sonarr_api_key,
                        arr_id=req.arr_id,
                        tvdb_id=req.tvdb_id,
                        tmdb_id=req.tmdb_id,
                        imdb_id=req.imdb_id,
                    )
                elif req.media_type == "movie" and settings.radarr_url and settings.radarr_api_key:
                    available, *_ = await is_movie_available(
                        settings.radarr_url,
                        settings.radarr_api_key,
                        arr_id=req.arr_id,
                        tmdb_id=req.tmdb_id,
                        imdb_id=req.imdb_id,
                    )
            except Exception as e:
                emit.warn(f"Erreur pour '{req.title}' : {e}")
                continue

            if available:
                req.status = RequestStatus.available
                req.available_at = now_utc_naive()
                db.commit()
                emit.ok(f"✓ '{req.title}' — disponible")
                newly_available += 1
            else:
                emit.info(f"· '{req.title}' — toujours en attente")

        run.progress = 100
        emit.ok(f"Terminé — {newly_available} nouveau(x) disponible(s) sur {len(candidates)} vérifiée(s).")
    except Exception as e:
        emit.err(f"Erreur inattendue : {e}")
        raise
    finally:
        db.close()


async def _run_health_check(run: MaintenanceRun):
    emit = _Emit(run, logging.getLogger("app.maintenance"))
    db = SessionLocal()
    try:
        settings = db.query(Settings).first()
        if not settings:
            emit.warn("Aucun paramètre configuré.")
            return

        services: list[tuple[str, "str | ArrInstance"]] = []
        if settings.plex_url and settings.plex_token:
            services.append(("Plex API", "plex"))
        if settings.plex_rss_url:
            services.append(("Plex RSS", "plex-rss"))
        for inst in (
            db.query(ArrInstance)
            .filter(ArrInstance.enabled, ArrInstance.arr_type.in_(["sonarr", "radarr"]))
            .order_by(ArrInstance.arr_type, ArrInstance.is_default.desc(), ArrInstance.name)
            .all()
        ):
            services.append((inst.name or inst.arr_type.title(), inst))
        if settings.seer_url and settings.seer_api_key:
            services.append(("Seer", "seer"))

        if not services:
            emit.warn("Aucun service configuré.")
            return

        emit.info(f"Test de {len(services)} service(s) configuré(s)…")
        step = 90 / len(services)

        async with httpx.AsyncClient(timeout=10) as client:
            for idx, (label, key) in enumerate(services):
                run.progress = round(5 + idx * step)
                try:
                    if key == "plex":
                        url = f"{settings.plex_url.rstrip('/')}/identity"
                        r = await client.get(url, params={"X-Plex-Token": settings.plex_token})
                        r.raise_for_status()
                        emit.ok(f"✓ {label} — OK ({r.elapsed.microseconds // 1000} ms)")
                    elif key == "plex-rss":
                        r = await client.get(settings.plex_rss_url)
                        r.raise_for_status()
                        emit.ok(f"✓ {label} — OK ({r.elapsed.microseconds // 1000} ms)")
                    elif isinstance(key, ArrInstance):
                        url = f"{key.url.rstrip('/')}/api/v3/system/status"
                        r = await client.get(url, headers={"X-Api-Key": key.api_key})
                        r.raise_for_status()
                        version = r.json().get("version", "?")
                        emit.ok(f"✓ {label} — OK v{version} ({r.elapsed.microseconds // 1000} ms)")
                    elif key == "sonarr":
                        url = f"{settings.sonarr_url.rstrip('/')}/api/v3/system/status"
                        r = await client.get(url, headers={"X-Api-Key": settings.sonarr_api_key})
                        r.raise_for_status()
                        version = r.json().get("version", "?")
                        emit.ok(f"✓ {label} — OK v{version} ({r.elapsed.microseconds // 1000} ms)")
                    elif key == "radarr":
                        url = f"{settings.radarr_url.rstrip('/')}/api/v3/system/status"
                        r = await client.get(url, headers={"X-Api-Key": settings.radarr_api_key})
                        r.raise_for_status()
                        version = r.json().get("version", "?")
                        emit.ok(f"✓ {label} — OK v{version} ({r.elapsed.microseconds // 1000} ms)")
                    elif key == "seer":
                        from ..services.seer import check_connection

                        ok, msg = await check_connection(settings.seer_url, settings.seer_api_key)
                        if ok:
                            emit.ok(f"✓ {label} — {msg}")
                        else:
                            emit.err(f"✗ {label} — {msg}")
                except Exception as e:
                    emit.err(f"✗ {label} — {e}")

        run.progress = 100
        emit.ok("Bilan terminé.")
    except Exception as e:
        emit.err(f"Erreur inattendue : {e}")
        raise
    finally:
        db.close()


async def _run_seer_sync_users(run: MaintenanceRun):
    emit = _Emit(run, logging.getLogger("app.maintenance"))
    handler = _LogCaptureHandler(run)
    sched_log = logging.getLogger("app.scheduler")
    sched_log.addHandler(handler)
    try:
        emit.info("Démarrage sync utilisateurs Seer…")
        run.progress = 10
        from ..scheduler import sync_seer_users

        await sync_seer_users()
        run.progress = 100
        emit.ok("Sync utilisateurs terminée.")
    except Exception as e:
        emit.err(str(e))
        raise
    finally:
        sched_log.removeHandler(handler)


async def _run_seer_sync_requests(run: MaintenanceRun):
    emit = _Emit(run, logging.getLogger("app.maintenance"))
    handler = _LogCaptureHandler(run)
    sched_log = logging.getLogger("app.scheduler")
    sched_log.addHandler(handler)
    try:
        emit.info("Démarrage sync demandes Seer…")
        run.progress = 10
        from ..scheduler import sync_seer_requests

        await sync_seer_requests()
        run.progress = 100
        emit.ok("Sync demandes terminée.")
    except Exception as e:
        emit.err(str(e))
        raise
    finally:
        sched_log.removeHandler(handler)


async def _run_discover_users(run: MaintenanceRun):
    emit = _Emit(run, logging.getLogger("app.maintenance"))
    try:
        emit.info("Lecture du flux RSS…")
        run.progress = 20
        from ..scheduler import poll_watchlists

        await poll_watchlists()
        run.progress = 100
        emit.ok("Sync RSS terminée.")
    except Exception as e:
        emit.err(str(e))
        raise


async def _run_retry_failed(run: MaintenanceRun):
    emit = _Emit(run, logging.getLogger("app.maintenance"))
    db = SessionLocal()
    try:
        from ..models import MediaRequest, RequestStatus
        from ..scheduler import poll_watchlists

        failed = db.query(MediaRequest).filter(MediaRequest.status == RequestStatus.failed).all()
        if not failed:
            emit.info("Aucune demande en échec.")
            run.progress = 100
            return
        emit.info(f"{len(failed)} demande(s) en échec — repassage en pending…")
        for req in failed:
            req.status = RequestStatus.pending
        db.commit()
        run.progress = 40
        emit.info("Déclenchement du polling…")
        await poll_watchlists()
        run.progress = 100
        emit.ok(f"{len(failed)} demande(s) relancée(s).")
    except Exception as e:
        emit.err(str(e))
        raise
    finally:
        db.close()


async def _run_recalculate_dates(run: MaintenanceRun):
    emit = _Emit(run, logging.getLogger("app.maintenance"))
    try:
        emit.info("Resynchronisation des dates depuis Seer…")
        run.progress = 10
        from ..scheduler import sync_seer_requests

        await sync_seer_requests()
        run.progress = 100
        emit.ok("Dates recalculées.")
    except Exception as e:
        emit.err(str(e))
        raise


async def _run_enrich_and_merge(run: MaintenanceRun):
    emit = _Emit(run, logging.getLogger("app.maintenance"))
    db = SessionLocal()
    try:
        from ..models import MediaRequest, Settings
        from ..services.radarr import resolve_tmdb_id as radarr_resolve
        from ..services.seer import _headers, _resolve_tmdb_id

        settings = db.query(Settings).first()
        radarr_ok = bool(settings and settings.radarr_url and settings.radarr_api_key)
        seer_ok = bool(settings and settings.seer_url and settings.seer_api_key)
        if not radarr_ok and not seer_ok:
            emit.warn("Ni Radarr ni Seer configuré — impossible de résoudre les tmdb_id.")
            run.progress = 100
            return

        no_tmdb = db.query(MediaRequest).filter(MediaRequest.tmdb_id.is_(None)).all()
        emit.info(f"{len(no_tmdb)} demande(s) sans tmdb_id à enrichir…")
        emit.info(
            f"Sources : {'Radarr (films, IMDB→TMDB) ' if radarr_ok else ''}{'Seer (titre) ' if seer_ok else ''}".strip()
        )

        base = settings.seer_url.rstrip("/") if seer_ok else None
        headers = _headers(settings.seer_api_key) if seer_ok else None
        enriched = 0

        for i, req in enumerate(no_tmdb):
            run.progress = round((i / max(len(no_tmdb), 1)) * 60)
            try:
                from ..scheduler import _clean_title

                resolved = None
                # Films : IMDB → TMDB via Radarr (fiable, pas besoin de Seer)
                if radarr_ok and req.media_type == "movie" and req.imdb_id:
                    resolved = await radarr_resolve(settings.radarr_url, settings.radarr_api_key, req.imdb_id)
                    if resolved:
                        emit.info(f"tmdb_id={resolved} via Radarr → '{req.title}'")
                # Sinon, repli sur Seer par titre (séries, films sans IMDB)
                if not resolved and seer_ok:
                    item = {"title": _clean_title(req.title), "media_type": req.media_type}
                    resolved = await _resolve_tmdb_id(base, headers, item)
                    if resolved:
                        emit.info(f"tmdb_id={resolved} via Seer → '{req.title}'")
                if resolved:
                    req.tmdb_id = resolved
                    enriched += 1
            except Exception as e:
                emit.warn(f"Erreur pour '{req.title}': {e}")

        if enriched:
            db.commit()
            emit.ok(f"{enriched} tmdb_id résolu(s).")
        else:
            emit.info("Aucun tmdb_id résolu.")

        run.progress = 70
        emit.info("Fusion des doublons…")

        import io
        import sys

        from scripts.merge_duplicate_requests import merge_duplicates

        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            merge_duplicates(dry_run=False)
        finally:
            sys.stdout = old_stdout

        for line in buf.getvalue().splitlines():
            if line.strip():
                if "Suppressions" in line or "fusionné" in line:
                    emit.ok(line.strip())
                elif "⚠" in line or "ignorée" in line:
                    emit.warn(line.strip())
                else:
                    emit.info(line.strip())

        run.progress = 100
        emit.ok("Enrichissement & fusion terminés.")
    except Exception as e:
        emit.err(f"Erreur inattendue : {e}")
        raise
    finally:
        db.close()


async def _run_merge_duplicates(run: MaintenanceRun):
    emit = _Emit(run, logging.getLogger("app.maintenance"))
    try:
        emit.info("Analyse des doublons…")
        run.progress = 20
        from scripts.merge_duplicate_requests import merge_duplicates

        merge_duplicates(dry_run=False)
        run.progress = 100
        emit.ok("Fusion terminée.")
    except Exception as e:
        emit.err(str(e))
        raise


class _LogCaptureHandler(logging.Handler):
    """Capture les logs du scheduler et les injecte dans le run."""

    _LEVEL_MAP = {
        logging.INFO: "[INFO]",
        logging.WARNING: "[WARN]",
        logging.ERROR: "[ERR]",
        logging.DEBUG: "[INFO]",
    }

    def __init__(self, run: MaintenanceRun):
        super().__init__()
        self._run = run

    def emit(self, record: logging.LogRecord):
        prefix = self._LEVEL_MAP.get(record.levelno, "[INFO]")
        self._run.logs.append(f"{prefix} {record.getMessage()}")


_ACTION_RUNNERS = {
    "check-arr-statuses": _run_check_arr_statuses,
    "health-check": _run_health_check,
    "seer-sync-users": _run_seer_sync_users,
    "seer-sync-requests": _run_seer_sync_requests,
    "discover-users": _run_discover_users,
    "retry-failed": _run_retry_failed,
    "recalculate-dates": _run_recalculate_dates,
    "merge-duplicates": _run_merge_duplicates,
    "enrich-and-merge": _run_enrich_and_merge,
}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/actions")
def list_actions(_: None = Depends(require_admin)):
    result = {}
    for key, meta in ACTIONS_META.items():
        last = _last_runs.get(key)
        result[key] = {
            **meta,
            "last_run": {
                "status": last.status,
                "finished_at": last.finished_at,
                "log_count": len(last.logs),
            }
            if last
            else None,
        }
    return result


@router.post("/run/{action}")
async def start_run(action: str, _: None = Depends(require_admin)):
    if action not in _ACTION_RUNNERS:
        raise HTTPException(404, f"Action inconnue : {action}")

    run_id, run = _new_run(action)

    async def _execute():
        try:
            await _ACTION_RUNNERS[action](run)
            run.status = "done"
        except Exception:
            run.status = "error"
        finally:
            run.progress = 100
            run.finished_at = now_utc().isoformat()
            _last_runs[action] = run

    asyncio.create_task(_execute())
    return {"run_id": run_id}


@router.get("/run/{run_id}")
def get_run(run_id: str, _: None = Depends(require_admin)):
    run = _runs.get(run_id)
    if not run:
        raise HTTPException(404, "Run introuvable")
    return {
        "run_id": run_id,
        "action": run.action,
        "status": run.status,
        "progress": run.progress,
        "logs": run.logs,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }
