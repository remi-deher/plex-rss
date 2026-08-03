"""Snapshot leger du tableau de bord.

Le navigateur ne doit pas ouvrir une douzaine de requetes HTTP pour reconstruire une
seule vue. Les lectures DB restent concurrentes, chacune avec sa propre session, et le
snapshot est servi en stale-while-revalidate pendant une courte periode.

Deux formes pour le meme calcul :

- `/dashboard/snapshot` assemble tout puis repond d'un bloc. Sert aux rafraichissements
  cibles (`?sections=`) et de repli.
- `/dashboard/snapshot/stream` emet chaque section des qu'elle est prete. Le premier
  affichage n'attend plus la plus lente des dix lectures : chaque panneau se remplit au
  fil de l'eau.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from ..cache import cache
from ..database import AsyncSessionLocal
from ..dependencies import require_admin
from . import calendar_api, metrics_api, notifications_api, onboarding_api, requests_api

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["dashboard"], dependencies=[Depends(require_admin)])

_CACHE_KEY = "plexarr:dashboard:snapshot:v1"


async def _with_session(call: Callable) -> object:
    async with AsyncSessionLocal() as db:
        return await call(db)


def _snapshot_calls() -> dict[str, Callable]:
    return {
        "counts": lambda db: metrics_api.stats_counts(db),
        "pending": lambda db: requests_api.list_pending_requests(db),
        "polls": lambda db: metrics_api.get_poll_history(limit=6, db=db),
        "timeline": lambda db: metrics_api.stats_timeline(db),
        "by_user": lambda db: metrics_api.stats_by_user(db),
        "onboarding": lambda db: onboarding_api.onboarding_status(db, None),
        "top_requested": lambda db: metrics_api.stats_top_requested(db, limit=5),
        "recently_available": lambda db: metrics_api.stats_recently_available(db, limit=5),
        "upcoming": lambda db: calendar_api.upcoming_releases(db=db, limit=8),
        "notifications": lambda db: notifications_api.list_notification_logs(limit=5, db=db),
    }


async def _compute_snapshot(sections: set[str] | None = None) -> dict:
    all_calls = _snapshot_calls()
    calls = {
        name: call for name, call in all_calls.items()
        if sections is None or name in sections
    }
    results = await asyncio.gather(
        *(_with_session(call) for call in calls.values()), return_exceptions=True
    )
    payload: dict = {"errors": []}
    if sections is None or "next_poll" in sections:
        payload["next_poll"] = metrics_api.next_poll_info()
    for name, result in zip(calls, results):
        if isinstance(result, Exception):
            payload["errors"].append(name)
        else:
            payload[name] = result
    return payload


def _frame(payload: dict) -> str:
    """Trame SSE. Le type `text/event-stream` n'est pas un detail cosmetique : c'est le
    seul que le GZipMiddleware de Starlette laisse passer sans le compresser, et donc sans
    le tamponner -- en NDJSON, gzip accumulerait les premieres sections et le flux
    arriverait d'un bloc, exactement ce qu'on cherche a eviter.
    """
    return f"data: {json.dumps(payload)}\n\n"


async def _stream_sections() -> AsyncIterator[str]:
    async def _named(name: str, call: Callable):
        try:
            return name, await _with_session(call), None
        except Exception as exc:  # noqa: BLE001 - une section en echec n'annule pas les autres
            return name, None, exc

    # Simple coup d'oeil au scheduler, sans I/O : part immediatement.
    yield _frame({"next_poll": metrics_api.next_poll_info()})

    calls = _snapshot_calls()
    tasks = [asyncio.create_task(_named(name, call)) for name, call in calls.items()]
    collected: dict = {}
    errors: list[str] = []
    try:
        for completed in asyncio.as_completed(tasks):
            name, value, error = await completed
            if error is not None:
                logger.warning("Section '%s' du tableau de bord indisponible : %s", name, error)
                errors.append(name)
                yield _frame({"errors": [name]})
            else:
                collected[name] = value
                yield _frame({name: value})
    finally:
        # Deconnexion du client en cours de route : rien ne doit continuer a tourner.
        for task in tasks:
            task.cancel()

    # Alimente le meme cache que /dashboard/snapshot, pour qu'un rafraichissement cible ou
    # un repli reparte d'une valeur chaude au lieu de tout recalculer.
    if collected and not errors:
        payload = {**collected, "next_poll": metrics_api.next_poll_info(), "errors": []}
        await cache.set_json(_CACHE_KEY, {"value": payload, "cached_at": time.time()}, ttl_seconds=60)


@router.get("/dashboard/snapshot/stream")
async def dashboard_snapshot_stream():
    """Emet chaque section du tableau de bord des qu'elle est prete.

    Les dix lectures partent en parallele, comme avant ; ce qui change est qu'on n'attend
    plus la plus lente pour afficher les neuf autres.
    """
    return StreamingResponse(
        _stream_sections(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            # nginx tamponne les reponses en amont par defaut, ce qui annulerait le
            # streaming sans rien signaler.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/dashboard/snapshot")
async def dashboard_snapshot(
    refresh: bool = Query(False),
    sections: str | None = Query(None),
):
    if sections:
        requested = {value.strip() for value in sections.split(",") if value.strip()}
        allowed = set(_snapshot_calls()) | {"next_poll"}
        return await _compute_snapshot(requested & allowed)
    if refresh:
        await cache.delete(_CACHE_KEY)
    return await cache.get_or_refresh(
        _CACHE_KEY,
        soft_ttl_seconds=15,
        hard_ttl_seconds=60,
        compute_sync=_compute_snapshot,
        compute_background=_compute_snapshot,
    )
