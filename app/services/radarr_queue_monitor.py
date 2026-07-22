"""Observation durable, chaque minute, de la file Radarr -- detecte les imports bloques.

Contrairement a Sonarr (regroupe par vague d'episodes via SeriesAcquisitionBatch/
sonarr_queue_monitor.py), un film Radarr est un item unique : pas de notion de vague
ni de stabilisation. L'alerte admin "import bloque" part directement d'ici des qu'un
item est confirme bloque deux verifications de suite -- meme evenement de notification
que cote Sonarr (voir notification_catalog.EVENTS["import_blocked"]), meme bascule
d'activation (Settings.notify_import_blocked).
"""

import logging

from sqlalchemy import select

from ..database import AsyncSessionLocal
from ..models import ArrInstance, MediaRequest, RadarrQueueObservation, Settings
from ..notification_queue import enqueue
from ..utils import now_utc_naive, parse_email_list
from . import radarr
from .sonarr_queue_monitor import BLOCKED_CONFIRMATION_CHECKS, classify_queue_record

logger = logging.getLogger(__name__)


async def monitor_radarr_queue() -> dict[str, int]:
    """Controle les instances Radarr et alerte l'admin sur un blocage confirme."""
    now = now_utc_naive()
    counters = {"instances": 0, "observed": 0, "blocked": 0, "resolved": 0, "admin_alerts": 0}
    async with AsyncSessionLocal() as db:
        instances = (
            await db.execute(
                select(ArrInstance).filter(ArrInstance.enabled, ArrInstance.arr_type == "radarr")
            )
        ).scalars().all()
        requests = (
            await db.execute(
                select(MediaRequest).filter(
                    MediaRequest.arr_instance_id.isnot(None), MediaRequest.arr_id.isnot(None)
                )
            )
        ).scalars().all()
        request_by_key = {(req.arr_instance_id, req.arr_id): req for req in requests}
        settings = (await db.execute(select(Settings))).scalars().first()
        alerts_enabled = bool(
            settings and settings.admin_notification_email and settings.notify_import_blocked
        )
        admin_recipients = parse_email_list(settings.admin_notification_email) if settings else []

        for instance in instances:
            # Une panne Radarr ne doit jamais ressembler a une file vide et resoudre
            # artificiellement tous les incidents connus.
            try:
                records = await radarr.get_queue(instance.url, instance.api_key, raise_on_error=True)
            except Exception as exc:
                logger.warning("Surveillance queue Radarr '%s' ignoree: %s", instance.name, exc)
                continue
            counters["instances"] += 1
            seen_queue_ids: set[int] = set()

            for record in records:
                queue_id = record.get("queue_id")
                arr_media_id = record.get("arr_media_id")
                if queue_id is None or arr_media_id is None:
                    continue
                queue_id = int(queue_id)
                arr_media_id = int(arr_media_id)
                seen_queue_ids.add(queue_id)
                req = request_by_key.get((instance.id, arr_media_id))

                observation = (
                    await db.execute(
                        select(RadarrQueueObservation).filter(
                            RadarrQueueObservation.arr_instance_id == instance.id,
                            RadarrQueueObservation.queue_id == queue_id,
                        )
                    )
                ).scalars().first()
                if observation is None:
                    observation = RadarrQueueObservation(arr_instance_id=instance.id, queue_id=queue_id)
                    db.add(observation)

                classification = classify_queue_record(record)
                blocked_checks = (
                    (observation.consecutive_blocked_checks or 0) + 1
                    if classification.blocked_candidate
                    else 0
                )
                state = (
                    "import_blocked"
                    if classification.blocked_candidate and blocked_checks >= BLOCKED_CONFIRMATION_CHECKS
                    else classification.state
                )
                observation.request_id = req.id if req else None
                observation.arr_media_id = arr_media_id
                observation.title = record.get("title")
                observation.state = state
                observation.progress = float(record.get("progress") or 0)
                observation.tracked_state = record.get("tracked_state")
                observation.tracked_status = record.get("tracked_status")
                observation.error_message = record.get("error")
                observation.consecutive_blocked_checks = blocked_checks
                observation.last_seen_at = now
                observation.resolved_at = None

                if state == "import_blocked":
                    observation.blocked_at = observation.blocked_at or now
                    counters["blocked"] += 1
                    if alerts_enabled and not observation.admin_alert_queued_at and req:
                        reason = observation.error_message or "Import Radarr bloque : verification manuelle requise."
                        await enqueue(
                            "import_blocked",
                            req.id,
                            admin_recipients,
                            {
                                "reason": f"{reason} ({observation.title or 'element Radarr'})",
                                "admin_only": True,
                            },
                            db=db,
                        )
                        observation.admin_alert_queued_at = now
                        counters["admin_alerts"] += 1
                else:
                    observation.blocked_at = None
                counters["observed"] += 1

            unresolved = (
                await db.execute(
                    select(RadarrQueueObservation).filter(
                        RadarrQueueObservation.arr_instance_id == instance.id,
                        RadarrQueueObservation.resolved_at.is_(None),
                    )
                )
            ).scalars().all()
            for observation in unresolved:
                if observation.queue_id in seen_queue_ids:
                    continue
                observation.state = "resolved"
                observation.resolved_at = now
                observation.consecutive_blocked_checks = 0
                counters["resolved"] += 1

        await db.commit()
    return counters
