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

from ..database import AsyncSessionLocal, get_db_async
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
import sqlalchemy
from ..dependencies import require_admin
from ..models import ArrInstance, Settings
from ..utils import now_utc

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
        "description": "Remplace la date affichée (\"Demandée le\") par la vraie date d'ajout à la watchlist Plex (RSS/API) ou de création côté Seer, au lieu de la date de première détection par l'app — n'envoie aucune notification.",
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
    "recover-sqlite": {
        "label": "Récupérer l'ancienne base SQLite",
        "description": "Ré-importe les utilisateurs, requêtes et historiques manquants depuis plex_rss.db.",
        "icon": "bi-database-fill-up",
        "color": "danger",
    },
    "resync-availability": {
        "label": "Resynchroniser les états de disponibilité",
        "description": (
            "Revérifie les séries déjà \"Disponible\" dont le détail par saison n'a jamais été "
            "renseigné (ex : passées disponibles avant l'introduction du suivi partiel) — les "
            "repasse en \"Partiellement disponible\" si elles ne sont en réalité pas complètes. "
            "N'envoie aucune notification (rattrapage silencieux) — un vrai nouveau progrès "
            "sera notifié normalement dès le prochain cycle planifié."
        ),
        "icon": "bi-arrow-repeat",
        "color": "warning",
    },
}


# ---------------------------------------------------------------------------
# Exécuteurs d'actions
# ---------------------------------------------------------------------------


async def _run_check_arr_statuses(run: MaintenanceRun):
    emit = _Emit(run, logging.getLogger("app.maintenance"))
    db = AsyncSessionLocal()
    try:
        from ..models import MediaRequest, RequestStatus
        from ..scheduler import (
            check_arr_statuses,
            is_movie_available,
            is_series_available,
        )
        from ..services.availability_service import (
            confirm_available_from_plex,
            note_arr_processed,
            should_confirm_available,
        )
        from ..services.seer import is_request_available as seer_available

        settings = (await db.execute(select(Settings))).scalars().first()
        if not settings:
            emit.warn("Aucun paramètre configuré.")
            return

        candidates = (await db.execute(select(MediaRequest).filter(MediaRequest.status == RequestStatus.sent_to_arr))).scalars().all()

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
                if await should_confirm_available(db, req, settings=settings):
                    changed = await confirm_available_from_plex(
                        settings,
                        req,
                        db,
                        source="plex_sync",
                    )
                    if changed:
                        newly_available += 1
                    emit.ok(f"OK '{req.title}' - disponible confirme par Plex")
                else:
                    await note_arr_processed(db, req)
                    await db.commit()
                    emit.info(f"- '{req.title}' - traite cote service, attente Plex")
                continue
            else:
                emit.info(f"· '{req.title}' — toujours en attente")

        run.progress = 100
        emit.ok(f"Terminé — {newly_available} nouveau(x) disponible(s) sur {len(candidates)} vérifiée(s).")
    except Exception as e:
        emit.err(f"Erreur inattendue : {e}")
        raise
    finally:
        await db.close()


async def _run_resync_availability(run: MaintenanceRun):
    emit = _Emit(run, logging.getLogger("app.maintenance"))
    db = AsyncSessionLocal()
    try:
        from ..models import MediaRequest, RequestStatus

        before = {
            r.id: {
                "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                "episodes_available_count": r.episodes_available_count,
                "episodes_aired_count": r.episodes_aired_count,
                "episodes_total_count": r.episodes_total_count,
                "has_vf": r.has_vf,
            }
            for r in (await db.execute(
                select(MediaRequest).filter(
                    MediaRequest.status == RequestStatus.available, MediaRequest.media_type == "show"
                )
            )).scalars().all()
        }
        emit.info(f"{len(before)} série(s) 'Disponible' à revérifier…")
        run.progress = 10

        from ..services.arr_tracker import check_arr_statuses
        from ..job_queue import (
            clear_resync_notification_baselines,
            set_resync_notification_baselines,
        )
        from ..notification_queue import cancel_pending_availability_notifications

        # Le resync tourne dans l'API, tandis que les cron, webhooks et livraisons
        # tournent potentiellement dans d'autres processus/conteneurs. On partage
        # donc uniquement l'état historique des séries ciblées, pas un mute global.
        await set_resync_notification_baselines(before)
        try:
            cancelled_notifications = await cancel_pending_availability_notifications(list(before))
            if cancelled_notifications:
                emit.info(
                    f"{cancelled_notifications} notification(s) de disponibilité en attente supprimée(s)"
                )
            await check_arr_statuses(full_resync=True, notify=False)
        finally:
            await clear_resync_notification_baselines(list(before))
        run.progress = 90

        # check_arr_statuses() commit ses changements via sa propre session (AsyncSessionLocal
        # distincte) : sans expire_all(), cette session locale renverrait les objets mis en
        # cache lors de la requete `before` ci-dessus, pas leur etat reellement a jour en base.
        db.expire_all()
        after = (await db.execute(
            select(MediaRequest).filter(MediaRequest.id.in_(list(before.keys())))
        )).scalars().all()
        demoted = [r for r in after if r.status == RequestStatus.partially_available]
        for r in demoted:
            emit.info(f"'{r.title}' repassée en Partiellement disponible ({r.episodes_available_count}/{r.episodes_total_count})")

        run.progress = 100
        emit.ok(f"Terminé — {len(demoted)} série(s) corrigée(s) sur {len(before)} revérifiée(s).")
    except Exception as e:
        emit.err(f"Erreur inattendue : {e}")
        raise
    finally:
        await db.close()


async def _run_health_check(run: MaintenanceRun):
    emit = _Emit(run, logging.getLogger("app.maintenance"))
    db = AsyncSessionLocal()
    try:
        settings = (await db.execute(select(Settings))).scalars().first()
        if not settings:
            emit.warn("Aucun paramètre configuré.")
            return

        services: list[tuple[str, "str | ArrInstance"]] = []
        if settings.plex_url and settings.plex_token:
            services.append(("Plex API", "plex"))
        if settings.plex_rss_url:
            services.append(("Plex RSS", "plex-rss"))
        for inst in (
            (await db.execute(select(ArrInstance).filter(ArrInstance.enabled, ArrInstance.arr_type.in_(["sonarr", "radarr"])).order_by(ArrInstance.arr_type, ArrInstance.is_default.desc(), ArrInstance.name))).scalars().all()
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
        await db.close()


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
    db = AsyncSessionLocal()
    try:
        from ..models import MediaRequest, RequestStatus
        from ..scheduler import poll_watchlists

        failed = (await db.execute(select(MediaRequest).filter(MediaRequest.status == RequestStatus.failed))).scalars().all()
        if not failed:
            emit.info("Aucune demande en échec.")
            run.progress = 100
            return
        emit.info(f"{len(failed)} demande(s) en échec — repassage en pending…")
        for req in failed:
            from ..services.request_lifecycle import transition_request

            await transition_request(db, req, "retry", source="maintenance")
        await db.commit()
        run.progress = 40
        emit.info("Déclenchement du polling…")
        await poll_watchlists()
        run.progress = 100
        emit.ok(f"{len(failed)} demande(s) relancée(s).")
    except Exception as e:
        emit.err(str(e))
        raise
    finally:
        await db.close()


async def _run_recalculate_dates(run: MaintenanceRun):
    """Corrige requested_at depuis les vraies dates Seer + watchlist Plex (RSS/API), sans
    jamais notifier : sync_seer_requests/sync_plex_dates ne font que mettre à jour la
    colonne, aucun _notify()/enqueue() n'est appelé sur ce chemin."""
    emit = _Emit(run, logging.getLogger("app.maintenance"))
    db = AsyncSessionLocal()
    try:
        emit.info("Resynchronisation des dates depuis Seer…")
        run.progress = 10
        from ..scheduler import sync_seer_requests
        from ..services.watchlist_poller import sync_plex_dates

        await sync_seer_requests()
        run.progress = 50
        emit.info("Resynchronisation des dates depuis la watchlist Plex (RSS/API)…")
        await sync_plex_dates(db)
        run.progress = 100
        emit.ok("Dates recalculées.")
    except Exception as e:
        emit.err(str(e))
        raise
    finally:
        await db.close()


async def _run_enrich_and_merge(run: MaintenanceRun):
    emit = _Emit(run, logging.getLogger("app.maintenance"))
    db = AsyncSessionLocal()
    try:
        from ..models import MediaRequest, Settings
        from ..services.radarr import resolve_tmdb_id as radarr_resolve
        from ..services.seer import _headers, _resolve_tmdb_id

        settings = (await db.execute(select(Settings))).scalars().first()
        radarr_ok = bool(settings and settings.radarr_url and settings.radarr_api_key)
        seer_ok = bool(settings and settings.seer_url and settings.seer_api_key)
        if not radarr_ok and not seer_ok:
            emit.warn("Ni Radarr ni Seer configuré — impossible de résoudre les tmdb_id.")
            run.progress = 100
            return

        no_tmdb = (await db.execute(select(MediaRequest).filter(MediaRequest.tmdb_id.is_(None)))).scalars().all()
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
            await db.commit()
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
        await db.close()


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


async def _run_recover_sqlite(run: MaintenanceRun):
    emit = _Emit(run, logging.getLogger("app.maintenance"))
    emit.info("Démarrage de la récupération SQLite...")
    try:
        import sys
        import asyncio
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "scripts/recover_sqlite_data.py",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode().strip()
            if text:
                emit.info(text)
        await proc.wait()
        if proc.returncode == 0:
            emit.ok("Récupération SQLite terminée.")
        else:
            emit.err(f"Le script a échoué avec le code {proc.returncode}")
            raise RuntimeError(f"Code {proc.returncode}")
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
    "recover-sqlite": _run_recover_sqlite,
    "resync-availability": _run_resync_availability,
}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

async def _is_action_enabled(action: str, db: AsyncSession) -> tuple[bool, str | None]:
    from sqlalchemy import select
    from ..models import Settings
    settings = (await db.execute(select(Settings))).scalars().first()
    if not settings:
        return True, None

    if action.startswith("seer-"):
        if not settings.seer_enabled:
            return False, "Seer n'est pas activé dans les paramètres."
        if not settings.seer_url or not settings.seer_api_key:
            return False, "L'URL ou la clé API Seer n'est pas configurée."

    if action == "discover-users":
        if not settings.plex_rss_url:
            return False, "Le flux RSS Plex n'est pas configuré."

    return True, None

@router.get("/actions")
async def list_actions(db: AsyncSession = Depends(get_db_async), _: None = Depends(require_admin)):
    result = {}
    for key, meta in ACTIONS_META.items():
        last = _last_runs.get(key)
        
        enabled, disabled_reason = await _is_action_enabled(key, db)
        
        result[key] = {
            **meta,
            "enabled": enabled,
            "disabled_reason": disabled_reason,
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
async def start_run(action: str, db: AsyncSession = Depends(get_db_async), _: None = Depends(require_admin)):
    if action not in _ACTION_RUNNERS:
        raise HTTPException(404, f"Action inconnue : {action}")

    enabled, reason = await _is_action_enabled(action, db)
    if not enabled:
        raise HTTPException(400, f"Action désactivée : {reason}")

    from ..job_queue import arq_enabled, enqueue_job, set_json

    if arq_enabled():
        run_id = uuid.uuid4().hex[:12]
        queued = MaintenanceRun(action=action, status="queued", started_at=now_utc().isoformat())
        await set_json(f"plexarr:maintenance:{run_id}", {"run_id": run_id, **queued.__dict__})
        shared_jobs = {"check-arr-statuses": "job_arr_statuses", "discover-users": "job_watchlist"}
        function = shared_jobs.get(action)
        if function:
            job_id = await enqueue_job(function, True, run_id, action, job_id=f"maintenance:{run_id}")
        else:
            job_id = await enqueue_job("job_maintenance", run_id, action, job_id=f"maintenance:{run_id}")
        if not job_id:
            raise HTTPException(503, "Worker ARQ indisponible")
        return {"run_id": run_id, "job_id": job_id}

    run_id, run = _new_run(action)
    runner = globals().get(f"_run_{action.replace('-', '_')}", _ACTION_RUNNERS[action])

    async def _execute():
        try:
            await runner(run)
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
async def get_run(run_id: str, _: None = Depends(require_admin)):
    from ..job_queue import arq_enabled, get_json

    if arq_enabled():
        run = await get_json(f"plexarr:maintenance:{run_id}")
        if not run:
            raise HTTPException(404, "Run introuvable")
        return run
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
