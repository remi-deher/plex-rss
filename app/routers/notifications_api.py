from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_admin
from ..models import MediaRequest, NotificationLog, PlexUser, Settings
from ..notification_queue import enqueue as enqueue_notification
from ..serializers import format_datetime
from ..services.email_service import (
    DEFAULT_AVAILABLE_TEMPLATE,
    DEFAULT_REQUEST_TEMPLATE,
    _build_tags,
    get_event_visuals,
    get_shared_email_parts,
    render_subject,
    render_template,
)
from ..services.notification_catalog import event_badge_class, get_event
from ..utils import get_or_404, now_utc, now_utc_naive

router = APIRouter(prefix="/api", tags=["notifications"], dependencies=[Depends(require_admin)])


@router.get("/activity")
def activity_log(db: Session = Depends(get_db)):
    """Retourne les 25 événements les plus récents (7 derniers jours) pour le journal."""
    cutoff = now_utc_naive() - timedelta(days=7)
    reqs = (
        db.query(MediaRequest)
        .filter(
            (MediaRequest.requested_at >= cutoff)
            | (MediaRequest.available_at >= cutoff)
            | (MediaRequest.vf_available_at >= cutoff)
        )
        .order_by(MediaRequest.requested_at.desc())
        .limit(120)
        .all()
    )
    users = {u.plex_user_id: (u.custom_name or u.display_name or u.plex_user_id) for u in db.query(PlexUser).all()}

    events: list[dict[str, Any]] = []

    def add_event(req: MediaRequest, event_type: str, event_time, label: str, detail: str = ""):
        if not event_time:
            return
        user_name = users.get(req.plex_user_id) or req.plex_user or req.plex_user_id or "?"
        events.append(
            {
                "type": event_type,
                "label": label,
                "detail": detail,
                "title": req.title,
                "user": user_name,
                "media_type": req.media_type,
                "source": req.source,
                "status": req.status,
                "request_id": req.id,
                "arr_slug": req.arr_slug,
                "time": format_datetime(event_time),
            }
        )

    for r in reqs:
        if r.requested_at:
            if r.status == "failed":
                add_event(r, "failed", r.requested_at, "Echec", "Traitement en erreur")
            elif r.status == "sent_to_arr":
                add_event(r, "sent", r.requested_at, "Transmise", "Detection et envoi vers ARR")
            else:
                add_event(r, "detected", r.requested_at, "Detectee", "Detection watchlist ou demande")
        if r.available_at and r.available_at >= cutoff:
            add_event(r, "available", r.available_at, "Disponible", "Disponibilite confirmee")
        if r.vf_available_at and r.vf_available_at >= cutoff:
            add_event(r, "vf_available", r.vf_available_at, "VF disponible", "Upgrade VF detecte")

    logs = (
        db.query(NotificationLog)
        .filter(NotificationLog.sent_at >= cutoff)
        .order_by(NotificationLog.sent_at.desc())
        .limit(80)
        .all()
    )
    for log in logs:
        events.append(
            {
                "type": "notification" if log.success else "notification_failed",
                "label": "Notification" if log.success else "Notif. echouee",
                "detail": log.event,
                "title": log.media_title or (f"Demande #{log.req_id}" if log.req_id else "Notification"),
                "user": "Admin" if log.is_admin else log.recipient,
                "media_type": log.media_type,
                "source": "notification",
                "status": "sent" if log.success else "failed",
                "request_id": log.req_id,
                "arr_slug": None,
                "time": format_datetime(log.sent_at),
            }
        )

    events.sort(key=lambda e: e["time"], reverse=True)
    return events[:40]


@router.get("/notifications/recent-available")
def recent_available(since: str = None, db: Session = Depends(get_db)):
    """Retourne les médias devenus disponibles depuis `since` (ISO 8601)."""
    q = db.query(MediaRequest).filter(MediaRequest.status == "available")
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            q = q.filter(MediaRequest.available_at >= since_dt)
        except ValueError:
            pass
    items = q.order_by(MediaRequest.available_at.desc()).limit(10).all()
    return [{"id": r.id, "title": r.title, "available_at": format_datetime(r.available_at)} for r in items]


@router.get("/logs")
def get_logs(_: None = Depends(require_admin)):
    """Retourne les derniers logs applicatifs (buffer mémoire circulaire)."""
    from ..log_buffer import get_logs as _get_logs

    return _get_logs()


@router.get("/email/preview")
def preview_email_template(event: str = "request", user_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Rend le template email avec des données fictives et retourne le HTML."""
    settings = db.query(Settings).first()

    plex_user_name = "Jean Dupont"
    recipient_email = "jean.dupont@plex.local"
    if user_id:
        user = db.query(PlexUser).filter(PlexUser.id == user_id).first()
        if user:
            plex_user_name = user.custom_name or user.display_name or user.plex_user_id
            recipient_email = user.notification_email or user.plex_email or "utilisateur@plex.local"

    fake = MediaRequest(
        title="Dune : Deuxième Partie",
        year=2024,
        media_type="movie",
        plex_user=plex_user_name,
        overview="Paul Atréides s'unit aux Fremen pour mener la guerre sainte contre ceux qui ont détruit sa famille.",
        poster_url="https://image.tmdb.org/t/p/w300/1pdfLvkbY9ohJlCjQH2CZjjYVvJ.jpg",
    )
    tags = _build_tags(fake, plex_user_name, language="vf")

    if event == "available":
        tpl = (
            settings.email_available_template
            if (settings and isinstance(settings.email_available_template, str))
            else None
        ) or DEFAULT_AVAILABLE_TEMPLATE
        subject_tmpl = (
            settings.email_available_subject
            if (settings and isinstance(settings.email_available_subject, str))
            else None
        ) or "[Plexarr] {titre} est disponible sur Plex !"
    else:
        tpl = (
            settings.email_request_template if (settings and isinstance(settings.email_request_template, str)) else None
        ) or DEFAULT_REQUEST_TEMPLATE
        subject_tmpl = (
            settings.email_request_subject if (settings and isinstance(settings.email_request_subject, str)) else None
        ) or "[Plexarr] Nouvelle demande : {titre}"

    fallback_subject = (
        f"[Plexarr] Nouvelle demande : {fake.title}"
        if event == "request"
        else f"[Plexarr] {fake.title} est disponible sur Plex !"
    )
    rendered_subject = render_subject(subject_tmpl, tags, fallback=fallback_subject)

    jinja_ctx = get_shared_email_parts(settings)
    jinja_ctx.update(get_event_visuals(settings, event if event == "available" else "request"))
    html = render_template(tpl, tags, jinja_ctx)

    header_html = f"""
    <div style="background:#2a2a2a; color:#fff; font-family:sans-serif; padding:12px 20px; border-bottom:1px solid #333; margin-bottom:15px; font-size:13px;">
      <div style="margin-bottom:4px;"><strong>Objet :</strong> <span style="color:#e5a00d; font-weight:bold;">{rendered_subject}</span></div>
      <div style="margin-bottom:4px;"><strong>De :</strong> {(settings.smtp_from if settings else None) or "plex-rss@monitor.local"}</div>
      <div><strong>À :</strong> {recipient_email}</div>
    </div>
    """

    if "<body>" in html:
        html = html.replace("<body>", f"<body>{header_html}")
    elif "<body style=" in html:
        parts = html.split("<body", 1)
        if len(parts) == 2:
            body_tag, rest = parts[1].split(">", 1)
            html = f"{parts[0]}<body{body_tag}>{header_html}{rest}"
    else:
        html = header_html + html

    return HTMLResponse(content=html)


@router.get("/notifications/log")
def list_notification_logs(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    q = db.query(NotificationLog).order_by(NotificationLog.sent_at.desc())
    total = q.count()
    logs = q.offset(offset).limit(min(limit, 200)).all()
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "id": log.id,
                "sent_at": format_datetime(log.sent_at),
                "event": log.event,
                "event_label": get_event(log.event).label,
                "event_group": get_event(log.event).group,
                "event_description": get_event(log.event).description,
                "event_badge_class": event_badge_class(log.event),
                "recipient": log.recipient,
                "is_admin": log.is_admin,
                "media_title": log.media_title,
                "media_type": log.media_type,
                "success": log.success,
                "status_label": "Envoyé" if log.success else "Erreur",
                "error_msg": log.error_msg,
                "req_id": log.req_id,
            }
            for log in logs
        ],
    }


@router.post("/notifications/{log_id}/resend")
async def resend_notification(log_id: int, db: Session = Depends(get_db)):
    log = db.query(NotificationLog).filter(NotificationLog.id == log_id).first()
    if not log:
        raise HTTPException(404, "Log introuvable")
    if not log.req_id:
        raise HTTPException(400, "req_id manquant sur cette entrée de log (envoi antérieur à la v2.1)")
    req = get_or_404(db, MediaRequest, log.req_id, "Demande originale introuvable")
    # Les anciens évènements de disponibilité (available_vf, vo_only, vf_available,
    # episode_track, partially_available, available_vo_tracking — retirés du catalogue,
    # voir notification_catalog.py) sont tous fusionnés dans "available" aujourd'hui.
    event = log.event if log.event in ("request", "available", "failed") else "available"
    context = (
        {
            "scope": log.scope,
            "language": log.language,
            "is_upgrade": log.is_upgrade,
            "season_number": log.season_number,
            "episode_number": log.episode_number,
        }
        if event == "available"
        else None
    )
    enqueue_notification(event, req.id, [log.recipient], context)
    return {"status": "queued", "recipient": log.recipient, "event": event}
