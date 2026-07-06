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
from ..models import ArrInstance, LibraryItem, MediaRequest, PlexUser, RequestStatus, Settings
from ..services.email_service import DEFAULT_AVAILABLE_TEMPLATE, DEFAULT_FAILURE_TEMPLATE, DEFAULT_REQUEST_TEMPLATE
from ..utils import identity_keys as _identity_keys

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
    """Retourne {plex_user_id: nom lisible} pour tous les utilisateurs connus.

    Utilisé pour résoudre les IDs hex en noms lisibles dans les templates.
    Priorité : nom d'usage (custom_name) → display_name → plex_user_id.
    """
    return {u.plex_user_id: (u.custom_name or u.display_name or u.plex_user_id) for u in db.query(PlexUser).all()}


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
    source: str = None,
    vf: str = None,
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
        "available_date": MediaRequest.available_at,
        "status": MediaRequest.status,
        "type": MediaRequest.media_type,
    }.get(sort, MediaRequest.requested_at)

    sort_fn = asc if order == "asc" else sqldesc
    q = db.query(MediaRequest).order_by(sort_fn(sort_col))

    if user:
        q = q.filter(MediaRequest.plex_user_id == user)
    if search:
        q = q.filter(MediaRequest.title.ilike(f"%{search}%"))
    if source:
        q = q.filter(MediaRequest.source == source)

    # Compteurs globaux (avant filtre statut/type et pagination, après filtre user/search/source)
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
    # Filtre VFF (uniquement pertinent sur les médias disponibles)
    if vf == "vf":
        q = q.filter(MediaRequest.has_vf.is_(True))
    elif vf == "vo":
        q = q.filter(MediaRequest.has_vf.is_(False))
    elif vf == "unchecked":
        q = q.filter(MediaRequest.status == RequestStatus.available, MediaRequest.has_vf.is_(None))

    all_filtered = q.all()
    total = len(all_filtered)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    requests_page_data = all_filtered[(page - 1) * per_page : page * per_page]

    # Extraire les sources uniques pour le filtre
    distinct_sources = [r[0] for r in db.query(MediaRequest.source).distinct().all() if r[0]]

    settings = db.query(Settings).first()
    return templates.TemplateResponse(
        request,
        "requests.html",
        {
            "requests": requests_page_data,
            "users_map": build_users_map(db),
            "users_obj_map": {u.plex_user_id: u for u in db.query(PlexUser).all()},
            "all_users": db.query(PlexUser).order_by(PlexUser.display_name).all(),
            "sources": distinct_sources,
            "active_user": user,
            "active_search": search or "",
            "active_status": status or "",
            "active_type": type or "",
            "active_source": source or "",
            "active_vf": vf or "",
            "vff_enabled": bool(settings and settings.vff_enabled),
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


@router.get("/library", response_class=HTMLResponse)
def library_page(
    request: Request,
    type: str = None,
    vf: str = None,
    _: None = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Bibliothèque : union des médias présents dans Plex (library_items) et des
    demandes non encore en bibliothèque, avec état VF/VFF. Onglets Films / Séries."""
    settings = db.query(Settings).first()

    lib_q = db.query(LibraryItem)
    req_q = db.query(MediaRequest)
    if type in ("movie", "show"):
        lib_q = lib_q.filter(LibraryItem.media_type == type)
        req_q = req_q.filter(MediaRequest.media_type == type)

    users_map = build_users_map(db)
    index: dict = {}
    items: list = []

    # 1. Éléments de bibliothèque (base : présents dans Plex)
    for li in lib_q.all():
        vm = {
            "kind": "library",
            "ref_id": li.id,
            "in_library": True,
            "title": li.title,
            "year": li.year,
            "media_type": li.media_type,
            "poster_url": li.poster_url,
            "has_vf": li.has_vf,
            "arr_slug": li.arr_slug,
            "arr_id": li.arr_id,
            "plex_guid": li.plex_guid,
            "request_status": None,
            "requested_by": None,
            "sort_at": li.added_at,
        }
        items.append(vm)
        for k in _identity_keys(li):
            index.setdefault(k, vm)

    # 2. Demandes : rattachées à un élément existant, sinon ajoutées comme « demandé »
    for r in req_q.all():
        matched = None
        for k in _identity_keys(r):
            if k in index:
                matched = index[k]
                break
        if matched:
            matched["request_status"] = r.status.value if hasattr(r.status, "value") else str(r.status)
            matched["requested_by"] = users_map.get(r.plex_user_id, r.plex_user or r.plex_user_id)
        else:
            vm = {
                "kind": "request",
                "ref_id": r.id,
                "in_library": False,
                "title": r.title,
                "year": r.year,
                "media_type": r.media_type,
                "poster_url": r.poster_url,
                "has_vf": r.has_vf,
                "arr_slug": r.arr_slug,
                "arr_id": r.arr_id,
                "plex_guid": r.plex_guid,
                "request_status": r.status.value if hasattr(r.status, "value") else str(r.status),
                "requested_by": users_map.get(r.plex_user_id, r.plex_user or r.plex_user_id),
                "sort_at": r.requested_at,
            }
            items.append(vm)
            for k in _identity_keys(r):
                index.setdefault(k, vm)

    from datetime import datetime as _dt

    items.sort(key=lambda v: v["sort_at"] or _dt.min, reverse=True)

    counts = {
        "vf": sum(1 for v in items if v["in_library"] and v["has_vf"] is True),
        "vo": sum(1 for v in items if v["in_library"] and v["has_vf"] is False),
        "unchecked": sum(1 for v in items if v["in_library"] and v["has_vf"] is None),
        "requested": sum(1 for v in items if not v["in_library"]),
    }

    # Filtre VF/VO/non analysé/demandé (counts calculés avant filtrage → totaux)
    if vf == "vf":
        items = [v for v in items if v["in_library"] and v["has_vf"] is True]
    elif vf == "vo":
        items = [v for v in items if v["in_library"] and v["has_vf"] is False]
    elif vf == "unchecked":
        items = [v for v in items if v["in_library"] and v["has_vf"] is None]
    elif vf == "requested":
        items = [v for v in items if not v["in_library"]]

    return templates.TemplateResponse(
        request,
        "library.html",
        {
            "page": "library",
            "settings": settings,
            "items": items,
            "active_type": type or "movie",
            "active_vf": vf or "",
            "counts": counts,
            "vff_enabled": bool(settings and settings.vff_enabled),
            "sonarr_url": (settings.sonarr_url or "").rstrip("/") if settings else "",
            "radarr_url": (settings.radarr_url or "").rstrip("/") if settings else "",
        },
    )


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request, _: None = Depends(require_auth), db: Session = Depends(get_db)):
    """Page des utilisateurs avec compteurs de demandes par statut."""
    users = db.query(PlexUser).all()

    # Calcul en Python pour éviter plusieurs sous-requêtes SQL
    counts_map: dict[str, dict] = {}
    for r in db.query(MediaRequest.plex_user_id, MediaRequest.status, MediaRequest.requested_at).all():
        uid = r.plex_user_id
        if uid not in counts_map:
            counts_map[uid] = {"total": 0, "available": 0, "failed": 0, "sent": 0, "last_requested_at": None}
        counts_map[uid]["total"] += 1
        if r.status == "available":
            counts_map[uid]["available"] += 1
        elif r.status == "failed":
            counts_map[uid]["failed"] += 1
        elif r.status == "sent_to_arr":
            counts_map[uid]["sent"] += 1
        if r.requested_at and (
            counts_map[uid]["last_requested_at"] is None or r.requested_at > counts_map[uid]["last_requested_at"]
        ):
            counts_map[uid]["last_requested_at"] = r.requested_at

    settings = db.query(Settings).first()
    seer_enabled = bool(settings and settings.seer_enabled and settings.seer_url and settings.seer_api_key)

    instances = db.query(ArrInstance).filter(ArrInstance.enabled).all()
    sonarr_instances = [i for i in instances if i.arr_type == "sonarr"]
    radarr_instances = [i for i in instances if i.arr_type == "radarr"]

    return templates.TemplateResponse(
        request,
        "users.html",
        {
            "users": users,
            "counts_map": counts_map,
            "seer_enabled": seer_enabled,
            "sonarr_instances": sonarr_instances,
            "radarr_instances": radarr_instances,
        },
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
def user_detail_page(user_id: int, request: Request, _: None = Depends(require_auth), db: Session = Depends(get_db)):
    """Page de détail d'un utilisateur : stats et historique complet de ses demandes."""
    user = db.get(PlexUser, user_id)
    if not user:
        return RedirectResponse("/users", status_code=302)

    user_requests = (
        db.query(MediaRequest)
        .filter(MediaRequest.plex_user_id == user.plex_user_id)
        .order_by(MediaRequest.requested_at.desc())
        .all()
    )
    stats = {
        "total": len(user_requests),
        "available": sum(1 for r in user_requests if r.status == RequestStatus.available),
        "sent": sum(1 for r in user_requests if r.status == RequestStatus.sent_to_arr),
        "failed": sum(1 for r in user_requests if r.status == RequestStatus.failed),
        "pending": sum(1 for r in user_requests if r.status == RequestStatus.pending),
    }
    return templates.TemplateResponse(
        request,
        "user_detail.html",
        {
            "user": user,
            "requests": user_requests,
            "stats": stats,
        },
    )


@router.get("/downloads", response_class=HTMLResponse)
def downloads_page(request: Request, _: None = Depends(require_auth)):
    """Page Téléchargements : file d'attente *arr unifiée (auto-rafraîchie)."""
    return templates.TemplateResponse(request, "downloads.html", {"page": "downloads"})


@router.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request, _: None = Depends(require_auth)):
    """Page des logs applicatifs en temps réel."""
    return templates.TemplateResponse(request, "logs.html")


@router.get("/search")
def search_page():
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/requests", status_code=301)


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
            "request_template": (s.email_request_template if s else None) or DEFAULT_REQUEST_TEMPLATE,
            "available_template": (s.email_available_template if s else None) or DEFAULT_AVAILABLE_TEMPLATE,
            "failure_template": (s.email_failure_template if s else None) or DEFAULT_FAILURE_TEMPLATE,
            "request_subject": (s.email_request_subject if s else None) or "",
            "available_subject": (s.email_available_subject if s else None) or "",
            "failure_subject": (s.email_failure_subject if s else None) or "",
            "template_variables": [
                ("{{ title }}", "Titre du film ou de la série"),
                ("{{ year }}", "Année de sortie"),
                ("{{ poster_url }}", "URL de l'affiche"),
                ("{{ plex_user }}", "Nom de l'utilisateur"),
                ("{{ media_type_label }}", "Film ou Série"),
                ("{{ media_type_label_cap }}", "Le film / La série"),
                ("{{ overview }}", "Synopsis"),
                ("{{ genres }}", "Genres (ex: Action, Drame)"),
                ("{{ reason }}", "Raison de l'échec (email d'échec uniquement)"),
            ],
        },
    )
