"""
Scheduler APScheduler gérant les deux tâches périodiques :

- poll_watchlists (défaut : toutes les 5 min)
    Lit les watchlists Plex et envoie les nouvelles demandes à Sonarr/Radarr.
    Retente également les demandes en statut `pending` ou `failed`.

- check_arr_statuses (toutes les 15 min)
    Interroge Sonarr/Radarr pour détecter les médias devenus disponibles.
    Cette approche par polling (sans webhook) est identique à celle d'Overseerr.
    Fallback : si arr_id est absent, recherche par tvdb_id/imdb_id/tmdb_id.
"""

import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session
from .database import SessionLocal
from .models import Settings, PlexUser, MediaRequest, RequestStatus
from .services.watchlist import fetch_watchlist
from .services.sonarr import add_series, is_series_available
from .services.radarr import add_movie, is_movie_available
from .services.email_service import (
    send_request_notification,
    send_failure_notification,
    send_available_notification,
)
from .services.notifications import send_all as send_push

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


# ---------------------------------------------------------------------------
# Cycle de vie du scheduler
# ---------------------------------------------------------------------------

def start_scheduler(poll_minutes: int = 5):
    """Enregistre les deux jobs et démarre le scheduler."""
    scheduler.add_job(poll_watchlists, "interval", minutes=poll_minutes, id="watchlist_poll", replace_existing=True)
    scheduler.add_job(check_arr_statuses, "interval", minutes=15, id="arr_status_check", replace_existing=True)
    scheduler.start()
    logger.info(f"Scheduler started (poll every {poll_minutes}m)")


def update_poll_interval(minutes: int):
    """Replanifie le job de polling sans redémarrer le scheduler."""
    scheduler.reschedule_job("watchlist_poll", trigger=IntervalTrigger(minutes=minutes))
    logger.info(f"Poll interval updated to {minutes}m")


# ---------------------------------------------------------------------------
# Fonctions utilitaires partagées
# ---------------------------------------------------------------------------

async def sync_users_from_feed(items: list[dict], db: Session):
    """Crée automatiquement un PlexUser pour chaque plex_user_id inconnu trouvé dans le flux."""
    known_ids = {u.plex_user_id for u in db.query(PlexUser).all()}
    new_ids = {item["plex_user_id"] for item in items if item.get("plex_user_id")} - known_ids
    for uid in new_ids:
        db.add(PlexUser(plex_user_id=uid, display_name=None, enabled=True))
        logger.info(f"Auto-discovered Plex user: {uid}")
    if new_ids:
        db.commit()


async def _submit_to_arr(settings: Settings, item: dict) -> tuple[int | None, bool, str | None]:
    """Envoie un média à Sonarr (séries) ou Radarr (films).

    Returns:
        (arr_id, already_existed, arr_slug)
        - arr_id         : ID interne Sonarr/Radarr, None si échec
        - already_existed: True si le média était déjà présent dans *arr
        - arr_slug       : titleSlug (Sonarr) ou titleSlug (Radarr) pour les liens
    """
    if item["media_type"] == "show" and settings.sonarr_enabled and settings.sonarr_url:
        return await add_series(
            settings.sonarr_url, settings.sonarr_api_key,
            settings.sonarr_quality_profile_id, settings.sonarr_root_folder,
            item,
        )
    if item["media_type"] == "movie" and settings.radarr_enabled and settings.radarr_url:
        return await add_movie(
            settings.radarr_url, settings.radarr_api_key,
            settings.radarr_quality_profile_id, settings.radarr_root_folder,
            item,
        )
    return None, False, None


async def _notify_request(settings: Settings, req: MediaRequest, db: Session):
    """Envoie les notifications de nouvelle demande (email + push Discord/Telegram)."""
    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    recipient = (user_obj.notification_email if user_obj else None) or settings.smtp_from

    if settings.email_on_request and recipient and not req.request_mail_sent:
        try:
            await send_request_notification(settings, req, recipient)
            req.request_mail_sent = True
            db.commit()
        except Exception as e:
            logger.error(f"Request email failed for '{req.title}': {e}")

    await send_push(settings, req, "request")


async def _notify_failure(settings: Settings, req: MediaRequest, db: Session):
    """Envoie les notifications d'échec de transmission (email + push)."""
    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    recipient = (user_obj.notification_email if user_obj else None) or settings.smtp_from

    if settings.email_on_request and recipient:
        try:
            arr_name = "Sonarr" if req.media_type == "show" else "Radarr"
            await send_failure_notification(
                settings, req, recipient,
                f"Impossible de transmettre a {arr_name}. Verifiez la configuration.",
            )
        except Exception as e:
            logger.error(f"Failure email failed for '{req.title}': {e}")

    await send_push(settings, req, "failed")


async def _notify_available(settings: Settings, req: MediaRequest, db: Session):
    """Envoie les notifications de disponibilité (email + push).

    Le flag available_mail_sent évite d'envoyer l'email plusieurs fois si le
    job check_arr_statuses repasse sur le même item (ex. redémarrage du scheduler).
    """
    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    recipient = (user_obj.notification_email if user_obj else None) or settings.smtp_from

    if settings.email_on_available and recipient and not req.available_mail_sent:
        try:
            await send_available_notification(settings, req, recipient)
            req.available_mail_sent = True
            db.commit()
        except Exception as e:
            logger.error(f"Available email failed for '{req.title}': {e}")

    await send_push(settings, req, "available")


# ---------------------------------------------------------------------------
# Jobs planifiés
# ---------------------------------------------------------------------------

async def poll_watchlists():
    """Lit les watchlists Plex et synchronise les demandes vers Sonarr/Radarr.

    Logique :
    1. Récupère les éléments depuis l'API Plex ou le flux RSS (selon config).
    2. Auto-crée les utilisateurs inconnus.
    3. Pour chaque item d'un utilisateur actif :
       - Si demande inexistante : création + envoi à *arr.
       - Si demande en `pending` ou `failed` : tentative de renvoi.
       - Si déjà `sent_to_arr` ou `available` : ignoré.
    4. Notifie selon le résultat (succès, échec, déjà existant).
    """
    logger.info("Polling watchlists...")
    db: Session = SessionLocal()
    try:
        settings = db.query(Settings).first()
        if not settings:
            return

        items = await fetch_watchlist(settings)
        if not items:
            logger.info("No watchlist items returned")
            return

        await sync_users_from_feed(items, db)

        all_users = db.query(PlexUser).all()
        users_map = {u.plex_user_id: u for u in all_users}
        enabled_ids = {u.plex_user_id for u in all_users if u.enabled}
        has_filter = len(all_users) > 0

        new_count = 0
        for item in items:
            uid = item.get("plex_user_id", "unknown")

            # Ignorer les utilisateurs désactivés si la table utilisateurs est renseignée
            if has_filter and uid not in enabled_ids:
                continue

            user_obj = users_map.get(uid)
            display_name = (user_obj.display_name if user_obj else None) or uid

            existing = db.query(MediaRequest).filter(
                MediaRequest.plex_user_id == uid,
                MediaRequest.title == item["title"],
                MediaRequest.media_type == item["media_type"],
            ).first()

            if existing:
                # Ne retenter que les statuts récupérables
                if existing.status in (RequestStatus.pending, RequestStatus.failed):
                    req = existing
                else:
                    continue
            else:
                req = MediaRequest(
                    plex_user_id=uid,
                    plex_user=display_name,
                    title=item["title"],
                    year=item.get("year"),
                    media_type=item["media_type"],
                    tmdb_id=item.get("tmdb_id"),
                    tvdb_id=item.get("tvdb_id"),
                    imdb_id=item.get("imdb_id"),
                    plex_guid=item.get("plex_guid"),
                    poster_url=item.get("poster_url"),
                    overview=item.get("overview", ""),
                    source=item.get("source"),
                    status=RequestStatus.pending,
                )
                db.add(req)
                db.flush()

            already_existed = False
            try:
                arr_id, already_existed, arr_slug = await _submit_to_arr(settings, item)
                req.status = RequestStatus.sent_to_arr
                req.arr_id = arr_id
                req.arr_slug = arr_slug
            except Exception as e:
                logger.error(f"Failed to send '{item['title']}' to arr: {e}")
                req.status = RequestStatus.failed

            db.commit()
            new_count += 1

            if already_existed:
                # Média déjà dans *arr : pas de notification (évite le spam au redémarrage)
                logger.info(f"'{item['title']}' already in arr — skipping notifications")
            elif req.status == RequestStatus.sent_to_arr:
                await _notify_request(settings, req, db)
            elif req.status == RequestStatus.failed:
                await _notify_failure(settings, req, db)

        logger.info(f"Poll complete: {new_count} requests processed")

    except Exception as e:
        logger.error(f"Poll error: {e}")
    finally:
        db.close()


async def check_arr_statuses():
    """Vérifie si des demandes `sent_to_arr` sont désormais disponibles dans *arr.

    Stratégie de lookup (sans webhook) :
    1. Si arr_id connu → GET /api/v3/series/{id} ou /api/v3/movie/{id}
    2. Sinon → scan de la liste complète filtré par tvdb_id/tmdb_id/imdb_id
       (cas des demandes créées avant la configuration de Sonarr/Radarr)

    Disponibilité :
    - Sonarr : statistics.episodeFileCount > 0
    - Radarr : hasFile == true
    """
    logger.info("Checking arr statuses...")
    db: Session = SessionLocal()
    try:
        settings = db.query(Settings).first()
        if not settings:
            return

        candidates = db.query(MediaRequest).filter(
            MediaRequest.status == RequestStatus.sent_to_arr,
        ).all()

        if not candidates:
            return

        logger.info(f"Checking {len(candidates)} sent_to_arr requests...")

        for req in candidates:
            available = False
            new_arr_id = None
            new_slug = None
            try:
                if req.media_type == "show" and settings.sonarr_url and settings.sonarr_api_key:
                    available, new_arr_id, new_slug = await is_series_available(
                        settings.sonarr_url, settings.sonarr_api_key,
                        arr_id=req.arr_id, tvdb_id=req.tvdb_id,
                    )
                elif req.media_type == "movie" and settings.radarr_url and settings.radarr_api_key:
                    available, new_arr_id, new_slug = await is_movie_available(
                        settings.radarr_url, settings.radarr_api_key,
                        arr_id=req.arr_id, tmdb_id=req.tmdb_id, imdb_id=req.imdb_id,
                    )
            except Exception as e:
                logger.warning(f"Status check error for '{req.title}': {e}")
                continue

            # Mettre à jour arr_id / arr_slug si on les découvre maintenant
            if new_arr_id and not req.arr_id:
                req.arr_id = new_arr_id
            if new_slug and not req.arr_slug:
                req.arr_slug = new_slug

            if available:
                req.status = RequestStatus.available
                req.available_at = datetime.utcnow()
                db.commit()
                logger.info(f"'{req.title}' is now available")
                await _notify_available(settings, req, db)
            elif new_arr_id or new_slug:
                db.commit()

        logger.info("Arr status check complete")

    except Exception as e:
        logger.error(f"check_arr_statuses error: {e}")
    finally:
        db.close()
