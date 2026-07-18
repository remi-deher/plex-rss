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


# (job, label, description, settings_field, settings_unit, default_seconds, fixed_schedule_note)
JOB_CATALOG = [
    (
        "watchlist",
        "Watchlist Plex",
        "Recupere la watchlist Plex/RSS et transmet les nouvelles demandes a Sonarr/Radarr/Prowlarr.",
        "poll_interval_seconds",
        "secondes",
        300,
        None,
    ),
    (
        "arr-statuses",
        "Disponibilite *arr",
        "Verifie si les demandes transmises a Sonarr/Radarr sont desormais disponibles.",
        "arr_poll_interval_seconds",
        "secondes",
        900,
        None,
    ),
    (
        "torrent-statuses",
        "Suivi torrents",
        "Suit la progression des torrents actifs (filet Prowlarr) et nettoie apres seed.",
        None,
        None,
        120,
        None,
    ),
    (
        "vff-statuses",
        "Scan VF complet",
        "Rescanne les medias en VO pour detecter un passage en VF (et les jamais-scannes).",
        "vff_recheck_interval_minutes",
        "minutes",
        21600,
        None,
    ),
    (
        "episode-tracking",
        "Suivi episodes (sans langue)",
        "Jalons episode/saison pour les series sans distinction VO/VF.",
        "vff_recheck_interval_minutes",
        "minutes",
        21600,
        None,
    ),
    (
        "episode-availability",
        "Disponibilite episodes (Sonarr)",
        "Resynchronise la disponibilite Sonarr par episode, pour un affichage instantane sur la fiche detail.",
        "vff_recheck_interval_minutes",
        "minutes",
        21600,
        None,
    ),
    (
        "new-vff",
        "Scan VF leger",
        "Analyse rapide des medias jamais scannes, comble le delai avant le scan complet.",
        None,
        None,
        60,
        None,
    ),
    (
        "seer-sync",
        "Synchronisation Seer",
        "Synchronise les demandes et utilisateurs Seer.",
        None,
        None,
        3600,
        None,
    ),
    (
        "plex-sync",
        "Synchronisation bibliotheque Plex (complete)",
        "Reconstruit entierement le cache local de la bibliotheque Plex.",
        "plex_sync_hour",
        "heure (0-23)",
        86400,
        None,
    ),
    (
        "plex-sync-recent",
        "Synchronisation bibliotheque Plex (recente)",
        "Detecte rapidement les medias recemment ajoutes a Plex, sans attendre le scan complet quotidien.",
        None,
        None,
        300,
        None,
    ),
    (
        "notification-purge",
        "Purge des journaux",
        "Purge les anciens journaux de notification selon la retention configuree.",
        None,
        None,
        86400,
        "Tous les jours a 03h00",
    ),
    (
        "digest",
        "Digest quotidien",
        "Envoie le recapitulatif quotidien aux utilisateurs abonnes, si active.",
        "digest_hour",
        "heure (0-23)",
        3600,
        None,
    ),
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
    for job, label, description, settings_field, settings_unit, default_seconds, fixed_schedule in JOB_CATALOG:
        interval_seconds = default_seconds
        settings_value = None
        if settings_field and settings:
            raw = getattr(settings, settings_field, None)
            if raw:
                settings_value = raw
                interval_seconds = raw * 60 if settings_unit == "minutes" else raw
        out.append({
            "job": job,
            "label": label,
            "description": description,
            "interval_seconds": interval_seconds,
            "configurable": settings_field is not None and settings_unit in ("minutes", "secondes"),
            "settings_field": settings_field,
            "settings_unit": settings_unit,
            "settings_value": settings_value,
            "fixed_schedule": fixed_schedule,
            "state": states.get(job),
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
