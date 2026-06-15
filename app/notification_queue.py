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
import logging
from datetime import datetime, timezone

from . import metrics as app_metrics
from .database import SessionLocal
from .models import MediaRequest, NotificationLog, PlexUser, Settings
from .services.email_service import (
    send_available_notification,
    send_failure_notification,
    send_request_notification,
)
from .services.notifications import (
    send_discord,
    send_discord_to_webhook,
    send_telegram,
    send_telegram_to_chat,
)
from .utils import parse_email_list

logger = logging.getLogger(__name__)

_queue: asyncio.Queue = asyncio.Queue()
_worker_task: asyncio.Task | None = None

_RETRY_DELAYS = [2, 5]  # secondes entre chaque tentative


def enqueue(event: str, req_id: int, recipients: list[str], reason: str = ""):
    """Empile une notification dans la queue (synchrone, sans await)."""
    _queue.put_nowait((event, req_id, recipients, reason))


async def _send_with_retry(
    settings: Settings, req: MediaRequest, event: str, recipient: str, reason: str
) -> tuple[bool, str | None]:
    """Tente d'envoyer un email avec retry automatique.

    Returns:
        (success, error_msg)
    """
    error_msg = None
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            if event == "request":
                await send_request_notification(settings, req, recipient)
            elif event == "available":
                await send_available_notification(settings, req, recipient)
            elif event == "failed":
                await send_failure_notification(settings, req, recipient, reason)
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

        # Envoi email à chaque destinataire avec retry automatique
        all_ok = True
        for recipient in recipients:
            success, error_msg = await _send_with_retry(settings, req, event, recipient, reason)
            if not success:
                all_ok = False
            db.add(
                NotificationLog(
                    sent_at=datetime.now(timezone.utc),
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
            if event == "request":
                req.request_mail_sent = True
            elif event == "available":
                req.available_mail_sent = True
        db.commit()

        # Push global (Discord + Telegram configurés dans Settings)
        await send_discord(settings, req, event)
        await send_telegram(settings, req, event)

        # Push par utilisateur (webhook Discord / chat_id Telegram individuels)
        user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
        if user_obj:
            if user_obj.discord_webhook_url:
                await send_discord_to_webhook(user_obj.discord_webhook_url, req, event)
            if user_obj.telegram_chat_id and settings.telegram_bot_token:
                await send_telegram_to_chat(settings.telegram_bot_token, user_obj.telegram_chat_id, req, event)

    except Exception as e:
        logger.error(f"Notification worker erreur inattendue [{event}] req#{req_id}: {e}")
    finally:
        db.close()


async def _worker():
    logger.info("Notification worker démarré")
    while True:
        try:
            event, req_id, recipients, reason = await _queue.get()
            await _process(event, req_id, recipients, reason)
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
    _worker_task = asyncio.create_task(_worker())
    return _worker_task


def stop_worker():
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
