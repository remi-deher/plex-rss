from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import PlexUser, Settings
import json

from ..services.email_service import (
    DEFAULT_AVAILABLE_TEMPLATE,
    DEFAULT_AVAILABLE_VF_TEMPLATE,
    DEFAULT_AVAILABLE_VO_TRACKING_TEMPLATE,
    DEFAULT_FAILURE_TEMPLATE,
    DEFAULT_LANGUAGE_EPISODE_TEMPLATE,
    DEFAULT_LANGUAGE_SEASON_COMPLETE_TEMPLATE,
    DEFAULT_LANGUAGE_SEASON_START_TEMPLATE,
    DEFAULT_LANGUAGE_SERIES_COMPLETE_TEMPLATE,
    DEFAULT_REQUEST_TEMPLATE,
    DEFAULT_VF_AVAILABLE_TEMPLATE,
    add_email_footer,
    render_subject,
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
   "language_reason": "VF saison 1 complete",
   "language": "VF",
   "language_lower": "vf",
   "language_milestone_type": "season_complete",
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
    elif body.type in ("available_vf", "available_vo_tracking", "vf_upgrade"):
        ctx["media_type_label"] = "Film"
        ctx["media_type_label_cap"] = "Le film"
        ctx["language_reason"] = "VF film complet"
        ctx["language"] = "VF"
        ctx["language_lower"] = "vf"
    elif body.type.startswith("language_"):
        ctx["media_type_label"] = "Série"
        ctx["media_type_label_cap"] = "La série"
        ctx["language"] = "VF"
        ctx["language_lower"] = "vf"
        if body.type == "language_episode":
            ctx["language_reason"] = "VF S01E02"
            ctx["language_milestone_type"] = "episode"
        elif body.type == "language_season_start":
            ctx["language_reason"] = "VF saison 1 demarree"
            ctx["language_milestone_type"] = "season_start"
        elif body.type == "language_season_complete":
            ctx["language_reason"] = "VF saison 1 complete"
            ctx["language_milestone_type"] = "season_complete"
        elif body.type == "language_series_complete":
            ctx["language_reason"] = "VF serie complete"
            ctx["language_milestone_type"] = "series_complete"
    elif body.type == "failure":
        ctx["reason"] = "Le serveur Sonarr (ou Radarr) est inaccessible ou a renvoyé une erreur 500."

    subject_fallbacks = {
        "request": f"[Plexarr] Nouvelle demande : {ctx['title']}",
        "available": f"[Plexarr] {ctx['title']} est disponible sur Plex !",
        "available_vf": f"[Plexarr] {ctx['title']} est disponible sur Plex en VF !",
        "available_vo_tracking": f"[Plexarr] {ctx['title']} est disponible sur Plex en VO !",
        "vf_upgrade": f"[Plexarr] {ctx['title']} est désormais disponible sur Plex en VF !",
        "language_episode": f"[Plexarr] {ctx['title']} : nouvel épisode en {ctx.get('language', 'VF')} sur Plex !",
        "language_season_start": f"[Plexarr] {ctx['title']} : saison démarrée en {ctx.get('language', 'VF')} sur Plex !",
        "language_season_complete": f"[Plexarr] {ctx['title']} : saison complète en {ctx.get('language', 'VF')} sur Plex !",
        "language_series_complete": f"[Plexarr] {ctx['title']} est entièrement disponible en {ctx.get('language', 'VF')} sur Plex !",
    }
    rendered_subject = render_subject(
        body.subject, ctx, fallback=subject_fallbacks.get(body.type, f"[Plexarr] Échec de transmission : {ctx['title']}")
    )

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

    return Response(content=add_email_footer(html), media_type="text/html")


class SaveTemplates(BaseModel):
    email_request_template: str
    email_available_template: str
    email_failure_template: str
    email_available_vf_template: str
    email_available_vo_tracking_template: str
    email_vf_upgrade_template: str
    email_language_episode_template: str
    email_language_season_start_template: str
    email_language_season_complete_template: str
    email_language_series_complete_template: str
    email_request_subject: Optional[str] = None
    email_available_subject: Optional[str] = None
    email_failure_subject: Optional[str] = None
    email_available_vf_subject: Optional[str] = None
    email_available_vo_tracking_subject: Optional[str] = None
    email_vf_upgrade_subject: Optional[str] = None
    email_language_episode_subject: Optional[str] = None
    email_language_season_start_subject: Optional[str] = None
    email_language_season_complete_subject: Optional[str] = None
    email_language_series_complete_subject: Optional[str] = None


TEMPLATE_FIELDS = [
    "email_request_template",
    "email_available_template",
    "email_failure_template",
    "email_available_vf_template",
    "email_available_vo_tracking_template",
    "email_vf_upgrade_template",
    "email_language_episode_template",
    "email_language_season_start_template",
    "email_language_season_complete_template",
    "email_language_series_complete_template",
    "email_request_subject",
    "email_available_subject",
    "email_failure_subject",
    "email_available_vf_subject",
    "email_available_vo_tracking_subject",
    "email_vf_upgrade_subject",
    "email_language_episode_subject",
    "email_language_season_start_subject",
    "email_language_season_complete_subject",
    "email_language_series_complete_subject",
]


@router.put("/api/email-templates")
def save_templates(body: SaveTemplates, db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    s.email_templates_backup = json.dumps({field: getattr(s, field) for field in TEMPLATE_FIELDS})
    s.email_request_template = body.email_request_template
    s.email_available_template = body.email_available_template
    s.email_failure_template = body.email_failure_template
    s.email_available_vf_template = body.email_available_vf_template
    s.email_available_vo_tracking_template = body.email_available_vo_tracking_template
    s.email_vf_upgrade_template = body.email_vf_upgrade_template
    s.email_language_episode_template = body.email_language_episode_template
    s.email_language_season_start_template = body.email_language_season_start_template
    s.email_language_season_complete_template = body.email_language_season_complete_template
    s.email_language_series_complete_template = body.email_language_series_complete_template
    s.email_request_subject = body.email_request_subject
    s.email_available_subject = body.email_available_subject
    s.email_failure_subject = body.email_failure_subject
    s.email_available_vf_subject = body.email_available_vf_subject
    s.email_available_vo_tracking_subject = body.email_available_vo_tracking_subject
    s.email_vf_upgrade_subject = body.email_vf_upgrade_subject
    s.email_language_episode_subject = body.email_language_episode_subject
    s.email_language_season_start_subject = body.email_language_season_start_subject
    s.email_language_season_complete_subject = body.email_language_season_complete_subject
    s.email_language_series_complete_subject = body.email_language_series_complete_subject
    db.commit()
    return {"status": "ok"}


@router.post("/api/email-templates/restore-previous")
def restore_previous_templates(db: Session = Depends(get_db)):
    """Restaure les templates/sujets tels qu'ils étaient juste avant la dernière sauvegarde (undo à un niveau)."""
    s = db.query(Settings).first()
    if not s.email_templates_backup:
        raise HTTPException(status_code=404, detail="Aucune sauvegarde précédente disponible")
    backup = json.loads(s.email_templates_backup)
    for field in TEMPLATE_FIELDS:
        setattr(s, field, backup.get(field))
    s.email_templates_backup = None
    db.commit()
    return {"status": "ok"}


@router.post("/api/email-templates/reset")
def reset_templates(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    s.email_templates_backup = json.dumps({field: getattr(s, field) for field in TEMPLATE_FIELDS})
    s.email_request_template = DEFAULT_REQUEST_TEMPLATE
    s.email_available_template = DEFAULT_AVAILABLE_TEMPLATE
    s.email_failure_template = DEFAULT_FAILURE_TEMPLATE
    s.email_available_vf_template = DEFAULT_AVAILABLE_VF_TEMPLATE
    s.email_available_vo_tracking_template = DEFAULT_AVAILABLE_VO_TRACKING_TEMPLATE
    s.email_vf_upgrade_template = DEFAULT_VF_AVAILABLE_TEMPLATE
    s.email_language_episode_template = DEFAULT_LANGUAGE_EPISODE_TEMPLATE
    s.email_language_season_start_template = DEFAULT_LANGUAGE_SEASON_START_TEMPLATE
    s.email_language_season_complete_template = DEFAULT_LANGUAGE_SEASON_COMPLETE_TEMPLATE
    s.email_language_series_complete_template = DEFAULT_LANGUAGE_SERIES_COMPLETE_TEMPLATE
    s.email_request_subject = None
    s.email_available_subject = None
    s.email_failure_subject = None
    s.email_available_vf_subject = None
    s.email_available_vo_tracking_subject = None
    s.email_vf_upgrade_subject = None
    s.email_language_episode_subject = None
    s.email_language_season_start_subject = None
    s.email_language_season_complete_subject = None
    s.email_language_series_complete_subject = None
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

    if body.type in ("available_vf", "available_vo_tracking", "vf_upgrade") and "language_reason" not in ctx:
        ctx["media_type_label"] = "Film"
        ctx["media_type_label_cap"] = "Le film"
        ctx["language_reason"] = "VF film complet"

    fallback_subject = f"[Plex Test] {body.type} : {ctx['title']}"
    rendered_subject = render_subject(body.subject, ctx, fallback=fallback_subject)
    rendered_subject = fallback_subject if rendered_subject == fallback_subject else f"[Test] {rendered_subject}"

    html = render_template(body.template, ctx)

    try:
        await smtp_send(settings, recipient, rendered_subject, html)
        return {"status": "ok", "message": f"Email de test envoyé avec succès à {recipient}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur d'envoi SMTP : {str(e)}")
