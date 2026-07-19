"""Politique reliant les transitions du cycle de vie aux notifications.

La transition produit une intention pure. Son expedition est volontairement realisee
apres le commit par l'appelant afin de ne jamais notifier un changement rollbacke.
"""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MediaRequest, PlexUser, Settings


TRANSITION_NOTIFICATION_EVENTS = {
    "submitted": "request",
    "failed": "failed",
    "partially_available": "available",
    "available": "available",
}

TECHNICAL_ORIGINS = {"arr", "arr_sync", "manual_import", "plex", "plex_sync", "library"}
PSEUDO_REQUESTERS = {"", "manual", "system", "unknown", "arr", "plex"}


def notification_intent_for_transition(event: str) -> str | None:
    return TRANSITION_NOTIFICATION_EVENTS.get(event)


def register_transition_notification_intent(req: MediaRequest, event: str) -> str | None:
    intent = notification_intent_for_transition(event)
    if not intent:
        return None
    intents = set(getattr(req, "_notification_intents", set()))
    intents.add(intent)
    req._notification_intents = intents
    return intent


def has_transition_notification_intent(req: MediaRequest, event: str) -> bool:
    intent = notification_intent_for_transition(event) or event
    return intent in set(getattr(req, "_notification_intents", set()))


def consume_transition_notification_intent(req: MediaRequest, event: str) -> bool:
    intent = notification_intent_for_transition(event) or event
    intents = set(getattr(req, "_notification_intents", set()))
    if intent not in intents:
        return False
    intents.remove(intent)
    req._notification_intents = intents
    return True


def _requester_ids(req: MediaRequest) -> set[str]:
    ids = {str(req.plex_user_id or "").strip()}
    try:
        ids.update(
            str(row.get("plex_user_id") or "").strip()
            for row in json.loads(req.extra_requesters or "[]")
            if isinstance(row, dict)
        )
    except Exception:
        pass
    return {uid for uid in ids if uid.lower() not in PSEUDO_REQUESTERS}


async def has_real_requester(req: MediaRequest, db: AsyncSession) -> bool:
    """Exige un compte reel; evite le fallback SMTP des demandes techniques."""
    requester_ids = _requester_ids(req)
    if not requester_ids:
        return False
    return (
        await db.execute(
            select(PlexUser.id).filter(PlexUser.plex_user_id.in_(requester_ids), PlexUser.enabled.is_(True)).limit(1)
        )
    ).first() is not None


async def request_notification_is_eligible(req: MediaRequest, db: AsyncSession) -> bool:
    source = (req.source or "").strip().lower()
    if source in TECHNICAL_ORIGINS:
        return False
    return await has_real_requester(req, db)


async def dispatch_transition_notification(
    settings: Settings | None,
    req: MediaRequest,
    db: AsyncSession,
    event: str,
    *,
    reason: str = "",
) -> bool:
    """Expedie une intention apres commit, avec filtrage d'origine/demandeur."""
    intent = notification_intent_for_transition(event) or event
    if not consume_transition_notification_intent(req, intent):
        return False
    if not settings or intent not in {"request", "failed"}:
        return False
    if not await request_notification_is_eligible(req, db):
        return False

    from .notification_orchestrator import _notify

    await _notify(intent, settings, req, db, reason)
    return True
