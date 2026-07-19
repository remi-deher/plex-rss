"""Machine de transitions centralisee des demandes.

Ce module est le seul endroit qui doit faire evoluer simultanement l'etat metier
(`status`) et l'etat technique (`fulfillment_status`). Il ne commit pas : l'appelant
garde la frontiere transactionnelle, mais tous les effets persistants sont ajoutes a
la meme transaction.
"""

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import FulfillmentStatus, MediaRequest, RequestStatus
from ..utils import now_utc_naive
from .diagnostics import record_event, update_request_context
from .download_history import record_completed
from .notification_policy import register_transition_notification_intent


async def transition_request(
    db: AsyncSession,
    req: MediaRequest,
    event: str,
    *,
    source: str,
    instance_name: str | None = None,
    message: str | None = None,
    error: str | None = None,
    available_at: datetime | None = None,
    details: dict[str, Any] | None = None,
) -> bool:
    """Applique une transition idempotente et journalisee.

    Retourne True lorsque l'etat metier ou technique a reellement change. L'appelant
    peut ainsi n'envoyer une notification qu'une fois, meme si webhook et poll voient
    le meme evenement presque simultanement.
    """
    now = now_utc_naive()
    old_business = req.status.value if hasattr(req.status, "value") else str(req.status)
    old_fulfillment = (
        req.fulfillment_status.value
        if hasattr(req.fulfillment_status, "value")
        else str(req.fulfillment_status or FulfillmentStatus.not_submitted)
    )

    mapping = {
        "created": (RequestStatus.pending, FulfillmentStatus.awaiting_submission),
        "approval_required": (RequestStatus.pending_approval, FulfillmentStatus.not_submitted),
        "submitted": (RequestStatus.sent_to_arr, FulfillmentStatus.submitted),
        "queued": (None, FulfillmentStatus.queued),
        "download_started": (None, FulfillmentStatus.downloading),
        "import_started": (None, FulfillmentStatus.importing),
        "download_finished": (None, FulfillmentStatus.awaiting_plex),
        "arr_imported": (None, FulfillmentStatus.awaiting_plex),
        "plex_pending": (None, FulfillmentStatus.awaiting_plex),
        "partially_available": (RequestStatus.partially_available, FulfillmentStatus.partially_available),
        "available": (RequestStatus.available, FulfillmentStatus.completed),
        "failed": (RequestStatus.failed, FulfillmentStatus.failed),
        "rejected": (RequestStatus.rejected, FulfillmentStatus.removed),
        "retry": (RequestStatus.pending, FulfillmentStatus.awaiting_submission),
        "availability_lost": (RequestStatus.sent_to_arr, FulfillmentStatus.submitted),
        "arr_removed": (None, FulfillmentStatus.removed),
    }
    if event not in mapping:
        raise ValueError(f"Transition de demande inconnue: {event}")

    business, fulfillment = mapping[event]
    if business is not None:
        req.status = business
    req.fulfillment_status = fulfillment
    req.fulfillment_updated_at = now
    req.fulfillment_error = error if event == "failed" else None
    req.is_downloading = fulfillment in {FulfillmentStatus.queued, FulfillmentStatus.downloading}

    if event == "available":
        req.available_at = req.available_at or available_at or now
        req.next_release_at = None
        req.next_release_label = None
    if event == "submitted" and not req.arr_processed_at:
        req.arr_processed_at = now
    if event == "retry":
        req.failure_mail_sent = False

    new_business = req.status.value if hasattr(req.status, "value") else str(req.status)
    new_fulfillment = fulfillment.value
    changed = old_business != new_business or old_fulfillment != new_fulfillment
    if not changed:
        return False

    register_transition_notification_intent(req, event)

    context = {
        "lifecycle_event": event,
        "fulfillment_status": new_fulfillment,
        "fulfillment_source": source,
    }
    if error:
        context["fulfillment_error"] = error
    update_request_context(req, **context)
    await record_event(
        db,
        category="lifecycle",
        action=event,
        status="error" if event == "failed" else "success",
        request=req,
        message=message or f"Transition {old_business}/{old_fulfillment} -> {new_business}/{new_fulfillment}",
        details={
            "source": source,
            "instance": instance_name,
            "business_before": old_business,
            "business_after": new_business,
            "fulfillment_before": old_fulfillment,
            "fulfillment_after": new_fulfillment,
            **(details or {}),
        },
    )
    if event == "available":
        await record_completed(
            db,
            title=req.title,
            year=req.year,
            media_type=req.media_type,
            source=source,
            instance_name=instance_name,
            poster_url=req.poster_url,
            request_id=req.id,
        )
    return True
