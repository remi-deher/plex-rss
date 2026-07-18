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
from ..models import JobRunLog, Settings
from ..serializers import format_datetime

router = APIRouter(prefix="/api", tags=["scheduled-tasks"], dependencies=[Depends(require_admin)])


# settings_minute_field n'est renseigne que pour les taches "heure murale" (plex-sync,
# digest) qui ont, en plus de l'heure, une minute de declenchement (digest_minute,
# plex_sync_minute).
JOB_CATALOG = [
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
        "settings_field": "plex_sync_hour",
        "settings_unit": "heure (0-23)",
        "settings_minute_field": "plex_sync_minute",
        "default_seconds": 86400,
        "fixed_schedule": None,
    },
    {
        "job": "plex-sync-recent",
        "label": "Synchronisation bibliotheque Plex (recente)",
        "description": "Detecte rapidement les medias recemment ajoutes a Plex, sans attendre le scan complet quotidien.",
        "settings_field": None,
        "settings_unit": None,
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
                interval_seconds = raw * 60 if settings_unit == "minutes" else raw
        if settings_minute_field and settings:
            settings_minute_value = getattr(settings, settings_minute_field, None)
        out.append({
            "job": entry["job"],
            "label": entry["label"],
            "description": entry["description"],
            "interval_seconds": interval_seconds,
            "configurable": settings_field is not None and settings_unit in ("minutes", "secondes"),
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
