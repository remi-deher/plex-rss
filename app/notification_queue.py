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

from . import metrics as app_metrics
from .database import SessionLocal
from .models import MediaRequest, Settings
from .services.email_service import (
    send_available_notification,
    send_failure_notification,
    send_request_notification,
)
from .services.notifications import send_discord, send_telegram

logger = logging.getLogger(__name__)

_queue: asyncio.Queue = asyncio.Queue()
_worker_task: asyncio.Task | None = None


def enqueue(event: str, req_id: int, recipients: list[str], reason: str = ""):
    """Empile une notification dans la queue (synchrone, sans await)."""
    _queue.put_nowait((event, req_id, recipients, reason))


async def _process(event: str, req_id: int, recipients: list[str], reason: str):
    db = SessionLocal()
    try:
        settings = db.query(Settings).first()
        req = db.query(MediaRequest).filter(MediaRequest.id == req_id).first()
        if not settings or not req:
            return

        # Envoi email à chaque destinataire séparément
        all_ok = True
        for recipient in recipients:
            try:
                if event == "request":
                    await send_request_notification(settings, req, recipient)
                elif event == "available":
                    await send_available_notification(settings, req, recipient)
                elif event == "failed":
                    await send_failure_notification(settings, req, recipient, reason)
                logger.info(f"Notification email [{event}] envoyée à {recipient} pour '{req.title}'")
            except Exception as e:
                all_ok = False
                logger.error(f"Notification email [{event}] échouée pour {recipient} / '{req.title}': {e}")

        # Mise à jour des flags uniquement si tous les emails ont été envoyés avec succès
        app_metrics.record_notification(all_ok)
        if all_ok:
            if event == "request":
                req.request_mail_sent = True
            elif event == "available":
                req.available_mail_sent = True
            db.commit()

        # Push Discord + Telegram (indépendants de l'email)
        await send_discord(settings, req, event)
        await send_telegram(settings, req, event)

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
