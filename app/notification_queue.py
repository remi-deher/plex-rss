"""
Queue asynchrone pour l'envoi des notifications (email + Discord + Telegram).

Au lieu d'attendre chaque envoi en ligne dans le scheduler (ce qui bloque le cycle
de polling), les notifications sont empilées dans une queue asyncio et traitées
par un worker indépendant.

Cycle de vie :
- `start_worker()` est appelé au démarrage de l'app (lifespan dans main.py).
- `enqueue()` est appelé par le scheduler pour chaque événement.
- Le worker ouvre sa propre session DB pour mettre à jour les flags d'envoi.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from . import metrics as app_metrics
from .database import SessionLocal
from .models import MediaRequest, NotificationLog, PendingNotification, PlexUser, Settings
from .services.email_service import (
    send_available_notification,
    send_available_vf_notification,
    send_available_vo_tracking_notification,
    send_episode_track_notification,
    send_failure_notification,
    send_partially_available_notification,
    send_request_notification,
    send_vf_available_notification,
    send_vo_only_notification,
)
from .services.notification_catalog import event_mail_flags
from .services.notifications import (
    send_discord,
    send_discord_to_webhook,
    send_gotify_notif,
    send_ntfy_notif,
    send_telegram,
    send_telegram_to_chat,
)
from .utils import now_utc, parse_email_list

logger = logging.getLogger(__name__)

_queue: asyncio.Queue = asyncio.Queue()
_worker_task: asyncio.Task | None = None

_RETRY_DELAYS = [2, 5]  # secondes entre chaque tentative


EMAIL_SENDERS = {
    "request": lambda settings, req, recipient, reason, display_name: send_request_notification(
        settings, req, recipient, display_name
    ),
    "available": lambda settings, req, recipient, reason, display_name: send_available_notification(
        settings, req, recipient, display_name
    ),
    "available_vf": lambda settings, req, recipient, reason, display_name: send_available_vf_notification(
        settings, req, recipient, display_name
    ),
    "available_vo_tracking": lambda settings, req, recipient, reason, display_name: send_available_vo_tracking_notification(
        settings, req, recipient, display_name
    ),
    "vo_only": lambda settings, req, recipient, reason, display_name: send_vo_only_notification(
        settings, req, recipient, display_name, reason
    ),
    "vf_available": lambda settings, req, recipient, reason, display_name: send_vf_available_notification(
        settings, req, recipient, display_name, reason
    ),
    "episode_track": lambda settings, req, recipient, reason, display_name: send_episode_track_notification(
        settings, req, recipient, display_name, reason
    ),
    "partially_available": lambda settings, req, recipient, reason, display_name: send_partially_available_notification(
        settings, req, recipient, reason, display_name
    ),
    "failed": lambda settings, req, recipient, reason, display_name: send_failure_notification(
        settings, req, recipient, reason, display_name
    ),
    "failure": lambda settings, req, recipient, reason, display_name: send_failure_notification(
        settings, req, recipient, reason, display_name
    ),
}


def _event_group(event: str) -> str:
    if event == "request":
        return "request"
    if event in ("failed", "failure"):
        return "failure"
    return "available"


def _push_allowed(settings: Settings, channel: str, event: str) -> bool:
    if not getattr(settings, f"{channel}_enabled", True):
        return False
    return bool(getattr(settings, f"{channel}_send_{_event_group(event)}", True))


def enqueue(event: str, req_id: int, recipients: list[str], reason: str = ""):
    """Empile une notification dans la queue (synchrone, sans await).

    Persiste d'abord la notification en base (`PendingNotification`) pour qu'elle
    survive à un crash/redémarrage entre l'empilement et son traitement par le worker
    (la queue asyncio en mémoire serait sinon vidée silencieusement). La ligne est
    supprimée par `_worker` une fois le traitement terminé (succès ou échec définitif).
    """
    pending_id = None
    db = SessionLocal()
    try:
        row = PendingNotification(event=event, req_id=req_id, recipients=json.dumps(recipients), reason=reason)
        db.add(row)
        db.commit()
        pending_id = row.id
    except Exception as e:
        logger.error(f"Impossible de persister la notification en attente [{event}] req#{req_id}: {e}")
    finally:
        db.close()
    _queue.put_nowait((pending_id, event, req_id, recipients, reason))


def _delete_pending(pending_id: int | None):
    if pending_id is None:
        return
    db = SessionLocal()
    try:
        db.query(PendingNotification).filter(PendingNotification.id == pending_id).delete()
        db.commit()
    except Exception as e:
        logger.error(f"Impossible de supprimer la notification en attente #{pending_id}: {e}")
    finally:
        db.close()


def _load_pending():
    """Recharge dans la queue asyncio les notifications persistées non traitées
    (typiquement après un redémarrage/crash survenu entre `enqueue()` et leur envoi)."""
    db = SessionLocal()
    try:
        rows = db.query(PendingNotification).order_by(PendingNotification.created_at).all()
        for row in rows:
            try:
                recipients = json.loads(row.recipients)
            except Exception:
                recipients = []
            _queue.put_nowait((row.id, row.event, row.req_id, recipients, row.reason or ""))
        if rows:
            logger.info(f"{len(rows)} notification(s) en attente rechargée(s) après redémarrage")
    except Exception as e:
        logger.error(f"Impossible de recharger les notifications en attente: {e}")
    finally:
        db.close()


async def _send_with_retry(
    settings: Settings, req: MediaRequest, event: str, recipient: str, reason: str, display_name: str | None = None
) -> tuple[bool, str | None]:
    """Tente d'envoyer un email avec retry automatique.

    Returns:
        (success, error_msg)
    """
    error_msg = None
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            sender = EMAIL_SENDERS.get(event)
            if sender:
                await sender(settings, req, recipient, reason, display_name)
            logger.info(f"Notification [{event}] envoyée à {recipient} pour '{req.title}' (tentative {attempt + 1})")
            return True, None
        except Exception as e:
            error_msg = str(e)
            if attempt < len(_RETRY_DELAYS):
                logger.warning(
                    f"Notification [{event}] échec tentative {attempt + 1}, retry dans {_RETRY_DELAYS[attempt]}s : {e}"
                )
                await asyncio.sleep(_RETRY_DELAYS[attempt])
            else:
                logger.error(
                    f"Notification [{event}] abandon après {attempt + 1} tentatives pour {recipient} / '{req.title}': {e}"
                )
    return False, error_msg


async def _process(event: str, req_id: int, recipients: list[str], reason: str):
    db = SessionLocal()
    try:
        settings = db.query(Settings).first()
        req = db.query(MediaRequest).filter(MediaRequest.id == req_id).first()
        if not settings or not req:
            return

        # Résolution des emails admin pour marquer is_admin dans les logs
        admin_emails = set(parse_email_list(settings.admin_notification_email))

        # Nom affiché dans le mail : le "Nom d'usage" (custom_name) prime sur
        # request.plex_user, pour être cohérent avec l'aperçu du template.
        user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
        display_name = user_obj.custom_name if user_obj else None

        # Envoi email à chaque destinataire avec retry automatique
        all_ok = True
        for recipient in recipients:
            success, error_msg = await _send_with_retry(settings, req, event, recipient, reason, display_name)
            if not success:
                all_ok = False
            db.add(
                NotificationLog(
                    sent_at=now_utc(),
                    event=event,
                    recipient=recipient,
                    is_admin=recipient in admin_emails,
                    media_title=req.title,
                    media_type=req.media_type,
                    success=success,
                    error_msg=error_msg,
                    req_id=req.id,
                )
            )

        # Mise à jour des flags uniquement si tous les emails ont été envoyés avec succès
        app_metrics.record_notification(all_ok)
        if all_ok:
            for attr in event_mail_flags(event):
                setattr(req, attr, True)
            if event == "partially_available":
                req.last_notified_episode_count = req.episodes_available_count
        db.commit()

        # Push global (Discord + Telegram + ntfy + Gotify configurés dans Settings)
        if _push_allowed(settings, "discord", event):
            await send_discord(settings, req, event)
        if _push_allowed(settings, "telegram", event):
            await send_telegram(settings, req, event)
        if _push_allowed(settings, "ntfy", event):
            await send_ntfy_notif(settings, req, event)
        if _push_allowed(settings, "gotify", event):
            await send_gotify_notif(settings, req, event)

        # Push par utilisateur (webhook Discord / chat_id Telegram individuels)
        if user_obj:
            if user_obj.discord_webhook_url and _push_allowed(settings, "discord", event):
                await send_discord_to_webhook(user_obj.discord_webhook_url, req, event)
            if user_obj.telegram_chat_id and settings.telegram_bot_token and _push_allowed(settings, "telegram", event):
                await send_telegram_to_chat(settings.telegram_bot_token, user_obj.telegram_chat_id, req, event)

    except Exception as e:
        logger.error(f"Notification worker erreur inattendue [{event}] req#{req_id}: {e}")
    finally:
        db.close()


async def _worker():
    logger.info("Notification worker démarré")
    while True:
        try:
            pending_id, event, req_id, recipients, reason = await _queue.get()
            try:
                await _process(event, req_id, recipients, reason)
            finally:
                _delete_pending(pending_id)
        except asyncio.CancelledError:
            logger.info("Notification worker arrêté")
            break
        except Exception as e:
            logger.error(f"Notification worker boucle erreur: {e}")
        finally:
            try:
                _queue.task_done()
            except Exception:
                pass


def start_worker():
    global _worker_task
    _load_pending()
    _worker_task = asyncio.create_task(_worker())
    return _worker_task


def stop_worker():
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
