import logging
from datetime import datetime
from fastapi import APIRouter, Request
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import Settings, MediaRequest, RequestStatus, PlexUser
from ..services.email_service import send_available_notification

router = APIRouter(prefix="/webhook", tags=["webhook"])
logger = logging.getLogger(__name__)


async def _mark_available_and_notify(title: str, media_type: str, arr_id: int | None, db: Session, settings: Settings):
    """Find matching pending requests, mark available, send notification email."""
    q = db.query(MediaRequest).filter(MediaRequest.status != RequestStatus.available)
    if arr_id:
        q = q.filter(MediaRequest.arr_id == arr_id)
    else:
        q = q.filter(
            MediaRequest.title.ilike(f"%{title}%"),
            MediaRequest.media_type == media_type,
        )
    requests = q.all()
    for req in requests:
        req.status = RequestStatus.available
        req.available_at = datetime.utcnow()
        db.commit()
        if settings and settings.email_on_available and not req.available_mail_sent:
            user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
            recipient = (user_obj.notification_email if user_obj else None) or (settings.smtp_from if settings else None)
            if recipient:
                try:
                    await send_available_notification(settings, req, recipient)
                    req.available_mail_sent = True
                    db.commit()
                except Exception as e:
                    logger.error(f"Available email failed: {e}")
    return len(requests)


@router.post("/sonarr")
async def sonarr_webhook(request: Request):
    """Receives Sonarr OnImport/OnDownload webhook events."""
    data = await request.json()
    event = data.get("eventType", "")
    logger.info(f"Sonarr webhook: {event}")

    if event not in ("Download", "Import"):
        return {"status": "ignored"}

    series = data.get("series", {})
    title = series.get("title", "")
    tvdb_id = series.get("tvdbId")

    db: Session = SessionLocal()
    try:
        settings = db.query(Settings).first()
        # Try to find by arr_id (tvdbId stored as arr_id for shows)
        matched = await _mark_available_and_notify(title, "show", tvdb_id, db, settings)
        return {"status": "ok", "matched": matched}
    finally:
        db.close()


@router.post("/radarr")
async def radarr_webhook(request: Request):
    """Receives Radarr OnDownload/OnImport webhook events."""
    data = await request.json()
    event = data.get("eventType", "")
    logger.info(f"Radarr webhook: {event}")

    if event not in ("Download", "Import", "MovieAdded"):
        return {"status": "ignored"}

    movie = data.get("movie", {})
    title = movie.get("title", "")
    tmdb_id = movie.get("tmdbId")

    db: Session = SessionLocal()
    try:
        settings = db.query(Settings).first()
        matched = await _mark_available_and_notify(title, "movie", tmdb_id, db, settings)
        return {"status": "ok", "matched": matched}
    finally:
        db.close()
