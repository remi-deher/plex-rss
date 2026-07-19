"""Journal persistant du parcours d'une demande, pour le diagnostic."""

import json
from typing import Any

from ..models import DiagnosticEvent, MediaRequest
from ..utils import now_utc_naive


async def record_event(
    db,
    *,
    category: str,
    action: str,
    status: str = "success",
    request: MediaRequest | None = None,
    message: str = "",
    details: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> DiagnosticEvent:
    """Ajoute un événement sans effectuer de commit."""
    event = DiagnosticEvent(
        request_id=request.id if request else None,
        correlation_id=correlation_id or (f"request:{request.id}" if request else None),
        category=category,
        action=action,
        status=status,
        title=request.title if request else None,
        media_type=request.media_type if request else None,
        source=request.source if request else None,
        message=message,
        details=json.dumps(details or {}, ensure_ascii=False, default=str),
        created_at=now_utc_naive(),
    )
    db.add(event)
    return event


def update_request_context(request: MediaRequest, **values: Any) -> dict[str, Any]:
    """Fusionne le dernier contexte de diagnostic dans la demande."""
    try:
        context = json.loads(request.diagnostic_context or "{}")
    except (TypeError, ValueError):
        context = {}
    context.update({key: value for key, value in values.items() if value is not None})
    request.diagnostic_context = json.dumps(context, ensure_ascii=False, default=str)
    return context


def request_context(request: MediaRequest) -> dict[str, Any]:
    try:
        value = json.loads(request.diagnostic_context or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}
