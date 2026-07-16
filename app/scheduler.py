"""
Scheduler APScheduler gérant la planification des tâches périodiques.

Les implémentations réelles des tâches sont déportées dans les modules sous app/services/.
Ce module conserve une compatibilité ascendante totale en réexportant les fonctions
et états globaux utilisés par les routeurs et les tests.
"""

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import sqlalchemy

from .database import AsyncSessionLocal
from .models import ArrInstance, Settings

# --- Imports des services pour réexportation (compatibilité ascendante) ---
from .notification_queue import enqueue as enqueue_notification
from .services.download_clients import delete_torrent, get_torrent_status
from .services.notification_orchestrator import (
    _add_co_requester,
    _get_recipients,
    _handle_show_progress_notification,
    _notify,
    _purge_notification_logs,
    _queue_milestone,
    _send_digest,
)
from .services.plex_sync import (
    _link_request_to_library_item,
    plex_sync_state,
    sync_plex_media,
)
from .services.radarr import get_all_movies, is_movie_available
from .services.seer import (
    _resolve_tmdb_id as _seer_resolve_tmdb_id,
)
from .services.seer import (
    get_user_requests as seer_get_user_requests,
)
from .services.seer import (
    get_users as seer_get_users,
)
from .services.seer import (
    is_request_available as seer_available,
)
from .services.seer_sync import (
    _seer_full_sync,
    sync_seer_requests,
    sync_seer_users,
)
from .services.sonarr import get_all_series, get_series_episode_stats, is_series_available
from .services.vff_scanner import (
    _invalidate_vf_cache,
    _load_known_vf_episodes,
    _parse_vff_libraries,
    _persist_episode_status,
    _scan_vf_blocking,
    _trigger_vf_search,
    check_episode_tracking,
    check_new_vf_availability,
    check_vf_statuses,
    episode_scan_state,
    trigger_vff_scan_background,
    vff_scan_state,
)
from .services.watchlist_poller import (
    _clean_title,
    _find_global_request,
    _submit_to_arr,
    add_torrent_to_client,
    fetch_watchlist,
    poll_watchlists,
    sync_users_from_feed,
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def start_scheduler(poll_seconds: int = 300):
    """Enregistre les jobs et démarre le scheduler.

    `poll_seconds` : intervalle de polling de la watchlist Plex, en secondes
    (permet un rafraîchissement sous la minute, façon Overseerr/Jellyseerr).
    """
    async with AsyncSessionLocal() as db:
        settings = (await db.execute(select(Settings))).scalars().first()
        digest_hour = settings.digest_hour if settings and settings.digest_enabled else None
        vff_interval = (
            settings.vff_recheck_interval_minutes if settings and settings.vff_recheck_interval_minutes else 360
        )

    # Poll watchlist : un premier passage ~15 s après le démarrage (rattrapage immédiat),
    # puis toutes les `poll_seconds`. coalesce + max_instances=1 évitent l'empilement si un
    # cycle dépasse l'intervalle (polling rapproché).
    scheduler.add_job(
        poll_watchlists,
        "interval",
        seconds=poll_seconds,
        id="watchlist_poll",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=15),
        max_instances=1,
        coalesce=True,
        # Tolère un léger retard (boucle asyncio ponctuellement saturée, ex. sync Plex au
        # démarrage) sans sauter le cycle — important pour un intervalle court comme 30 s.
        misfire_grace_time=30,
    )
    scheduler.add_job(check_arr_statuses, "interval", minutes=15, id="arr_status_check", replace_existing=True)
    scheduler.add_job(check_torrent_statuses, "interval", minutes=2, id="torrent_status_check", replace_existing=True)
    scheduler.add_job(check_vf_statuses, "interval", minutes=vff_interval, id="vf_status_check", replace_existing=True)
    scheduler.add_job(
        check_episode_tracking, "interval", minutes=vff_interval, id="episode_tracking_check", replace_existing=True
    )
    # Scan léger et fréquent, restreint aux médias jamais analysés (has_vf IS NULL) :
    # comble le trou laissé par un scan eager raté (scan_and_notify_availability) sans
    # attendre le prochain scan complet (potentiellement long, cf. vff_interval ci-dessus).
    scheduler.add_job(
        check_new_vf_availability, "interval", minutes=1, id="vf_new_availability_check", replace_existing=True
    )
    scheduler.add_job(_seer_full_sync, "interval", minutes=60, id="seer_sync", replace_existing=True)
    scheduler.add_job(_purge_notification_logs, "cron", hour=3, minute=0, id="notif_log_purge", replace_existing=True)
    # Le trigger "interval" ne se déclenche qu'après un premier cycle (ici 24 h) : sans
    # first-run au démarrage, un conteneur souvent redémarré ne resynchronise jamais la
    # bibliothèque Plex (elle reste figée). On force donc un premier passage ~30 s après
    # le boot, puis toutes les 24 h.
    scheduler.add_job(
        sync_plex_media,
        "interval",
        hours=24,
        id="plex_library_sync",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    if digest_hour is not None:
        scheduler.add_job(_send_digest, "cron", hour=digest_hour, minute=0, id="digest", replace_existing=True)
    scheduler.start()
    logger.info(f"Scheduler started (poll every {poll_seconds}s)")


def update_poll_interval(seconds: int):
    """Replanifie le job de polling watchlist (en secondes) sans redémarrer le scheduler."""
    if not scheduler.running or not scheduler.get_job("watchlist_poll"):
        logger.info("Poll interval saved; ARQ will read it on its next scheduling tick")
        return
    scheduler.reschedule_job("watchlist_poll", trigger=IntervalTrigger(seconds=seconds))
    logger.info(f"Poll interval updated to {seconds}s")


# --- Wrappers de déclenchement des jobs planifiés ---


async def check_arr_statuses(**kwargs):
    """Job planifié : vérification de la disponibilité des médias dans Sonarr/Radarr."""
    from .services.arr_tracker import check_arr_statuses as _check

    await _check(**kwargs)


async def check_torrent_statuses():
    """Job planifié : suivi des téléchargements torrents actifs."""
    from .services.arr_tracker import check_torrent_statuses as _check

    await _check()


async def _check_and_seed_instances_from_settings(db: AsyncSession, settings: Settings):
    """Fallback / compatibilité pour les tests unitaires et les premières exécutions."""
    count = (await db.execute(select(sqlalchemy.func.count(ArrInstance.id)))).scalar()
    if count == 0 and settings:
        if settings.sonarr_url and settings.sonarr_api_key:
            db.add(
                ArrInstance(
                    name="Sonarr Default",
                    arr_type="sonarr",
                    url=settings.sonarr_url,
                    api_key=settings.sonarr_api_key,
                    quality_profile_id=settings.sonarr_quality_profile_id,
                    root_folder=settings.sonarr_root_folder,
                    enabled=settings.sonarr_enabled if settings.sonarr_enabled is not None else True,
                    is_default=True,
                )
            )
        if settings.radarr_url and settings.radarr_api_key:
            db.add(
                ArrInstance(
                    name="Radarr Default",
                    arr_type="radarr",
                    url=settings.radarr_url,
                    api_key=settings.radarr_api_key,
                    quality_profile_id=settings.radarr_quality_profile_id,
                    root_folder=settings.radarr_root_folder,
                    enabled=settings.radarr_enabled if settings.radarr_enabled is not None else True,
                    is_default=True,
                    minimum_availability=settings.radarr_minimum_availability or "released",
                )
            )
        await db.commit()
