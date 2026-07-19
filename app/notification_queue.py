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
import inspect
import json
import logging

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from . import metrics as app_metrics
from .database import AsyncSessionLocal
from .job_queue import availability_notification_is_historical, notification_hold_enabled
from .models import MediaRequest, NotificationLog, PendingNotification, PlexUser, Settings
from .services.email_service import (
    send_available_notification,
    send_failure_notification,
    send_import_blocked_notification,
    send_request_notification,
)
from .services.diagnostics import record_event
from .services.notification_catalog import event_mail_flags
from .services.notifications import ChannelNotConfigured
from .services.notifications import (
    send_discord,
    send_discord_to_webhook,
    send_gotify_notif,
    send_ntfy_notif,
    send_telegram,
    send_telegram_to_chat,
)
from .utils import now_utc, now_utc_naive, parse_email_list

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
        batch_summary=context.get("batch_summary", ""),
    )


async def _send_failed(settings, req, recipient, context, display_name):
    context = context if isinstance(context, dict) else {"reason": str(context or "")}
    if context.get("scope") == "import_blocked":
        await send_import_blocked_notification(
            settings, req, recipient, context.get("reason", ""), display_name
        )
        return
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


async def enqueue(
    event: str,
    req_id: int,
    recipients: list[str],
    context: dict | str | None = None,
    triggered_by: str = "auto",
    *,
    db: AsyncSession | None = None,
):
    """Empile et persiste une notification dans la queue.

    `context` porte les données structurées du jalon (scope/language/is_upgrade/
    season_number/episode_number pour "available", reason pour "failed") — remplace
    l'ancien texte libre `reason` reparsé par regex côté email_service.py. Sérialisé en
    JSON dans la colonne `reason` (texte) de `PendingNotification`, pour éviter une
    migration sur cette table de queue éphémère.

    `triggered_by` ("auto" par défaut, "manual" pour un renvoi déclenché depuis la
    fiche détail) est embarqué dans `context` plutôt que d'ajouter une colonne à
    `PendingNotification` — même raison : éviter une migration sur une table éphémère,
    et il survit au rechargement après redémarrage (_load_pending) puisque tout le
    contexte est sérialisé/désérialisé en JSON.

    Persiste d'abord la notification en base (`PendingNotification`) pour qu'elle
    survive à un crash/redémarrage entre l'empilement et son traitement par le worker
    (la queue asyncio en mémoire serait sinon vidée silencieusement). La ligne est
    supprimée par `_worker` une fois le traitement terminé (succès ou échec définitif).
    """
    pending_id = None
    normalized_event = event
    normalized_context: dict = {}
    if db is not None:
        try:
            pending_id, normalized_event, normalized_context = await persist_pending_notification(
                db, event, req_id, recipients, context, triggered_by=triggered_by
            )
            if pending_id is None:
                await db.rollback()
                return None
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        await schedule_pending_notification(
            pending_id, normalized_event, req_id, recipients, normalized_context
        )
        return pending_id

    async with AsyncSessionLocal() as db:
        try:
            pending_id, normalized_event, normalized_context = await persist_pending_notification(
                db, event, req_id, recipients, context, triggered_by=triggered_by
            )
            if pending_id is None:
                return
            await db.commit()
        except Exception as e:
            logger.error(f"Impossible de persister la notification en attente [{event}] req#{req_id}: {e}")
            return

    await schedule_pending_notification(
        pending_id, normalized_event, req_id, recipients, normalized_context
    )
    return pending_id


async def persist_pending_notification(
    db: AsyncSession,
    event: str,
    req_id: int,
    recipients: list[str],
    context: dict | str | None = None,
    *,
    triggered_by: str = "auto",
) -> tuple[int | None, str, dict]:
    """Ajoute une notification à la transaction courante, sans commit ni planification."""
    event, normalized_context = _normalize_event_context(event, context)
    if triggered_by != "auto":
        normalized_context["triggered_by"] = triggered_by
    recipients_json = json.dumps(recipients)
    reason_json = json.dumps(normalized_context)
    existing = (await db.execute(select(PendingNotification).filter(
        PendingNotification.event == event,
        PendingNotification.req_id == req_id,
        PendingNotification.reason == reason_json,
    ))).scalars().first()
    if existing:
        logger.info(
            "Notification [%s] req#%s déjà en attente, ignorée pour éviter un doublon.",
            event, req_id,
        )
        return None, event, normalized_context
    row = PendingNotification(
        event=event, req_id=req_id, recipients=recipients_json, reason=reason_json
    )
    db.add(row)
    flush_result = db.flush()
    if inspect.isawaitable(flush_result):
        await flush_result
    return row.id, event, normalized_context


async def schedule_pending_notification(
    pending_id: int,
    event: str,
    req_id: int,
    recipients: list[str],
    context: dict,
) -> None:
    """Planifie une notification déjà committée."""
    from .job_queue import arq_enabled, enqueue_job

    if arq_enabled():
        try:
            await enqueue_job("job_send_notification", pending_id, job_id=f"notification:{pending_id}")
        except Exception as exc:
            logger.error("Impossible de mettre la notification #%s dans ARQ: %s", pending_id, exc)
            raise
    else:
        _queue.put_nowait((pending_id, event, req_id, recipients, context))


async def _delete_pending(pending_id: int | None):
    if pending_id is None:
        return
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(text("DELETE FROM pending_notifications WHERE id = :id"), {"id": int(pending_id)})
            await db.commit()
        except Exception as e:
            logger.error(f"Impossible de supprimer la notification en attente #{pending_id}: {e}")


async def cancel_pending(ids: list[int]) -> int:
    """Supprime des notifications persistées et annule celles déjà rechargées en mémoire."""
    clean_ids = [int(i) for i in ids if i is not None]
    if not clean_ids:
        return 0
    _cancelled_pending_ids.update(clean_ids)
    async with AsyncSessionLocal() as db:
        try:
            stmt = text("DELETE FROM pending_notifications WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            )
            result = await db.execute(stmt, {"ids": clean_ids})
            await db.commit()
            deleted = result.rowcount
            return int(deleted or 0)
        except Exception as e:
            logger.error(f"Impossible d'annuler les notifications en attente {clean_ids}: {e}")
            await db.rollback()
            return 0


async def cancel_all_pending() -> int:
    """Vide toute la queue persistée et annule les entrées déjà en mémoire."""
    async with AsyncSessionLocal() as db:
        try:
            ids = [row[0] for row in (await db.execute(text("SELECT id FROM pending_notifications"))).fetchall()]
            _cancelled_pending_ids.update(int(i) for i in ids)
            result = await db.execute(text("DELETE FROM pending_notifications"))
            await db.commit()
            deleted = result.rowcount
            return int(deleted or 0)
        except Exception as e:
            logger.error(f"Impossible de purger la queue de notifications: {e}")
            await db.rollback()
            return 0


async def cancel_pending_availability_notifications(request_ids: list[int] | None = None) -> int:
    """Supprime les disponibilités déjà en attente avant un resync silencieux."""
    async with AsyncSessionLocal() as db:
        try:
            if request_ids:
                ids = [row[0] for row in (await db.execute(
                    text(
                        "SELECT id FROM pending_notifications "
                        "WHERE event = 'available' AND req_id IN :request_ids"
                    ).bindparams(bindparam("request_ids", expanding=True)),
                    {"request_ids": [int(i) for i in request_ids]},
                )).fetchall()]
            else:
                ids = [row[0] for row in (await db.execute(
                    text("SELECT id FROM pending_notifications WHERE event = 'available'")
                )).fetchall()]
            _cancelled_pending_ids.update(int(i) for i in ids)
            if not ids:
                return 0
            if request_ids:
                result = await db.execute(
                    text(
                        "DELETE FROM pending_notifications "
                        "WHERE event = 'available' AND req_id IN :request_ids"
                    ).bindparams(bindparam("request_ids", expanding=True)),
                    {"request_ids": [int(i) for i in request_ids]},
                )
            else:
                result = await db.execute(text("DELETE FROM pending_notifications WHERE event = 'available'"))
            await db.commit()
            return int(result.rowcount or 0)
        except Exception as e:
            logger.error("Impossible de purger les disponibilités en attente: %s", e)
            await db.rollback()
            return 0


async def _load_pending():
    """Recharge dans la queue asyncio les notifications persistées non traitées
    (typiquement après un redémarrage/crash survenu entre `enqueue()` et leur envoi).

    Lit les colonnes brutes via SQL plutôt que l'ORM : une seule ligne corrompue
    (ex. `created_at` non parsable en datetime) ferait sinon échouer l'hydratation
    ORM de la requête entière (`.all()`), et avec elle la relecture de TOUTE ligne
    valide présente au même moment — perte silencieuse de vraies notifications en
    attente. Chaque ligne invalide est ignorée individuellement à la place.
    """
    async with AsyncSessionLocal() as db:
        try:
            raw_rows = (await db.execute(
                text("SELECT id, event, req_id, recipients, reason FROM pending_notifications ORDER BY id")
            )).fetchall()
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


async def _send_push_with_retry(coro_factory) -> tuple[bool | None, str | None]:
    """Tente un envoi push (Discord/Telegram/ntfy/Gotify) avec le même retry que l'email.

    Returns:
        (success, error_msg). success=None si le canal n'est pas configuré (ChannelNotConfigured)
        — rien à journaliser ni retenter dans ce cas, contrairement à un échec réel.
    """
    error_msg = None
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            await coro_factory()
            return True, None
        except ChannelNotConfigured:
            return None, None
        except Exception as e:
            error_msg = str(e)
            if attempt < len(_RETRY_DELAYS):
                await asyncio.sleep(_RETRY_DELAYS[attempt])
    return False, error_msg


class NotificationDeliveryError(Exception):
    """Levée quand au moins un destinataire n'a pas pu être livré après retries.

    Signale à l'appelant (ARQ ou worker asyncio) de NE PAS supprimer la
    PendingNotification persistée, pour qu'elle survive à un redémarrage/à un
    nouveau job ARQ plutôt que d'être perdue silencieusement (voir
    process_pending_id / _worker).
    """


async def _process(
    event: str, req_id: int, recipients: list[str], context: dict, *, force: bool = False
) -> bool:
    """Traite une notification en attente.

    Returns:
        True si tout a été livré (ou s'il n'y avait rien à faire — settings/req
        introuvables, aucun destinataire) : la PendingNotification peut être
        supprimée. False si au moins un destinataire n'a pas pu être livré après
        les retries internes (_send_with_retry) : la ligne doit être conservée
        pour une reprise ultérieure plutôt que perdue.
    """
    event, context = _normalize_event_context(event, context)
    triggered_by = context.get("triggered_by") or "auto"
    async with AsyncSessionLocal() as db:
        try:
            settings = (await db.execute(select(Settings))).scalars().first()
            req = (await db.execute(select(MediaRequest).filter(MediaRequest.id == req_id))).scalars().first()
            if not settings or not req:
                return True
            if (
                event == "available"
                and not context.get("allow_during_resync")
                and await availability_notification_is_historical(req.id)
            ):
                logger.info("Notification historique ignorée pendant le resync pour '%s'", req.title)
                return True
            if not force and await notification_hold_enabled():
                return False

            # Résolution des emails admin pour marquer is_admin dans les logs
            admin_emails = set(parse_email_list(settings.admin_notification_email))

            # Nom affiché dans le mail : le "Nom d'usage" (custom_name) prime sur
            # request.plex_user, pour être cohérent avec l'aperçu du template.
            user_obj = (await db.execute(select(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id))).scalars().first()
            display_name = user_obj.custom_name if user_obj else None

            # Envoi email à chaque destinataire avec retry automatique
            all_ok = True
            for recipient in recipients:
                success, error_msg = await _send_with_retry(settings, req, event, recipient, context, display_name)
                if not success:
                    all_ok = False
                db.add(
                    NotificationLog(
                        sent_at=now_utc_naive(),
                        event=event,
                        channel="email",
                        recipient=recipient,
                        is_admin=recipient in admin_emails,
                        media_title=req.title,
                        media_type=req.media_type,
                        success=success,
                        error_msg=error_msg,
                        req_id=req.id,
                        triggered_by=triggered_by,
                        scope=context.get("scope"),
                        language=context.get("language"),
                        is_upgrade=bool(context.get("is_upgrade")),
                        season_number=context.get("season_number"),
                        episode_number=context.get("episode_number"),
                    )
                )

            # Mise à jour des flags uniquement si tous les emails ont été envoyés avec succès
            app_metrics.record_notification(all_ok)
            await record_event(
                db,
                category="notification",
                action="sent" if all_ok else "failed",
                status="success" if all_ok else "error",
                request=req,
                message=f"Notification {event} traitée.",
                details={"event": event, "channel": "email", "recipients": recipients, "success": all_ok},
            )
            if all_ok and not context.get("admin_only"):
                for attr in event_mail_flags(event):
                    setattr(req, attr, True)
                if event == "available" and context.get("scope") == "episode" and req.episodes_available_count is not None:
                    req.last_notified_episode_count = req.episodes_available_count
            await db.commit()

            # Push (Discord/Telegram global + par utilisateur, ntfy, Gotify) : retry +
            # journalisation au même titre que l'email (voir _send_push_with_retry). Ne
            # participe PAS à `all_ok`/à la survie de la PendingNotification pour retry ARQ :
            # cette fonction n'a pas de garde-fou "déjà envoyé" pour l'email comme _notify()
            # en a un côté appelant — un retry ARQ du job entier renverrait le même email une
            # deuxième fois si un push échoue après que l'email a déjà réussi.
            push_targets: list[tuple[str, str, object]] = []
            suppress_push = bool(context.get("admin_only"))
            if not suppress_push and _push_allowed(settings, "discord", event):
                push_targets.append(("discord", "discord (global)", lambda: send_discord(settings, req, event, context)))
            if not suppress_push and _push_allowed(settings, "telegram", event):
                push_targets.append(("telegram", "telegram (global)", lambda: send_telegram(settings, req, event, context)))
            if not suppress_push and _push_allowed(settings, "ntfy", event):
                push_targets.append(("ntfy", "ntfy", lambda: send_ntfy_notif(settings, req, event, context)))
            if not suppress_push and _push_allowed(settings, "gotify", event):
                push_targets.append(("gotify", "gotify", lambda: send_gotify_notif(settings, req, event, context)))
            if user_obj and not suppress_push:
                if user_obj.discord_webhook_url and _push_allowed(settings, "discord", event):
                    webhook_url = user_obj.discord_webhook_url
                    push_targets.append((
                        "discord", f"discord (utilisateur {req.plex_user_id})",
                        lambda: send_discord_to_webhook(webhook_url, req, event, context),
                    ))
                if user_obj.telegram_chat_id and settings.telegram_bot_token and _push_allowed(settings, "telegram", event):
                    bot_token, chat_id = settings.telegram_bot_token, user_obj.telegram_chat_id
                    push_targets.append((
                        "telegram", f"telegram (utilisateur {req.plex_user_id})",
                        lambda: send_telegram_to_chat(bot_token, chat_id, req, event, context),
                    ))

            for channel, recipient_label, coro_factory in push_targets:
                success, error_msg = await _send_push_with_retry(coro_factory)
                if success is None:
                    continue  # canal non configuré : pas d'entrée dans le journal
                db.add(
                    NotificationLog(
                        sent_at=now_utc_naive(),
                        event=event,
                        channel=channel,
                        recipient=recipient_label,
                        is_admin=False,
                        media_title=req.title,
                        media_type=req.media_type,
                        success=success,
                        error_msg=error_msg,
                        req_id=req.id,
                        triggered_by=triggered_by,
                        scope=context.get("scope"),
                        language=context.get("language"),
                        is_upgrade=bool(context.get("is_upgrade")),
                        season_number=context.get("season_number"),
                        episode_number=context.get("episode_number"),
                    )
                )
            if push_targets:
                await db.commit()

            return all_ok
        except Exception as e:
            logger.error(f"Notification worker erreur inattendue [{event}] req#{req_id}: {e}")
            return False


async def process_pending_id(pending_id: int, force: bool = False) -> str | int | None:
    """Process one persisted notification from ARQ and return its target user id.

    Ne supprime la PendingNotification que si la livraison a réussi. En cas
    d'échec, la ligne est conservée et une NotificationDeliveryError est levée :
    ARQ retente le job (WorkerSettings.max_tries=3, avec son propre backoff) ;
    si toutes les tentatives ARQ échouent, la ligne reste en base et sera
    récupérée au prochain démarrage du worker (voir jobs.py::startup, qui
    réenfile toute PendingNotification restante) plutôt que perdue en silence.
    """
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "SELECT event, req_id, recipients, reason FROM pending_notifications "
                    "WHERE id = :id"
                ),
                {"id": int(pending_id)},
            )
        ).first()
        if not row:
            return None
        event, req_id, recipients_raw, reason_raw = row
        recipients = json.loads(recipients_raw) if recipients_raw else []
        context = json.loads(reason_raw) if reason_raw else {}
        req = (await db.execute(select(MediaRequest).filter(MediaRequest.id == int(req_id)))).scalars().first()
        user_id = req.plex_user_id if req else None

    if not force and await notification_hold_enabled():
        return user_id
    ok = await _process(event, int(req_id), recipients, context, force=force)
    if not ok:
        raise NotificationDeliveryError(f"Notification #{pending_id} [{event}] non livrée à tous les destinataires")
    await _delete_pending(pending_id)
    return user_id


async def _worker():
    logger.info("Notification worker démarré")
    while True:
        try:
            pending_id, event, req_id, recipients, context = await _queue.get()
            if pending_id in _cancelled_pending_ids:
                logger.info(f"Notification en attente #{pending_id} annulée avant envoi")
                _cancelled_pending_ids.discard(pending_id)
                await _delete_pending(pending_id)
            else:
                ok = await _process(event, req_id, recipients, context)
                if ok:
                    await _delete_pending(pending_id)
                else:
                    # Conservée en base plutôt que perdue : ce worker en mémoire ne la
                    # retentera pas lui-même dans ce cycle de vie du process, mais
                    # _load_pending() la réenfilera au prochain démarrage de l'app —
                    # cohérent avec la garantie de survie déjà documentée sur ce modèle.
                    logger.warning(f"Notification #{pending_id} [{event}] non livrée, conservée pour reprise ultérieure")
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


async def start_worker():
    global _worker_task
    await _load_pending()
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
