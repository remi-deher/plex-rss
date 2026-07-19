"""Vue d'ensemble des taches planifiees (cron ARQ) : intervalles, dernier etat, historique.

Alimente l'onglet Reglages > Taches planifiees. Le catalogue est statique (les taches
sont definies dans app/jobs.py) ; l'etat courant vient de Redis (plexarr:jobs:state:*,
ecrit par jobs._state) et l'historique d'execution de la table job_run_logs
(ecrite par jobs._run des la premiere migration qui l'introduit).
"""
import json
import os

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import get_db_async
from ..dependencies import require_admin
from ..models import (
    JobRunLog,
    MediaRequest,
    SeriesAcquisitionBatch,
    Settings,
    SonarrQueueObservation,
)
from ..serializers import format_datetime

router = APIRouter(prefix="/api", tags=["scheduled-tasks"], dependencies=[Depends(require_admin)])


# settings_minute_field n'est renseigne que pour les taches "heure murale" (digest,
# la seule qui doit reellement partir a un instant precis plutot que suivre un simple
# intervalle periodique) qui ont, en plus de l'heure, une minute de declenchement
# (digest_minute).
JOB_CATALOG = [
    {
        "job": "sonarr-queue-monitor",
        "label": "File d'acquisition Sonarr",
        "description": "Suit chaque minute les telechargements, imports et blocages afin de regrouper les notifications de serie.",
        "settings_field": None,
        "settings_unit": None,
        "default_seconds": 60,
        "fixed_schedule": "Toutes les minutes",
    },
    {
        "job": "watchlist",
        "label": "Watchlist Plex",
        "description": "Recupere la watchlist Plex/RSS et transmet les nouvelles demandes a Sonarr/Radarr/Prowlarr.",
        "settings_field": "poll_interval_seconds",
        "settings_unit": "secondes",
        "default_seconds": 300,
        "fixed_schedule": None,
    },
    {
        "job": "arr-statuses",
        "label": "Disponibilite *arr",
        "description": "Verifie si les demandes transmises a Sonarr/Radarr sont desormais disponibles.",
        "settings_field": "arr_poll_interval_seconds",
        "settings_unit": "secondes",
        "default_seconds": 900,
        "fixed_schedule": None,
    },
    {
        "job": "torrent-statuses",
        "label": "Suivi torrents",
        "description": "Suit la progression des torrents actifs (filet Prowlarr) et nettoie apres seed.",
        "settings_field": None,
        "settings_unit": None,
        "default_seconds": 120,
        "fixed_schedule": None,
    },
    {
        "job": "vff-statuses",
        "label": "Scan VF complet",
        "description": "Rescanne les medias en VO pour detecter un passage en VF (et les jamais-scannes).",
        "settings_field": "vff_recheck_interval_minutes",
        "settings_unit": "minutes",
        "default_seconds": 21600,
        "fixed_schedule": None,
    },
    {
        "job": "episode-tracking",
        "label": "Suivi episodes (sans langue)",
        "description": "Jalons episode/saison pour les series sans distinction VO/VF.",
        "settings_field": "vff_recheck_interval_minutes",
        "settings_unit": "minutes",
        "default_seconds": 21600,
        "fixed_schedule": None,
    },
    {
        "job": "episode-availability",
        "label": "Disponibilite episodes (Sonarr)",
        "description": "Resynchronise la disponibilite Sonarr par episode, pour un affichage instantane sur la fiche detail.",
        "settings_field": "vff_recheck_interval_minutes",
        "settings_unit": "minutes",
        "default_seconds": 21600,
        "fixed_schedule": None,
    },
    {
        "job": "new-vff",
        "label": "Scan VF leger",
        "description": "Analyse rapide des medias jamais scannes, comble le delai avant le scan complet.",
        "settings_field": None,
        "settings_unit": None,
        "default_seconds": 60,
        "fixed_schedule": None,
    },
    {
        "job": "seer-sync",
        "label": "Synchronisation Seer",
        "description": "Synchronise les demandes et utilisateurs Seer.",
        "settings_field": None,
        "settings_unit": None,
        "default_seconds": 3600,
        "fixed_schedule": None,
    },
    {
        "job": "plex-sync",
        "label": "Synchronisation bibliotheque Plex (complete)",
        "description": "Reconstruit entierement le cache local de la bibliotheque Plex.",
        "settings_field": "plex_sync_interval_hours",
        "settings_unit": "heures",
        "default_seconds": 86400,
        "fixed_schedule": None,
    },
    {
        "job": "plex-sync-recent",
        "label": "Synchronisation bibliotheque Plex (recente)",
        "description": "Detecte rapidement les medias recemment ajoutes a Plex, sans attendre le scan complet quotidien.",
        "settings_field": "plex_sync_recent_interval_minutes",
        "settings_unit": "minutes",
        "default_seconds": 300,
        "fixed_schedule": None,
    },
    {
        "job": "notification-purge",
        "label": "Purge des journaux",
        "description": "Purge les anciens journaux de notification selon la retention configuree.",
        "settings_field": None,
        "settings_unit": None,
        "default_seconds": 86400,
        "fixed_schedule": "Tous les jours a 03h00",
    },
    {
        "job": "digest",
        "label": "Digest quotidien",
        "description": "Envoie le recapitulatif quotidien aux utilisateurs abonnes, si active.",
        "settings_field": "digest_hour",
        "settings_unit": "heure (0-23)",
        "settings_minute_field": "digest_minute",
        "default_seconds": 3600,
        "fixed_schedule": None,
    },
]


def _json_list(value: str | None) -> list:
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


@router.get("/acquisition-batches")
async def list_acquisition_batches(limit: int = 50, db: AsyncSession = Depends(get_db_async)):
    """Etat exploitable des lots actifs et des imports Sonarr recents/bloques."""
    batches = (
        await db.execute(
            select(SeriesAcquisitionBatch, MediaRequest)
            .outerjoin(MediaRequest, MediaRequest.id == SeriesAcquisitionBatch.request_id)
            .filter(SeriesAcquisitionBatch.status.in_(("open", "stabilizing")))
            .order_by(SeriesAcquisitionBatch.opened_at.desc())
            .limit(min(max(limit, 1), 200))
        )
    ).all()
    batch_ids = [batch.id for batch, _request in batches]
    observations = []
    if batch_ids:
        observations = (
            await db.execute(
                select(SonarrQueueObservation)
                .filter(
                    SonarrQueueObservation.batch_id.in_(batch_ids),
                    SonarrQueueObservation.resolved_at.is_(None),
                )
                .order_by(SonarrQueueObservation.last_seen_at.desc())
            )
        ).scalars().all()
    by_batch: dict[int, list[SonarrQueueObservation]] = {}
    for observation in observations:
        by_batch.setdefault(observation.batch_id, []).append(observation)

    items = []
    for batch, request in batches:
        queue = by_batch.get(batch.id, [])
        items.append({
            "id": batch.id,
            "request_id": batch.request_id,
            "title": request.title if request else f"Serie Sonarr #{batch.arr_id}",
            "source": batch.source,
            "status": batch.status,
            "expected_scope": batch.expected_scope,
            "expected_seasons": _json_list(batch.expected_seasons),
            "pending_events": _json_list(batch.pending_events),
            "opened_at": format_datetime(batch.opened_at),
            "last_sonarr_activity_at": format_datetime(batch.last_sonarr_activity_at),
            "last_plex_change_at": format_datetime(batch.last_plex_change_at),
            "stabilization_started_at": format_datetime(batch.stabilization_started_at),
            "queue": [
                {
                    "id": observation.id,
                    "title": observation.title,
                    "season_number": observation.season_number,
                    "episode_number": observation.episode_number,
                    "state": observation.state,
                    "progress": observation.progress,
                    "blocked_checks": observation.consecutive_blocked_checks,
                    "error": observation.error_message,
                    "blocked_at": format_datetime(observation.blocked_at),
                    "last_seen_at": format_datetime(observation.last_seen_at),
                }
                for observation in queue
            ],
        })
    return {
        "items": items,
        "counts": {
            "active_batches": len(items),
            "active_queue": sum(1 for item in items for row in item["queue"] if row["state"] != "import_blocked"),
            "blocked_imports": sum(1 for item in items for row in item["queue"] if row["state"] == "import_blocked"),
        },
    }


async def _job_states() -> dict[str, dict]:
    states: dict[str, dict] = {}
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return states
    try:
        from redis.asyncio import Redis

        redis = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
        try:
            async for key in redis.scan_iter("plexarr:jobs:state:*"):
                raw = await redis.get(key)
                if raw:
                    data = json.loads(raw)
                    name = data.get("name") or key.rsplit(":", 1)[-1]
                    states[name] = data
        finally:
            await redis.aclose()
    except Exception:
        pass
    return states


@router.get("/scheduled-tasks")
async def list_scheduled_tasks(db: AsyncSession = Depends(get_db_async)):
    settings = (await db.execute(select(Settings))).scalars().first()
    states = await _job_states()

    out = []
    for entry in JOB_CATALOG:
        settings_field = entry["settings_field"]
        settings_unit = entry["settings_unit"]
        settings_minute_field = entry.get("settings_minute_field")
        interval_seconds = entry["default_seconds"]
        settings_value = None
        settings_minute_value = None
        if settings_field and settings:
            raw = getattr(settings, settings_field, None)
            if raw:
                settings_value = raw
                interval_seconds = raw * 3600 if settings_unit == "heures" else raw * 60 if settings_unit == "minutes" else raw
        if settings_minute_field and settings:
            settings_minute_value = getattr(settings, settings_minute_field, None)
        out.append({
            "job": entry["job"],
            "label": entry["label"],
            "description": entry["description"],
            "interval_seconds": interval_seconds,
            "configurable": settings_field is not None and settings_unit in ("minutes", "secondes", "heures"),
            "settings_field": settings_field,
            "settings_unit": settings_unit,
            "settings_value": settings_value,
            "settings_minute_field": settings_minute_field,
            "settings_minute_value": settings_minute_value,
            "fixed_schedule": entry["fixed_schedule"],
            "state": states.get(entry["job"]),
        })
    return out


@router.get("/scheduled-tasks/{job}/history")
async def scheduled_task_history(job: str, limit: int = 50, db: AsyncSession = Depends(get_db_async)):
    rows = (await db.execute(
        select(JobRunLog).filter(JobRunLog.job == job).order_by(JobRunLog.started_at.desc()).limit(min(limit, 200))
    )).scalars().all()
    return [
        {
            "id": r.id,
            "started_at": format_datetime(r.started_at),
            "duration_ms": r.duration_ms,
            "status": r.status,
            "error": r.error,
        }
        for r in rows
    ]
