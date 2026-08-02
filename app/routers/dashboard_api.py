"""Snapshot leger du tableau de bord.

Le navigateur ne doit pas ouvrir une douzaine de requetes HTTP pour reconstruire une
seule vue. Les lectures DB restent concurrentes, chacune avec sa propre session, et le
snapshot est servi en stale-while-revalidate pendant une courte periode.
"""

import asyncio
from collections.abc import Callable

from fastapi import APIRouter, Depends, Query

from ..cache import cache
from ..database import AsyncSessionLocal
from ..dependencies import require_admin
from . import calendar_api, metrics_api, notifications_api, onboarding_api, requests_api

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
