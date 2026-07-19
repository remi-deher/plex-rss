"""Observation durable, chaque minute, de la file Sonarr.

Cette etape ne declenche aucune notification. Elle fournit la source de verite qui
permettra ensuite de regrouper les changements VO/VF par vague d'acquisition.
"""

import json
import logging
from dataclasses import dataclass

from sqlalchemy import select

from ..database import AsyncSessionLocal
from ..models import ArrInstance, MediaRequest, SeriesAcquisitionBatch, Settings, SonarrQueueObservation
from ..utils import now_utc_naive
from . import sonarr

logger = logging.getLogger(__name__)

BLOCKED_CONFIRMATION_CHECKS = 2
FULL_PROGRESS = 99.9
OPEN_BATCH_STATES = ("open", "stabilizing")
ALL_SEASONS_SOURCES = {"api", "rss"}


@dataclass(frozen=True)
class QueueClassification:
    state: str
    blocked_candidate: bool = False


def classify_queue_record(record: dict) -> QueueClassification:
    """Classe un element sans confondre import lent et blocage confirme."""
    progress = float(record.get("progress") or 0)
    size = float(record.get("size") or 0)
    sizeleft = float(record.get("sizeleft") or 0)
    complete = progress >= FULL_PROGRESS or (size > 0 and sizeleft <= 0)
    status = str(record.get("status") or "").strip().lower()
    tracked_state = str(record.get("tracked_state") or "").strip().lower()
    tracked_status = str(record.get("tracked_status") or "").strip().lower()
    has_diagnostic = bool(
        record.get("error")
        or record.get("status_messages")
        or tracked_status in {"warning", "error", "failed"}
    )

    if not complete:
        return QueueClassification("downloading" if status == "downloading" else "queued")
    if tracked_state == "importing":
        return QueueClassification("importing")
    if tracked_state in {"imported", "completed"}:
        return QueueClassification("completed")
    if tracked_state == "importpending" or has_diagnostic:
        return QueueClassification("awaiting_import", blocked_candidate=True)
    return QueueClassification("awaiting_import")


def _expected_scope(source: str | None) -> str:
    return "all_seasons" if (source or "").strip().lower() in ALL_SEASONS_SOURCES else "monitored_seasons"


def _expected_seasons(record: dict, scope: str) -> list[int]:
    seasons = record.get("series_seasons") or []
    return sorted({
        int(season["season_number"])
        for season in seasons
        if season.get("season_number") not in (None, 0)
        and (scope == "all_seasons" or season.get("monitored") is True)
    })


async def _open_batch(db, instance: ArrInstance, req: MediaRequest | None, arr_media_id: int):
    batch = (
        await db.execute(
            select(SeriesAcquisitionBatch).filter(
                SeriesAcquisitionBatch.arr_instance_id == instance.id,
                SeriesAcquisitionBatch.arr_id == arr_media_id,
                SeriesAcquisitionBatch.status.in_(OPEN_BATCH_STATES),
            )
        )
    ).scalars().first()
    if batch:
        return batch
    batch = SeriesAcquisitionBatch(
        request_id=req.id if req else None,
        arr_instance_id=instance.id,
        arr_id=arr_media_id,
        source=req.source if req else "arr_sync",
        expected_scope=_expected_scope(req.source if req else None),
        status="open",
    )
    db.add(batch)
    await db.flush()
    return batch


async def monitor_sonarr_queue() -> dict[str, int]:
    """Controle les instances Sonarr et confirme un blocage au second passage."""
    now = now_utc_naive()
    counters = {"instances": 0, "observed": 0, "blocked": 0, "resolved": 0}
    async with AsyncSessionLocal() as db:
        instances = (
            await db.execute(
                select(ArrInstance).filter(ArrInstance.enabled, ArrInstance.arr_type == "sonarr")
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

        for instance in instances:
            # Une panne Sonarr ne doit jamais ressembler a une file vide et resoudre
            # artificiellement tous les incidents connus.
            try:
                records = await sonarr.get_queue(instance.url, instance.api_key, raise_on_error=True)
            except Exception as exc:
                logger.warning("Surveillance queue Sonarr '%s' ignoree: %s", instance.name, exc)
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
                batch = await _open_batch(db, instance, req, arr_media_id)
                expected_seasons = _expected_seasons(record, batch.expected_scope)
                if expected_seasons:
                    batch.expected_seasons = json.dumps(expected_seasons)

                observation = (
                    await db.execute(
                        select(SonarrQueueObservation).filter(
                            SonarrQueueObservation.arr_instance_id == instance.id,
                            SonarrQueueObservation.queue_id == queue_id,
                        )
                    )
                ).scalars().first()
                if observation is None:
                    observation = SonarrQueueObservation(
                        batch_id=batch.id,
                        request_id=req.id if req else None,
                        arr_instance_id=instance.id,
                        queue_id=queue_id,
                    )
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
                if state in {"queued", "downloading", "importing", "awaiting_import"}:
                    batch.status = "open"
                    batch.last_sonarr_activity_at = now
                    batch.stabilization_started_at = None
                observation.batch_id = batch.id
                observation.request_id = req.id if req else None
                observation.download_id = record.get("download_id")
                observation.arr_media_id = arr_media_id
                observation.season_number = record.get("season_number")
                observation.episode_number = record.get("episode_number")
                observation.title = record.get("title")
                observation.state = state
                observation.progress = float(record.get("progress") or 0)
                observation.tracked_state = record.get("tracked_state")
                observation.tracked_status = record.get("tracked_status")
                observation.error_message = record.get("error")
                observation.status_messages = json.dumps(record.get("status_messages") or [], ensure_ascii=False)
                observation.consecutive_blocked_checks = blocked_checks
                observation.last_seen_at = now
                observation.resolved_at = None
                if state == "import_blocked":
                    observation.blocked_at = observation.blocked_at or now
                    counters["blocked"] += 1
                else:
                    observation.blocked_at = None
                counters["observed"] += 1

            unresolved = (
                await db.execute(
                    select(SonarrQueueObservation).filter(
                        SonarrQueueObservation.arr_instance_id == instance.id,
                        SonarrQueueObservation.resolved_at.is_(None),
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

        settings = (await db.execute(select(Settings))).scalars().first()
        from .acquisition_batches import advance_acquisition_batches

        batch_counters = await advance_acquisition_batches(db, settings, now=now)
        await db.commit()
        counters.update(batch_counters)
    return counters
