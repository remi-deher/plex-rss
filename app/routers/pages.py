"""
Router des pages HTML (rendu côté serveur via Jinja2).

Chaque route retourne un HTMLResponse en rendant le template correspondant.
Les données de contexte sont minimales : elles servent à l'affichage initial ;
les mises à jour dynamiques passent par les endpoints API (api.py).
"""

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import asc
from sqlalchemy import desc as sqldesc
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import MediaRequest, PlexUser, RequestStatus, Settings

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["fromjson"] = lambda s: json.loads(s) if s else []


class RedirectException(Exception):
    def __init__(self, path: str):
        self.path = path


def require_auth(request: Request):
    """Dépendance : redirige vers /login si l'utilisateur n'est pas authentifié."""
    if not request.session.get("authenticated"):
        from urllib.parse import quote

        path = quote(str(request.url.path), safe="/")
        raise RedirectException(f"/login?next={path}")


def build_users_map(db: Session) -> dict:
    """Retourne {plex_user_id: display_name} pour tous les utilisateurs connus.

    Utilisé pour résoudre les IDs hex en noms lisibles dans les templates.
    """
    return {u.plex_user_id: (u.display_name or u.plex_user_id) for u in db.query(PlexUser).all()}


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, _: None = Depends(require_auth), db: Session = Depends(get_db)):
    """Page principale : stats globales + 10 demandes récentes + graphique timeline (JS)."""
    settings = db.query(Settings).first()
    recent = db.query(MediaRequest).order_by(MediaRequest.requested_at.desc()).limit(10).all()
    all_requests = db.query(MediaRequest).all()
    stats = {
        "total": len(all_requests),
        "sent": sum(1 for r in all_requests if r.status == RequestStatus.sent_to_arr),
        "available": sum(1 for r in all_requests if r.status == RequestStatus.available),
        "failed": sum(1 for r in all_requests if r.status == RequestStatus.failed),
    }
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "settings": settings,
            "recent_requests": recent,
            "stats": stats,
            "users_map": build_users_map(db),
        },
    )


@router.get("/requests", response_class=HTMLResponse)
def requests_page(
    request: Request,
    user: str = None,
    search: str = None,
    status: str = None,
    type: str = None,
    page: int = 1,
    per_page: int = 50,
    sort: str = "date",
    order: str = "desc",
    _: None = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Page des demandes avec tri, recherche et pagination côté serveur."""
    sort_col = {
        "title": MediaRequest.title,
        "date": MediaRequest.requested_at,
        "status": MediaRequest.status,
        "type": MediaRequest.media_type,
    }.get(sort, MediaRequest.requested_at)

    sort_fn = asc if order == "asc" else sqldesc
    q = db.query(MediaRequest).order_by(sort_fn(sort_col))

    if user:
        q = q.filter(MediaRequest.plex_user_id == user)
    if search:
        q = q.filter(MediaRequest.title.ilike(f"%{search}%"))

    # Compteurs globaux (avant filtre statut/type et pagination, après filtre user/search)
    all_unfiltered_status = q.all()
    status_counts = {"failed": 0, "pending": 0, "sent_to_arr": 0, "available": 0}
    for r in all_unfiltered_status:
        s = r.status.value if hasattr(r.status, "value") else str(r.status)
        if s in status_counts:
            status_counts[s] += 1

    # Appliquer les filtres de statut et de type de média
    if status:
        q = q.filter(MediaRequest.status == status)
    if type:
        q = q.filter(MediaRequest.media_type == type)

    all_filtered = q.all()
    total = len(all_filtered)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    requests_page_data = all_filtered[(page - 1) * per_page : page * per_page]

    settings = db.query(Settings).first()
    return templates.TemplateResponse(
        request,
        "requests.html",
        {
            "requests": requests_page_data,
            "users_map": build_users_map(db),
            "users_obj_map": {u.plex_user_id: u for u in db.query(PlexUser).all()},
            "all_users": db.query(PlexUser).order_by(PlexUser.display_name).all(),
            "active_user": user,
            "active_search": search or "",
            "active_status": status or "",
            "active_type": type or "",
            "sonarr_url": (settings.sonarr_url or "").rstrip("/") if settings else "",
            "radarr_url": (settings.radarr_url or "").rstrip("/") if settings else "",
            "seer_url": (settings.seer_url or "").rstrip("/") if settings else "",
            "current_page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "sort": sort,
            "order": order,
            "status_counts": status_counts,
        },
    )


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request, _: None = Depends(require_auth), db: Session = Depends(get_db)):
    """Page des utilisateurs avec compteurs de demandes par statut."""
    users = db.query(PlexUser).all()

    # Calcul en Python pour éviter plusieurs sous-requêtes SQL
    counts_map: dict[str, dict] = {}
    for r in db.query(MediaRequest.plex_user_id, MediaRequest.status).all():
        uid = r.plex_user_id
        if uid not in counts_map:
            counts_map[uid] = {"total": 0, "available": 0, "failed": 0, "sent": 0}
        counts_map[uid]["total"] += 1
        if r.status == "available":
            counts_map[uid]["available"] += 1
        elif r.status == "failed":
            counts_map[uid]["failed"] += 1
        elif r.status == "sent_to_arr":
            counts_map[uid]["sent"] += 1

    settings = db.query(Settings).first()
    seer_enabled = bool(settings and settings.seer_enabled and settings.seer_url and settings.seer_api_key)

    return templates.TemplateResponse(
        request,
        "users.html",
        {
            "users": users,
            "counts_map": counts_map,
            "seer_enabled": seer_enabled,
        },
    )


@router.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request, _: None = Depends(require_auth)):
    """Page des logs applicatifs en temps réel."""
    return templates.TemplateResponse(request, "logs.html")


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, _: None = Depends(require_auth), db: Session = Depends(get_db)):
    """Page de configuration globale de l'application."""
    s = db.query(Settings).first()
    base_url = str(request.base_url).rstrip("/")
    users = db.query(PlexUser).order_by(PlexUser.display_name).all()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "s": s,
            "webhook_url": f"{base_url}/webhook/plex",
            "users": users,
        },
    )
