from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import PlexUser, Settings
from ..services.email_service import DEFAULT_AVAILABLE_TEMPLATE, DEFAULT_REQUEST_TEMPLATE, render_template


def require_auth(request: Request):
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Non authentifié")


router = APIRouter(tags=["email-templates"], dependencies=[Depends(require_auth)])
templates = Jinja2Templates(directory="app/templates")


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


@router.get("/settings/email-templates", response_class=HTMLResponse)
def email_templates_page(request: Request, db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    users = db.query(PlexUser).order_by(PlexUser.display_name).all()
    return templates.TemplateResponse(
        request,
        "email_templates.html",
        {
            "page": "email-templates",
            "request_template": s.email_request_template or DEFAULT_REQUEST_TEMPLATE,
            "available_template": s.email_available_template or DEFAULT_AVAILABLE_TEMPLATE,
            "request_subject": s.email_request_subject or "",
            "available_subject": s.email_available_subject or "",
            "users": users,
            "variables": [
                ("{{ title }}", "Titre du film ou de la série"),
                ("{{ year }}", "Année de sortie"),
                ("{{ poster_url }}", "URL de l'affiche"),
                ("{{ plex_user }}", "Nom de l'utilisateur"),
                ("{{ media_type_label }}", "Film ou Série"),
                ("{{ media_type_label_cap }}", "Le film / La série"),
                ("{{ overview }}", "Synopsis"),
                ("{{ genres }}", "Genres (ex: Action, Drame)"),
            ],
        },
    )


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

    rendered_subject = render_template(body.subject, ctx)
    if rendered_subject.startswith("<p>Erreur de template"):
        rendered_subject = (
            f"[Plex] Nouvelle demande : {ctx['title']}"
            if body.type == "request"
            else f"[Plex] Disponible : {ctx['title']}"
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

    return Response(content=html, media_type="text/html")


class SaveTemplates(BaseModel):
    email_request_template: str
    email_available_template: str
    email_request_subject: Optional[str] = None
    email_available_subject: Optional[str] = None


@router.put("/api/email-templates")
def save_templates(body: SaveTemplates, db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    s.email_request_template = body.email_request_template
    s.email_available_template = body.email_available_template
    s.email_request_subject = body.email_request_subject
    s.email_available_subject = body.email_available_subject
    db.commit()
    return {"status": "ok"}


@router.post("/api/email-templates/reset")
def reset_templates(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    s.email_request_template = DEFAULT_REQUEST_TEMPLATE
    s.email_available_template = DEFAULT_AVAILABLE_TEMPLATE
    s.email_request_subject = None
    s.email_available_subject = None
    db.commit()
    return {"status": "ok"}
