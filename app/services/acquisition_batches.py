"""Accumulation et cloture des vagues d'acquisition de series."""

import json
from datetime import timedelta

from sqlalchemy import select

from ..models import (
    MediaRequest,
    SeriesAcquisitionBatch,
    Settings,
    SonarrQueueObservation,
)
from ..notification_queue import enqueue
from ..utils import now_utc_naive, parse_email_list

STABILIZATION_DELAY = timedelta(minutes=5)
MAX_BATCH_DELAY = timedelta(minutes=60)
OPEN_BATCH_STATES = ("open", "stabilizing")
ACTIVE_QUEUE_STATES = ("queued", "downloading", "importing", "awaiting_import")


def _event_dict(candidate) -> dict:
    return {
        "scope": candidate.scope,
        "language": candidate.language,
        "is_upgrade": bool(candidate.is_upgrade),
        "season_number": candidate.season_number,
        "episode_number": candidate.episode_number,
    }


def _event_key(event: dict) -> tuple:
    return (
        event.get("scope"),
        event.get("language"),
        bool(event.get("is_upgrade")),
        event.get("season_number"),
        event.get("episode_number"),
    )


async def accumulate_batch_candidates(db, req: MediaRequest, candidates: list) -> bool:
    """Ajoute des jalons a un lot ouvert et reporte seulement leur livraison."""
    if not req.arr_instance_id or not req.arr_id:
        return False
    batch = (
        await db.execute(
            select(SeriesAcquisitionBatch).filter(
                SeriesAcquisitionBatch.request_id == req.id,
                SeriesAcquisitionBatch.arr_instance_id == req.arr_instance_id,
                SeriesAcquisitionBatch.arr_id == req.arr_id,
                SeriesAcquisitionBatch.status.in_(OPEN_BATCH_STATES),
            )
        )
    ).scalars().first()
    if not batch:
        return False
    try:
        events = json.loads(batch.pending_events or "[]")
    except (TypeError, ValueError):
        events = []
    known = {_event_key(event) for event in events}
    changed = False
    for candidate in candidates:
        event = _event_dict(candidate)
        if _event_key(event) not in known:
            events.append(event)
            known.add(_event_key(event))
            changed = True
    if not changed:
        return True
    now = now_utc_naive()
    batch.pending_events = json.dumps(events, ensure_ascii=False)
    batch.last_plex_change_at = now
    if batch.status == "stabilizing":
        batch.stabilization_started_at = now
    await db.commit()
    await db.refresh(req)
    return True


def build_batch_summary(
    events: list[dict], blocked_count: int, expected_seasons: list[int] | None = None
) -> str:
    """Produit une phrase courte couvrant VO, VF, partiel et imports bloques."""
    vf_seasons = {e.get("season_number") for e in events if e.get("language") == "vf" and e.get("season_number") is not None}
    vo_seasons = {e.get("season_number") for e in events if e.get("language") == "vo" and e.get("season_number") is not None}
    vf_complete = {
        e.get("season_number")
        for e in events
        if e.get("language") == "vf" and e.get("scope") == "season_complete" and e.get("season_number") is not None
    }
    parts: list[str] = []
    if vf_seasons:
        if vf_complete == vf_seasons:
            detail = f"{len(vf_seasons)} saison(s) complete(s) en VF"
        else:
            detail = f"{len(vf_seasons)} saison(s) en VF"
        if vf_complete and vf_complete != vf_seasons:
            detail += f", dont {len(vf_complete)} complete(s)"
        parts.append(detail)
    if vo_seasons:
        parts.append(f"{len(vo_seasons)} saison(s) en VO")
    if not parts and events:
        parts.append(f"{len(events)} mise(s) a jour de disponibilite")
    reported_seasons = {
        event.get("season_number")
        for event in events
        if event.get("season_number") is not None
    }
    complete_seasons = {
        event.get("season_number")
        for event in events
        if event.get("scope") == "season_complete" and event.get("season_number") is not None
    }
    partial_seasons = reported_seasons - complete_seasons
    if partial_seasons:
        parts.append(f"{len(partial_seasons)} saison(s) partiellement disponible(s)")
    missing_seasons = set(expected_seasons or []) - reported_seasons
    if missing_seasons:
        parts.append(f"{len(missing_seasons)} saison(s) encore en attente")
    if blocked_count:
        parts.append(f"{blocked_count} import(s) encore en attente d'une intervention")
    return ". ".join(parts) + ("." if parts else "")


def classify_batch_availability(events: list[dict], expected_seasons: list[int] | None = None) -> dict:
    """Classe un lot selon le niveau le plus utile a annoncer a l'utilisateur."""
    expected = {int(season) for season in (expected_seasons or []) if int(season) > 0}
    reported = {e.get("season_number") for e in events if e.get("season_number") is not None}
    complete = {
        e.get("season_number")
        for e in events
        if e.get("scope") == "season_complete" and e.get("season_number") is not None
    }
    episode_events = [e for e in events if e.get("scope") == "episode"]
    started = {
        e.get("season_number")
        for e in events
        if e.get("scope") == "season_start" and e.get("season_number") is not None
    }
    if expected and expected.issubset(complete):
        variant = "series_complete"
    elif len(complete) >= 2 or (complete and (started or episode_events)):
        variant = "series_partial"
    elif len(complete) == 1:
        variant = "season_complete"
    elif len(episode_events) == 1 and not started:
        variant = "episode_available"
    elif len(episode_events) > 1:
        variant = "season_partial"
    else:
        variant = "season_started"
    return {
        "availability_variant": variant,
        "available_seasons": sorted(reported),
        "complete_seasons": sorted(complete),
        "partial_seasons": sorted((reported - complete)),
        "missing_seasons": sorted(expected - reported),
        "expected_seasons": sorted(expected),
        "episode_count": len(episode_events),
    }


async def _summary_recipients(db, settings: Settings, req: MediaRequest, events: list[dict]) -> list[str]:
    from .notification_orchestrator import (
        _get_recipients,
        _get_vf_recipients,
        _resolve_requester_users,
    )

    users = await _resolve_requester_users(req, db)
    recipients: list[str] = []
    language_events = [event for event in events if event.get("language") in {"vo", "vf"}]
    language_enabled = any(
        settings.email_on_vf_available if event.get("is_upgrade") else settings.email_on_available
        for event in language_events
    )
    if language_events and language_enabled:
        recipients.extend(_get_vf_recipients(users, settings, req.vf_category))
    if any(event.get("language") is None for event in events) and settings.email_on_available:
        recipients.extend(_get_recipients(users, settings, "available"))
    return list(dict.fromkeys(recipients))


async def advance_acquisition_batches(db, settings: Settings | None, *, now=None) -> dict[str, int]:
    """Stabilise/clot les lots et met en queue resumes et alertes administrateur."""
    now = now or now_utc_naive()
    counters = {"stabilizing": 0, "summaries": 0, "admin_alerts": 0, "closed": 0}
    batches = (
        await db.execute(select(SeriesAcquisitionBatch).filter(SeriesAcquisitionBatch.status.in_(OPEN_BATCH_STATES)))
    ).scalars().all()

    for batch in batches:
        observations = (
            await db.execute(
                select(SonarrQueueObservation).filter(
                    SonarrQueueObservation.batch_id == batch.id,
                    SonarrQueueObservation.resolved_at.is_(None),
                )
            )
        ).scalars().all()
        active = [observation for observation in observations if observation.state in ACTIVE_QUEUE_STATES]
        blocked = [observation for observation in observations if observation.state == "import_blocked"]

        if settings and settings.admin_notification_email:
            req = await db.get(MediaRequest, batch.request_id) if batch.request_id else None
            for observation in blocked:
                if observation.admin_alert_queued_at or not req:
                    continue
                reason = observation.error_message or "Import Sonarr bloque : verification manuelle requise."
                await enqueue(
                    "failed",
                    req.id,
                    parse_email_list(settings.admin_notification_email),
                    {
                        "scope": "import_blocked",
                        "reason": f"{reason} ({observation.title or 'element Sonarr'})",
                        "admin_only": True,
                    },
                    db=db,
                )
                observation.admin_alert_queued_at = now
                counters["admin_alerts"] += 1

        if active:
            batch.status = "open"
            batch.stabilization_started_at = None
            continue
        if batch.status != "stabilizing":
            batch.status = "stabilizing"
            batch.stabilization_started_at = now
            counters["stabilizing"] += 1

        stable_since = max(
            value for value in (batch.stabilization_started_at, batch.last_plex_change_at, batch.opened_at) if value
        )
        if now - stable_since < STABILIZATION_DELAY and now - batch.opened_at < MAX_BATCH_DELAY:
            continue

        try:
            events = json.loads(batch.pending_events or "[]")
        except (TypeError, ValueError):
            events = []
        req = await db.get(MediaRequest, batch.request_id) if batch.request_id else None
        if events and req and settings:
            recipients = await _summary_recipients(db, settings, req, events)
            try:
                expected_seasons = json.loads(batch.expected_seasons or "[]")
            except (TypeError, ValueError):
                expected_seasons = []
            availability = classify_batch_availability(events, expected_seasons)
            await enqueue(
                "available",
                req.id,
                recipients,
                {
                    "scope": "series_batch",
                    "language": None,
                    # Le recap peut melanger premieres disponibilites et ameliorations :
                    # il utilise donc le visuel neutre "disponible", pas un mail VF pur.
                    "is_upgrade": False,
                    "batch_summary": build_batch_summary(events, len(blocked), expected_seasons),
                    **availability,
                },
                db=db,
            )
            batch.summary_queued_at = now
            counters["summaries"] += 1
        batch.status = "closed"
        batch.closed_at = now
        counters["closed"] += 1
    return counters
