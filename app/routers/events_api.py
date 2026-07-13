"""Authenticated Server-Sent Events endpoint."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..dependencies import current_user, require_auth
from ..realtime import subscribe

router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events", dependencies=[Depends(require_auth)])
async def events(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(401, "SSE requires an authenticated browser session")
    last_id = request.headers.get("Last-Event-ID") or request.query_params.get("last_event_id")

    async def stream():
        yield "retry: 3000\n\n"
        async for event in subscribe(last_id, user):
            if await request.is_disconnected():
                break
            if event is None:
                yield ": heartbeat\n\n"
                continue
            payload = json.dumps(event, ensure_ascii=True, separators=(",", ":"))
            yield f"id: {event['id']}\nevent: {event['type']}\ndata: {payload}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
