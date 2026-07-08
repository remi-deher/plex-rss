from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_auth
from ..models import MediaRequest, NotificationLog, PlexUser, Settings
from ..notification_queue import enqueue as enqueue_notification
from ..serializers import format_datetime
from ..services.email_service import (
    DEFAULT_AVAILABLE_TEMPLATE,
    DEFAULT_REQUEST_TEMPLATE,
    add_email_footer,
    render_subject,
    render_template,
)
from ..services.notification_catalog import event_badge_class, get_event
from ..utils import get_or_404, now_utc, now_utc_naive

router = APIRouter(prefix="/api", tags=["notifications"], dependencies=[Depends(require_auth)])


@router.get("/activity")
def activity_log(db: Session = Depends(get_db)):
    """Retourne les 25 événements les plus récents (7 derniers jours) pour le journal."""
    cutoff = now_utc_naive() - timedelta(days=7)
    reqs = (
        db.query(MediaRequest)
        .filter(MediaRequest.requested_at >= cutoff)
        .order_by(MediaRequest.requested_at.desc())
        .limit(50)
        .all()
    )
    users = {u.plex_user_id: (u.custom_name or u.display_name or u.plex_user_id) for u in db.query(PlexUser).all()}

    events = []
    for r in reqs:
        user_name = users.get(r.plex_user_id) or r.plex_user or r.plex_user_id or "?"
        if r.requested_at:
            events.append(
                {
                    "type": r.status if r.status in ("failed",) else "request",
                    "title": r.title,
                    "user": user_name,
                    "media_type": r.media_type,
                    "time": format_datetime(r.requested_at),
                }
            )
        if r.available_at and r.available_at >= cutoff:
            events.append(
                {
                    "type": "available",
                    "title": r.title,
                    "user": user_name,
                    "media_type": r.media_type,
                    "time": format_datetime(r.available_at),
                }
            )
    events.sort(key=lambda e: e["time"], reverse=True)
    return events[:25]


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
def get_logs(_: None = Depends(require_auth)):
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
    ctx = {
        "title": fake.title,
        "year": fake.year,
        "poster_url": fake.poster_url,
        "plex_user": fake.plex_user,
        "media_type": fake.media_type,
        "media_type_label": "Film",
        "media_type_label_cap": "Le film",
        "overview": fake.overview,
        "genres": "Science-Fiction, Aventure",
        "language_reason": "VF film complet",
    }

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
        ) or "[Plexarr] {{ title }} est disponible sur Plex !"
    else:
        tpl = (
            settings.email_request_template if (settings and isinstance(settings.email_request_template, str)) else None
        ) or DEFAULT_REQUEST_TEMPLATE
        subject_tmpl = (
            settings.email_request_subject if (settings and isinstance(settings.email_request_subject, str)) else None
        ) or "[Plexarr] Nouvelle demande : {{ title }}"

    fallback_subject = (
        f"[Plexarr] Nouvelle demande : {fake.title}"
        if event == "request"
        else f"[Plexarr] {fake.title} est disponible sur Plex !"
    )
    rendered_subject = render_subject(subject_tmpl, ctx, fallback=fallback_subject)

    html = render_template(tpl, ctx)

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

    return HTMLResponse(content=add_email_footer(html))


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
    enqueue_notification(log.event, req.id, [log.recipient])
    return {"status": "queued", "recipient": log.recipient, "event": log.event}
