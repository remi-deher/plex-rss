from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import PlexUser, Settings
from ..services.email_service import (
    DEFAULT_AVAILABLE_TEMPLATE,
    DEFAULT_FAILURE_TEMPLATE,
    DEFAULT_REQUEST_TEMPLATE,
    render_template,
)
from ..services.email_service import _send as smtp_send


def require_auth(request: Request):
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Non authentifié")


router = APIRouter(tags=["email-templates"], dependencies=[Depends(require_auth)])


@router.get("/settings/email-templates")
def email_templates_redirect():
    return RedirectResponse("/settings#tab-templates", status_code=301)


SAMPLE_CONTEXT = {
    "title": "Breaking Bad",
    "year": 2008,
    "poster_url": "https://image.tmdb.org/t/p/w300/ggFHVNu6YYI5L9pCfOacjizRGt.jpg",
    "plex_user": "Jean Dupont",
    "media_type": "show",
    "media_type_label": "Série",
    "media_type_label_cap": "La série",
    "overview": "Un professeur de chimie atteint d'un cancer du poumon se lance dans la fabrication et la vente de méthamphétamine afin de subvenir aux besoins de sa famille.",
    "genres": "Crime, Drame, Thriller",
}


class PreviewRequest(BaseModel):
    template: str
    subject: str
    type: str = "request"
    user_id: Optional[int] = None


@router.post("/api/email-preview")
def preview_email(body: PreviewRequest, db: Session = Depends(get_db)):
    ctx = dict(SAMPLE_CONTEXT)
    recipient_email = "jean.dupont@plex.local"
    if body.user_id:
        user = db.query(PlexUser).filter(PlexUser.id == body.user_id).first()
        if user:
            ctx["plex_user"] = user.custom_name or user.display_name or user.plex_user_id
            recipient_email = user.notification_email or user.plex_email or "utilisateur@plex.local"

    if body.type == "available":
        ctx["media_type_label"] = "Série"
        ctx["media_type_label_cap"] = "La série"
    elif body.type == "failure":
        ctx["reason"] = "Le serveur Sonarr (ou Radarr) est inaccessible ou a renvoyé une erreur 500."

    rendered_subject = render_template(body.subject, ctx)
    if rendered_subject.startswith("<p>Erreur de template"):
        if body.type == "request":
            rendered_subject = f"[Plex] Nouvelle demande : {ctx['title']}"
        elif body.type == "available":
            rendered_subject = f"[Plex] Disponible : {ctx['title']}"
        else:
            rendered_subject = f"[Plex] Échec de transmission : {ctx['title']}"

    html = render_template(body.template, ctx)

    # Prepend email client headers
    settings = db.query(Settings).first()
    header_html = f"""
    <div style="background:#2a2a2a; color:#fff; font-family:sans-serif; padding:12px 20px; border-bottom:1px solid #333; margin-bottom:15px; font-size:13px;">
      <div style="margin-bottom:4px;"><strong>Objet :</strong> <span style="color:#e5a00d; font-weight:bold;">{rendered_subject}</span></div>
      <div style="margin-bottom:4px;"><strong>De :</strong> {settings.smtp_from if settings else "plex-rss@monitor.local"}</div>
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

    return Response(content=html, media_type="text/html")


class SaveTemplates(BaseModel):
    email_request_template: str
    email_available_template: str
    email_failure_template: str
    email_request_subject: Optional[str] = None
    email_available_subject: Optional[str] = None
    email_failure_subject: Optional[str] = None


@router.put("/api/email-templates")
def save_templates(body: SaveTemplates, db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    s.email_request_template = body.email_request_template
    s.email_available_template = body.email_available_template
    s.email_failure_template = body.email_failure_template
    s.email_request_subject = body.email_request_subject
    s.email_available_subject = body.email_available_subject
    s.email_failure_subject = body.email_failure_subject
    db.commit()
    return {"status": "ok"}


@router.post("/api/email-templates/reset")
def reset_templates(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    s.email_request_template = DEFAULT_REQUEST_TEMPLATE
    s.email_available_template = DEFAULT_AVAILABLE_TEMPLATE
    s.email_failure_template = DEFAULT_FAILURE_TEMPLATE
    s.email_request_subject = None
    s.email_available_subject = None
    s.email_failure_subject = None
    db.commit()
    return {"status": "ok"}


class TestSendRequest(BaseModel):
    template: str
    subject: str
    type: str = "request"
    user_id: Optional[int] = None


@router.post("/api/email-templates/test-send")
async def test_send_email(body: TestSendRequest, db: Session = Depends(get_db)):
    settings = db.query(Settings).first()
    if not settings:
        raise HTTPException(status_code=404, detail="Settings non trouvés")

    # Resolve recipient: settings.admin_notification_email or settings.smtp_from
    recipient = (settings.admin_notification_email or "").strip()
    if body.user_id:
        user = db.query(PlexUser).filter(PlexUser.id == body.user_id).first()
        if user:
            recipient = user.notification_email or user.plex_email

    if not recipient:
        recipient = settings.smtp_from

    if not recipient:
        raise HTTPException(
            status_code=400,
            detail="Aucun destinataire de test configuré (renseignez l'email de notification admin ou From SMTP)",
        )

    ctx = dict(SAMPLE_CONTEXT)
    if body.user_id:
        user = db.query(PlexUser).filter(PlexUser.id == body.user_id).first()
        if user:
            ctx["plex_user"] = user.custom_name or user.display_name or user.plex_user_id

    if body.type == "available":
        ctx["media_type_label"] = "Série"
        ctx["media_type_label_cap"] = "La série"
    elif body.type == "failure":
        ctx["reason"] = "Le serveur Sonarr (ou Radarr) est inaccessible ou a renvoyé une erreur 500."

    rendered_subject = render_template(body.subject, ctx)
    if rendered_subject.startswith("<p>Erreur de template"):
        rendered_subject = f"[Plex Test] {body.type} : {ctx['title']}"
    else:
        rendered_subject = f"[Test] {rendered_subject}"

    html = render_template(body.template, ctx)

    try:
        await smtp_send(settings, recipient, rendered_subject, html)
        return {"status": "ok", "message": f"Email de test envoyé avec succès à {recipient}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur d'envoi SMTP : {str(e)}")
