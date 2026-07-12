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

from sqlalchemy import bindparam, text

from . import metrics as app_metrics
from .database import SessionLocal
from .models import MediaRequest, NotificationLog, PendingNotification, PlexUser, Settings
from .services.email_service import send_available_notification, send_failure_notification, send_request_notification
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
_cancelled_pending_ids: set[int] = set()

_RETRY_DELAYS = [2, 5]  # secondes entre chaque tentative


async def _send_request(settings, req, recipient, context, display_name):
    await send_request_notification(settings, req, recipient, display_name)


async def _send_available(settings, req, recipient, context, display_name):
    context = context if isinstance(context, dict) else {}
    await send_available_notification(
        settings,
        req,
        recipient,
        display_name,
        scope=context.get("scope", "movie"),
        language=context.get("language"),
        is_upgrade=bool(context.get("is_upgrade")),
        season_number=context.get("season_number"),
        episode_number=context.get("episode_number"),
    )


async def _send_failed(settings, req, recipient, context, display_name):
    context = context if isinstance(context, dict) else {"reason": str(context or "")}
    await send_failure_notification(settings, req, recipient, context.get("reason", ""), display_name)


# Catalogue réduit à 3 évènements réels (voir notification_catalog.py) : toutes les
# variantes de disponibilité passent par "available" avec un contexte structuré
# (scope/language/is_upgrade/season/episode), plutôt qu'une fonction d'envoi dédiée.
EMAIL_SENDERS = {
    "request": _send_request,
    "available": _send_available,
    "failed": _send_failed,
}


def _normalize_event_context(event: str, context: dict | str | None) -> tuple[str, dict]:
    if isinstance(context, dict):
        normalized_context = dict(context)
    else:
        normalized_context = {"reason": context} if context else {}
    if event == "failure":
        return "failed", normalized_context
    return event, normalized_context


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


def enqueue(event: str, req_id: int, recipients: list[str], context: dict | str | None = None):
    """Empile une notification dans la queue (synchrone, sans await).

    `context` porte les données structurées du jalon (scope/language/is_upgrade/
    season_number/episode_number pour "available", reason pour "failed") — remplace
    l'ancien texte libre `reason` reparsé par regex côté email_service.py. Sérialisé en
    JSON dans la colonne `reason` (texte) de `PendingNotification`, pour éviter une
    migration sur cette table de queue éphémère.

    Persiste d'abord la notification en base (`PendingNotification`) pour qu'elle
    survive à un crash/redémarrage entre l'empilement et son traitement par le worker
    (la queue asyncio en mémoire serait sinon vidée silencieusement). La ligne est
    supprimée par `_worker` une fois le traitement terminé (succès ou échec définitif).
    """
    event, context = _normalize_event_context(event, context)
    pending_id = None
    db = SessionLocal()
    try:
        recipients_json = json.dumps(recipients)
        reason_json = json.dumps(context)
        
        existing = db.query(PendingNotification).filter(
            PendingNotification.event == event,
            PendingNotification.req_id == req_id,
            PendingNotification.reason == reason_json
        ).first()
        
        if existing:
            logger.info(f"Notification [{event}] req#{req_id} déjà en attente, ignorée pour éviter un doublon.")
            return

        row = PendingNotification(
            event=event, req_id=req_id, recipients=recipients_json, reason=reason_json
        )
        db.add(row)
        db.commit()
        pending_id = row.id
    except Exception as e:
        logger.error(f"Impossible de persister la notification en attente [{event}] req#{req_id}: {e}")
        return
    finally:
        db.close()
        
    if pending_id is not None:
        _queue.put_nowait((pending_id, event, req_id, recipients, context))


def _delete_pending(pending_id: int | None):
    if pending_id is None:
        return
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM pending_notifications WHERE id = :id"), {"id": int(pending_id)})
        db.commit()
    except Exception as e:
        logger.error(f"Impossible de supprimer la notification en attente #{pending_id}: {e}")
    finally:
        db.close()


def cancel_pending(ids: list[int]) -> int:
    """Supprime des notifications persistées et annule celles déjà rechargées en mémoire."""
    clean_ids = [int(i) for i in ids if i is not None]
    if not clean_ids:
        return 0
    _cancelled_pending_ids.update(clean_ids)
    db = SessionLocal()
    try:
        stmt = text("DELETE FROM pending_notifications WHERE id IN :ids").bindparams(
            bindparam("ids", expanding=True)
        )
        result = db.execute(stmt, {"ids": clean_ids})
        db.commit()
        deleted = result.rowcount
        return int(deleted or 0)
    except Exception as e:
        logger.error(f"Impossible d'annuler les notifications en attente {clean_ids}: {e}")
        db.rollback()
        return 0
    finally:
        db.close()


def cancel_all_pending() -> int:
    """Vide toute la queue persistée et annule les entrées déjà en mémoire."""
    db = SessionLocal()
    try:
        ids = [row[0] for row in db.execute(text("SELECT id FROM pending_notifications")).fetchall()]
        _cancelled_pending_ids.update(int(i) for i in ids)
        result = db.execute(text("DELETE FROM pending_notifications"))
        db.commit()
        deleted = result.rowcount
        return int(deleted or 0)
    except Exception as e:
        logger.error(f"Impossible de purger la queue de notifications: {e}")
        db.rollback()
        return 0
    finally:
        db.close()


def _load_pending():
    """Recharge dans la queue asyncio les notifications persistées non traitées
    (typiquement après un redémarrage/crash survenu entre `enqueue()` et leur envoi).

    Lit les colonnes brutes via SQL plutôt que l'ORM : une seule ligne corrompue
    (ex. `created_at` non parsable en datetime) ferait sinon échouer l'hydratation
    ORM de la requête entière (`.all()`), et avec elle la relecture de TOUTE ligne
    valide présente au même moment — perte silencieuse de vraies notifications en
    attente. Chaque ligne invalide est ignorée individuellement à la place.
    """
    db = SessionLocal()
    try:
        raw_rows = db.execute(
            text("SELECT id, event, req_id, recipients, reason FROM pending_notifications ORDER BY id")
        ).fetchall()
        loaded = 0
        skipped = 0
        for row_id, event, req_id, recipients_raw, reason_raw in raw_rows:
            if event not in EMAIL_SENDERS:
                skipped += 1
                continue
            try:
                req_id = int(req_id)
            except (TypeError, ValueError):
                skipped += 1
                continue
            try:
                recipients = json.loads(recipients_raw)
                if not isinstance(recipients, list):
                    recipients = []
            except Exception:
                recipients = []
            try:
                context = json.loads(reason_raw) if reason_raw else {}
                if not isinstance(context, dict):
                    context = {}
            except Exception:
                context = {}
            _queue.put_nowait((row_id, event, req_id, recipients, context))
            loaded += 1
        if loaded:
            logger.info(f"{loaded} notification(s) en attente rechargée(s) après redémarrage")
        if skipped:
            logger.warning(f"{skipped} ligne(s) invalide(s) ignorée(s) dans pending_notifications au rechargement")
    except Exception as e:
        logger.error(f"Impossible de recharger les notifications en attente: {e}")
    finally:
        db.close()


async def _send_with_retry(
    settings: Settings, req: MediaRequest, event: str, recipient: str, context: dict, display_name: str | None = None
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
                await sender(settings, req, recipient, context, display_name)
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


async def _process(event: str, req_id: int, recipients: list[str], context: dict):
    event, context = _normalize_event_context(event, context)
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
            success, error_msg = await _send_with_retry(settings, req, event, recipient, context, display_name)
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
                    scope=context.get("scope"),
                    language=context.get("language"),
                    is_upgrade=bool(context.get("is_upgrade")),
                    season_number=context.get("season_number"),
                    episode_number=context.get("episode_number"),
                )
            )

        # Mise à jour des flags uniquement si tous les emails ont été envoyés avec succès
        app_metrics.record_notification(all_ok)
        if all_ok:
            for attr in event_mail_flags(event):
                setattr(req, attr, True)
            if event == "available" and context.get("scope") == "episode" and req.episodes_available_count is not None:
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
            pending_id, event, req_id, recipients, context = await _queue.get()
            try:
                if pending_id in _cancelled_pending_ids:
                    logger.info(f"Notification en attente #{pending_id} annulée avant envoi")
                    _cancelled_pending_ids.discard(pending_id)
                else:
                    await _process(event, req_id, recipients, context)
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


async def stop_worker():
    """Annule le worker et attend sa sortie (bornée) avant de rendre la main.

    Sans ce await, `lifespan` (main.py) rendait la main à uvicorn immédiatement
    après `.cancel()`, sans savoir si le worker était en plein milieu d'un
    `db.commit()` (traitement d'une notification) au moment de l'arrêt — un
    process tué (SIGKILL, timeout d'arrêt Docker dépassé) pendant une écriture
    SQLite en cours est un facteur de corruption. Le timeout court reste un
    filet de sécurité : mieux vaut couper après 5 s qu'empêcher tout arrêt.
    """
    if not _worker_task or _worker_task.done():
        return
    _worker_task.cancel()
    try:
        await asyncio.wait_for(_worker_task, timeout=5)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
