import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import MediaRequest, PlexUser, RequestStatus, Settings
from ..notification_queue import enqueue as enqueue_notification

router = APIRouter(prefix="/webhook", tags=["webhook"])
logger = logging.getLogger(__name__)


def _get_recipients(user_obj, settings: Settings) -> list[str]:
    raw = (user_obj.notification_email if user_obj else None) or (settings.smtp_from if settings else "") or ""
    recipients = [e.strip() for e in raw.split(",") if e.strip()]
    admin_email = (settings.admin_notification_email or "").strip() if settings else ""
    if admin_email and user_obj and getattr(user_obj, "notify_admin", True):
        for addr in [e.strip() for e in admin_email.split(",") if e.strip()]:
            if addr not in recipients:
                recipients.append(addr)
    return recipients


def _mark_available_and_notify(title: str, media_type: str, arr_id: int | None, db: Session, settings: Settings):
    """Trouve les demandes correspondantes, les marque disponibles, empile les notifications."""
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
        req.available_at = datetime.now(timezone.utc)
        db.commit()
        if settings and settings.email_on_available and not req.available_mail_sent:
            user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
            recipients = _get_recipients(user_obj, settings)
            enqueue_notification("available", req.id, recipients)
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
        matched = _mark_available_and_notify(title, "show", tvdb_id, db, settings)
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
        matched = _mark_available_and_notify(title, "movie", tmdb_id, db, settings)
        return {"status": "ok", "matched": matched}
    finally:
        db.close()


@router.post("/plex")
async def plex_webhook(request: Request):
    """Reçoit les événements Plex (library.new, media.scrobble).

    Plex envoie un multipart/form-data avec un champ `payload` contenant le JSON.
    Nécessite Plex Pass et la configuration d'un webhook dans Plex → Paramètres → Webhooks.

    Événements traités :
    - library.new       : nouveau média ajouté à la bibliothèque Plex
    - media.scrobble    : média regardé en entier (marqué comme vu)
    """
    try:
        form = await request.form()
        raw = str(form.get("payload", ""))
        if not raw:
            # Fallback : JSON direct (certains proxys aplatissent le multipart)
            try:
                data = await request.json()
            except Exception:
                return {"status": "ignored", "reason": "empty payload"}
        else:
            data = json.loads(raw)
    except Exception as e:
        logger.warning(f"Plex webhook parse error: {e}")
        return {"status": "error", "reason": str(e)}

    event = data.get("event", "")
    logger.info(f"Plex webhook: {event}")

    if event not in ("library.new", "media.scrobble"):
        return {"status": "ignored", "event": event}

    metadata = data.get("Metadata", {})
    media_type_plex = metadata.get("type", "")  # "movie" ou "episode"
    title = metadata.get("title", "") or metadata.get("grandparentTitle", "")

    # Pour les épisodes, on utilise le titre de la série parente
    if media_type_plex == "episode":
        title = metadata.get("grandparentTitle", title)
        media_type = "show"
    elif media_type_plex == "movie":
        media_type = "movie"
    else:
        return {"status": "ignored", "reason": f"unsupported media type: {media_type_plex}"}

    # Extraction des identifiants depuis Metadata.Guid (liste)
    guids = metadata.get("Guid", [])
    tmdb_id = None
    tvdb_id = None
    imdb_id = None
    for g in guids:
        gid = g.get("id", "")
        if gid.startswith("tmdb://"):
            tmdb_id = gid.replace("tmdb://", "")
        elif gid.startswith("tvdb://"):
            tvdb_id = gid.replace("tvdb://", "")
        elif gid.startswith("imdb://"):
            imdb_id = gid.replace("imdb://", "")

    # Recherche et mise à jour des demandes correspondantes
    db: Session = SessionLocal()
    try:
        settings = db.query(Settings).first()
        q = db.query(MediaRequest).filter(
            MediaRequest.status != RequestStatus.available,
            MediaRequest.media_type == media_type,
        )
        # Filtre par identifiant si disponible, sinon par titre
        if tmdb_id:
            q = q.filter(MediaRequest.tmdb_id == tmdb_id)
        elif tvdb_id:
            q = q.filter(MediaRequest.tvdb_id == tvdb_id)
        elif imdb_id:
            q = q.filter(MediaRequest.imdb_id == imdb_id)
        else:
            q = q.filter(MediaRequest.title.ilike(f"%{title}%"))

        requests = q.all()
        for req in requests:
            req.status = RequestStatus.available
            req.available_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(f"Plex webhook: '{req.title}' marqué disponible")
            if settings and settings.email_on_available and not req.available_mail_sent:
                user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
                recipients = _get_recipients(user_obj, settings)
                enqueue_notification("available", req.id, recipients)

        return {"status": "ok", "event": event, "matched": len(requests), "title": title}
    finally:
        db.close()
