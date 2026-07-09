import hmac
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import MediaRequest, PlexUser, RequestStatus, Settings, VfEpisodeStatus
from ..notification_queue import enqueue as enqueue_notification
from ..utils import now_utc

router = APIRouter(prefix="/webhook", tags=["webhook"])
logger = logging.getLogger(__name__)


def _check_webhook_secret(request: Request, settings: Settings | None) -> None:
    """Vérifie le secret partagé si un webhook_secret est configuré.

    Un secret est généré automatiquement au premier démarrage (voir
    database.seed_defaults) donc ce contrôle est actif par défaut. Le secret
    peut être fourni via le header X-Webhook-Secret ou le paramètre de requête
    ?secret= (nécessaire pour Plex, qui ne permet pas de header custom sur ses
    webhooks). Si l'admin l'a explicitement révoqué, l'endpoint reste ouvert.
    """
    expected = (settings.webhook_secret if settings else None) or ""
    if not expected:
        logger.warning("Webhook reçu sans webhook_secret configuré : endpoint non authentifié")
        return
    provided = request.headers.get("X-Webhook-Secret") or request.query_params.get("secret") or ""
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="Secret de webhook invalide")


def _get_recipients(user_obj, settings: Settings) -> list[str]:
    raw = (user_obj.notification_email if user_obj else None) or (settings.smtp_from if settings else "") or ""
    recipients = [e.strip() for e in raw.split(",") if e.strip()]
    admin_email = (settings.admin_notification_email or "").strip() if settings else ""
    if admin_email and user_obj and getattr(user_obj, "notify_admin", True):
        for addr in [e.strip() for e in admin_email.split(",") if e.strip()]:
            if addr not in recipients:
                recipients.append(addr)
    return recipients


def _delete_vf_episode_cache(db: Session, request_id: int) -> None:
    db.query(VfEpisodeStatus).filter(
        VfEpisodeStatus.source_type == "request", VfEpisodeStatus.source_id == request_id
    ).delete()


def _arr_event_query(
    db: Session,
    media_type: str,
    *,
    arr_id: int | None = None,
    tmdb_id: int | str | None = None,
    tvdb_id: int | str | None = None,
    imdb_id: str | None = None,
    title: str | None = None,
    instance_id: int | None = None,
):
    q = db.query(MediaRequest).filter(MediaRequest.media_type == media_type)
    if instance_id:
        q = q.filter(MediaRequest.arr_instance_id == instance_id)

    candidates = []
    if arr_id:
        candidates.append(MediaRequest.arr_id == int(arr_id))
    if tmdb_id:
        candidates.append(MediaRequest.tmdb_id == str(tmdb_id))
    if tvdb_id:
        candidates.append(MediaRequest.tvdb_id == str(tvdb_id))
    if imdb_id:
        candidates.append(MediaRequest.imdb_id == str(imdb_id))

    if candidates:
        return q.filter(or_(*candidates))
    if title:
        return q.filter(MediaRequest.title.ilike(f"%{title}%"))
    return q.filter(False)


def _mark_available_and_notify(
    title: str,
    media_type: str,
    arr_id: int | None,
    db: Session,
    settings: Settings,
    *,
    tmdb_id: int | str | None = None,
    tvdb_id: int | str | None = None,
    imdb_id: str | None = None,
    instance_id: int | None = None,
):
    """Trouve les demandes correspondantes, les marque disponibles, empile les notifications."""
    q = _arr_event_query(
        db,
        media_type,
        arr_id=arr_id,
        tmdb_id=tmdb_id,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
        title=title,
        instance_id=instance_id,
    )
    requests = q.all()
    for req in requests:
        if req.status == RequestStatus.available:
            continue
        req.status = RequestStatus.available
        req.available_at = now_utc()
        if arr_id and not req.arr_id:
            req.arr_id = int(arr_id)
        if instance_id and not req.arr_instance_id:
            req.arr_instance_id = instance_id
        db.commit()
        if settings and settings.email_on_available and not req.available_mail_sent:
            user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
            recipients = _get_recipients(user_obj, settings)
            enqueue_notification("available", req.id, recipients)
    return len(requests)


def _delete_arr_requests(
    db: Session,
    media_type: str,
    *,
    arr_id: int | None = None,
    tmdb_id: int | str | None = None,
    tvdb_id: int | str | None = None,
    imdb_id: str | None = None,
    title: str | None = None,
    instance_id: int | None = None,
) -> int:
    requests = _arr_event_query(
        db,
        media_type,
        arr_id=arr_id,
        tmdb_id=tmdb_id,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
        title=title,
        instance_id=instance_id,
    ).all()
    count = 0
    for req in requests:
        _delete_vf_episode_cache(db, req.id)
        db.delete(req)
        count += 1
    db.commit()
    return count


def _query_instance_id(request: Request) -> int | None:
    raw = request.query_params.get("instance_id")
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


@router.post("/sonarr")
async def sonarr_webhook(request: Request):
    """Receives Sonarr OnImport/OnDownload webhook events."""
    db: Session = SessionLocal()
    try:
        settings = db.query(Settings).first()
        _check_webhook_secret(request, settings)

        data = await request.json()
        event = data.get("eventType", "")
        logger.info(f"Sonarr webhook: {event}")

        if event in ("SeriesDelete", "EpisodeFileDelete"):
            series = data.get("series", {})
            deleted = _delete_arr_requests(
                db,
                "show",
                arr_id=series.get("id"),
                tvdb_id=series.get("tvdbId"),
                title=series.get("title", ""),
                instance_id=_query_instance_id(request),
            )
            return {"status": "ok", "deleted": deleted}

        if event not in ("Download", "Import"):
            return {"status": "ignored"}

        series = data.get("series", {})
        title = series.get("title", "")
        sonarr_id = series.get("id")
        tvdb_id = series.get("tvdbId")

        matched = _mark_available_and_notify(
            title,
            "show",
            sonarr_id,
            db,
            settings,
            tvdb_id=tvdb_id,
            instance_id=_query_instance_id(request),
        )
        return {"status": "ok", "matched": matched}
    finally:
        db.close()


@router.post("/radarr")
async def radarr_webhook(request: Request):
    """Receives Radarr OnDownload/OnImport webhook events."""
    db: Session = SessionLocal()
    try:
        settings = db.query(Settings).first()
        _check_webhook_secret(request, settings)

        data = await request.json()
        event = data.get("eventType", "")
        logger.info(f"Radarr webhook: {event}")

        if event in ("MovieDelete", "MovieFileDelete"):
            movie = data.get("movie", {})
            deleted = _delete_arr_requests(
                db,
                "movie",
                arr_id=movie.get("id"),
                tmdb_id=movie.get("tmdbId"),
                imdb_id=movie.get("imdbId"),
                title=movie.get("title", ""),
                instance_id=_query_instance_id(request),
            )
            return {"status": "ok", "deleted": deleted}

        if event not in ("Download", "Import", "MovieAdded"):
            return {"status": "ignored"}

        movie = data.get("movie", {})
        title = movie.get("title", "")
        radarr_id = movie.get("id")
        tmdb_id = movie.get("tmdbId")
        imdb_id = movie.get("imdbId")

        matched = _mark_available_and_notify(
            title,
            "movie",
            radarr_id,
            db,
            settings,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
            instance_id=_query_instance_id(request),
        )
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
    _db = SessionLocal()
    try:
        _check_webhook_secret(request, _db.query(Settings).first())
    finally:
        _db.close()

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
            req.available_at = now_utc()
            db.commit()
            logger.info(f"Plex webhook: '{req.title}' marqué disponible")
            if settings and settings.email_on_available and not req.available_mail_sent:
                user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
                recipients = _get_recipients(user_obj, settings)
                enqueue_notification("available", req.id, recipients)

        return {"status": "ok", "event": event, "matched": len(requests), "title": title}
    finally:
        db.close()
