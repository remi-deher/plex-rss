import re

with open("app/routers/email_templates.py", "r", encoding="utf-8") as f:
    original = f.read()

new_content = """import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_settings_or_404, require_admin
from ..models import PlexUser, Settings, MediaRequest
from ..services.email_service import (
    DEFAULT_AVAILABLE_TEMPLATE,
    DEFAULT_UPGRADE_TEMPLATE,
    DEFAULT_FAILURE_TEMPLATE,
    DEFAULT_REQUEST_TEMPLATE,
    render_subject,
    render_template,
    _build_tags,
    _build_jinja_ctx,
)
from ..services.email_service import _send as smtp_send
from ..services.notification_catalog import get_event, template_fields

router = APIRouter(tags=["email-templates"], dependencies=[Depends(require_admin)])


@router.get("/settings/email-templates")
def email_templates_redirect():
    return RedirectResponse("/templates", status_code=301)


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


def _create_dummy_request() -> MediaRequest:
    req = MediaRequest(
        title="Breaking Bad",
        year=2008,
        poster_url="https://image.tmdb.org/t/p/w300/ggFHVNu6YYI5L9pCfOacjizRGt.jpg",
        plex_user="Jean Dupont",
        media_type="show",
        overview="Un professeur de chimie atteint d'un cancer du poumon se lance dans la fabrication et la vente de méthamphétamine afin de subvenir aux besoins de sa famille.",
        genres="Crime, Drame, Thriller"
    )
    return req

class PreviewRequest(BaseModel):
    template: str
    subject: str
    type: str = "request"
    user_id: Optional[int] = None
    preview_variant: Optional[str] = None


@router.post("/api/email-preview")
def preview_email(body: PreviewRequest, db: Session = Depends(get_db)):
    event_def = get_event(body.type)
    req = _create_dummy_request()
    display_name = "Jean Dupont"
    
    scope = "movie"
    language = None
    is_upgrade = False
    season_number = None
    episode_number = None

    if body.type == "available" and body.preview_variant:
        if body.preview_variant == "movie_generic":
            scope, language, is_upgrade = "movie", None, False
        elif body.preview_variant == "movie_vo":
            scope, language, is_upgrade = "movie", "vo", False
        elif body.preview_variant == "movie_vf":
            scope, language, is_upgrade = "movie", "vf", False
        elif body.preview_variant == "episode":
            scope, language, is_upgrade, season_number, episode_number = "episode", None, False, 2, 1
        elif body.preview_variant == "season_complete":
            scope, language, is_upgrade, season_number = "season_complete", None, False, 2
        elif body.preview_variant == "upgrade_vf":
            scope, language, is_upgrade = "movie", "vf", True

    settings = db.query(Settings).first()
    recipient_email = "jean.dupont@plex.local"
    if body.user_id:
        user = db.query(PlexUser).filter(PlexUser.id == body.user_id).first()
        if user:
            display_name = user.custom_name or user.display_name or user.plex_user_id
            recipient_email = user.notification_email or user.plex_email or "utilisateur@plex.local"

    tags = _build_tags(req, display_name=display_name, scope=scope, language=language, is_upgrade=is_upgrade, season_number=season_number, episode_number=episode_number, reason="Impossible de contacter Sonarr." if body.type == "failure" else "")
    
    jinja_ctx = _build_jinja_ctx(req, display_name=display_name)

    if body.type == "request":
        jinja_ctx.update({
            "_accent_color": "#e5a00d",
            "_badge_text": "Nouvelle demande",
            "_headline_text": "Demande enregistrée",
            "_show_synopsis": True,
        })
    elif body.type == "failure":
        jinja_ctx.update({
            "_accent_color": "#dc3545",
            "_badge_text": "Action requise",
            "_headline_text": "Demande non transmise",
            "_show_synopsis": False,
        })
    elif body.type == "available":
        if is_upgrade:
            jinja_ctx.update({
                "_accent_color": "#1db954",
                "_badge_text": "Mise à jour VF",
                "_headline_text": "VF disponible",
                "_show_synopsis": True,
            })
        else:
            jinja_ctx.update({
                "_accent_color": "#0d6efd" if language == "vo" else "#1db954",
                "_badge_text": "Disponible en VO" if language == "vo" else "Disponible",
                "_headline_text": "Média disponible",
                "_show_synopsis": True,
            })

    generic_fallback = f"[Plexarr] {event_def.label} : {req.title}"
    fallback_subject = (
        render_subject(event_def.default_subject, tags, fallback=generic_fallback)
        if event_def.default_subject
        else generic_fallback
    )
    rendered_subject = render_subject(body.subject, tags, fallback=fallback_subject)

    html = render_template(body.template, tags, jinja_ctx)

    header_html = f\"\"\"
    <div style="background:#2a2a2a; color:#fff; font-family:sans-serif; padding:12px 20px; border-bottom:1px solid #333; margin-bottom:15px; font-size:13px;">
      <div style="margin-bottom:4px;"><strong>Objet :</strong> <span style="color:#e5a00d; font-weight:bold;">{rendered_subject}</span></div>
      <div style="margin-bottom:4px;"><strong>De :</strong> {settings.smtp_from if settings else "plex-rss@monitor.local"}</div>
      <div><strong>À :</strong> {recipient_email}</div>
    </div>
    \"\"\"

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
    email_upgrade_template: Optional[str] = None
    email_failure_template: str
    email_request_subject: Optional[str] = None
    email_available_subject: Optional[str] = None
    email_upgrade_subject: Optional[str] = None
    email_failure_subject: Optional[str] = None


TEMPLATE_FIELDS = [
    "email_request_template",
    "email_available_template",
    "email_upgrade_template",
    "email_failure_template",
    "email_request_subject",
    "email_available_subject",
    "email_upgrade_subject",
    "email_failure_subject",
]


@router.put("/api/email-templates")
def save_templates(body: SaveTemplates, db: Session = Depends(get_db), s: Settings = Depends(get_settings_or_404)):
    s.email_templates_backup = json.dumps({field: getattr(s, field) for field in TEMPLATE_FIELDS})
    for field in TEMPLATE_FIELDS:
        setattr(s, field, getattr(body, field, None))
    db.commit()
    return {"status": "ok"}


@router.post("/api/email-templates/restore-previous")
def restore_previous_templates(db: Session = Depends(get_db), s: Settings = Depends(get_settings_or_404)):
    if not s.email_templates_backup:
        raise HTTPException(status_code=404, detail="Aucune sauvegarde précédente disponible")
    backup = json.loads(s.email_templates_backup)
    for field in TEMPLATE_FIELDS:
        setattr(s, field, backup.get(field))
    s.email_templates_backup = None
    db.commit()
    return {"status": "ok"}


@router.post("/api/email-templates/reset")
def reset_templates(db: Session = Depends(get_db), s: Settings = Depends(get_settings_or_404)):
    s.email_templates_backup = json.dumps({field: getattr(s, field) for field in TEMPLATE_FIELDS})
    s.email_request_template = DEFAULT_REQUEST_TEMPLATE
    s.email_available_template = DEFAULT_AVAILABLE_TEMPLATE
    s.email_upgrade_template = DEFAULT_UPGRADE_TEMPLATE
    s.email_failure_template = DEFAULT_FAILURE_TEMPLATE
    s.email_request_subject = None
    s.email_available_subject = None
    s.email_upgrade_subject = None
    s.email_failure_subject = None
    db.commit()
    return {"status": "ok"}


class TestSendRequest(BaseModel):
    template: str
    subject: str
    type: str = "request"
    user_id: Optional[int] = None
    preview_variant: Optional[str] = None


@router.post("/api/email-templates/test-send")
async def test_send_email(
    body: TestSendRequest, db: Session = Depends(get_db), settings: Settings = Depends(get_settings_or_404)
):
    recipient = (settings.admin_notification_email or "").strip()
    display_name = "Jean Dupont"
    if body.user_id:
        user = db.query(PlexUser).filter(PlexUser.id == body.user_id).first()
        if user:
            recipient = user.notification_email or user.plex_email
            display_name = user.custom_name or user.display_name or user.plex_user_id

    if not recipient:
        recipient = settings.smtp_from

    if not recipient:
        raise HTTPException(
            status_code=400,
            detail="Aucun destinataire de test configuré",
        )

    event_def = get_event(body.type)
    req = _create_dummy_request()
    
    scope = "movie"
    language = None
    is_upgrade = False
    season_number = None
    episode_number = None

    if body.type == "available" and body.preview_variant:
        if body.preview_variant == "movie_generic":
            scope, language, is_upgrade = "movie", None, False
        elif body.preview_variant == "movie_vo":
            scope, language, is_upgrade = "movie", "vo", False
        elif body.preview_variant == "movie_vf":
            scope, language, is_upgrade = "movie", "vf", False
        elif body.preview_variant == "episode":
            scope, language, is_upgrade, season_number, episode_number = "episode", None, False, 2, 1
        elif body.preview_variant == "season_complete":
            scope, language, is_upgrade, season_number = "season_complete", None, False, 2
        elif body.preview_variant == "upgrade_vf":
            scope, language, is_upgrade = "movie", "vf", True

    tags = _build_tags(req, display_name=display_name, scope=scope, language=language, is_upgrade=is_upgrade, season_number=season_number, episode_number=episode_number, reason="Impossible de contacter Sonarr." if body.type == "failure" else "")
    
    jinja_ctx = _build_jinja_ctx(req, display_name=display_name)

    if body.type == "request":
        jinja_ctx.update({
            "_accent_color": "#e5a00d",
            "_badge_text": "Nouvelle demande",
            "_headline_text": "Demande enregistrée",
            "_show_synopsis": True,
        })
    elif body.type == "failure":
        jinja_ctx.update({
            "_accent_color": "#dc3545",
            "_badge_text": "Action requise",
            "_headline_text": "Demande non transmise",
            "_show_synopsis": False,
        })
    elif body.type == "available":
        if is_upgrade:
            jinja_ctx.update({
                "_accent_color": "#1db954",
                "_badge_text": "Mise à jour VF",
                "_headline_text": "VF disponible",
                "_show_synopsis": True,
            })
        else:
            jinja_ctx.update({
                "_accent_color": "#0d6efd" if language == "vo" else "#1db954",
                "_badge_text": "Disponible en VO" if language == "vo" else "Disponible",
                "_headline_text": "Média disponible",
                "_show_synopsis": True,
            })

    generic_fallback = f"[Plexarr] {event_def.label} : {req.title}"
    fallback_subject = (
        render_subject(event_def.default_subject, tags, fallback=generic_fallback)
        if event_def.default_subject
        else generic_fallback
    )
    rendered_subject = render_subject(body.subject, tags, fallback=fallback_subject)

    html = render_template(body.template, tags, jinja_ctx)

    try:
        from ..services.email_service import _send
        await _send(settings, recipient, rendered_subject, html)
        return {"status": "ok", "message": f"Email envoyé avec succès à {recipient}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
"""

with open("app/routers/email_templates.py", "w", encoding="utf-8") as f:
    f.write(new_content)
