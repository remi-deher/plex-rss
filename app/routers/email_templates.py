from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Settings
from ..services.email_service import (
    render_template, DEFAULT_REQUEST_TEMPLATE, DEFAULT_AVAILABLE_TEMPLATE
)


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
    return templates.TemplateResponse("email_templates.html", {
        "request": request,
        "page": "settings",
        "request_template": s.email_request_template or DEFAULT_REQUEST_TEMPLATE,
        "available_template": s.email_available_template or DEFAULT_AVAILABLE_TEMPLATE,
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
    })


class PreviewRequest(BaseModel):
    template: str
    type: str = "request"


@router.post("/api/email-preview")
def preview_email(body: PreviewRequest):
    ctx = dict(SAMPLE_CONTEXT)
    if body.type == "available":
        ctx["media_type_label"] = "Série"
        ctx["media_type_label_cap"] = "La série"
    html = render_template(body.template, ctx)
    return Response(content=html, media_type="text/html")


class SaveTemplates(BaseModel):
    email_request_template: str
    email_available_template: str


@router.put("/api/email-templates")
def save_templates(body: SaveTemplates, db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    s.email_request_template = body.email_request_template
    s.email_available_template = body.email_available_template
    db.commit()
    return {"status": "ok"}


@router.post("/api/email-templates/reset")
def reset_templates(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    s.email_request_template = DEFAULT_REQUEST_TEMPLATE
    s.email_available_template = DEFAULT_AVAILABLE_TEMPLATE
    db.commit()
    return {"status": "ok"}
