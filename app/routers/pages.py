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
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ArrInstance, LibraryItem, MediaRequest, PlexUser, RequestStatus, Settings
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
)
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


def _is_admin_session(request: Request) -> bool:
    return bool(request.session.get("is_owner") or request.session.get("role") == "admin")


def require_admin(request: Request):
    """Dépendance pages : réservé aux admins. Un utilisateur 'user' est renvoyé vers
    /discover (sa page d'accueil), un visiteur non connecté vers /login."""
    if not request.session.get("authenticated"):
        from urllib.parse import quote

        path = quote(str(request.url.path), safe="/")
        raise RedirectException(f"/login?next={path}")
    if not _is_admin_session(request):
        raise RedirectException("/discover")


def build_users_map(db: Session) -> dict:
    """Retourne {plex_user_id: nom lisible} pour tous les utilisateurs connus.

    Utilisé pour résoudre les IDs hex en noms lisibles dans les templates.
    Priorité : nom d'usage (custom_name) → display_name → plex_user_id.
    """
    return {u.plex_user_id: (u.custom_name or u.display_name or u.plex_user_id) for u in db.query(PlexUser).all()}


def _status_value(req: MediaRequest) -> str:
    return req.status.value if hasattr(req.status, "value") else str(req.status)


def _request_summary(req: MediaRequest, users_map: dict[str, str]) -> dict:
    requester_ids = [req.plex_user_id] if req.plex_user_id else []
    requester_names = [users_map.get(req.plex_user_id, req.plex_user or req.plex_user_id)] if req.plex_user_id else []
    try:
        for extra in json.loads(req.extra_requesters or "[]"):
            uid = extra.get("plex_user_id")
            if uid and uid not in requester_ids:
                requester_ids.append(uid)
                requester_names.append(users_map.get(uid, extra.get("display_name") or uid))
    except Exception:
        pass
    return {
        "id": req.id,
        "title": req.title,
        "year": req.year,
        "media_type": req.media_type,
        "status": _status_value(req),
        "source": req.source,
        "plex_user_id": req.plex_user_id,
        "plex_user": users_map.get(req.plex_user_id, req.plex_user or req.plex_user_id),
        "requester_ids": requester_ids,
        "requesters": requester_names,
        "requested_by": ", ".join(requester_names),
        "requested_at": req.requested_at,
        "available_at": req.available_at,
        "request_mail_sent": req.request_mail_sent,
        "available_mail_sent": req.available_mail_sent,
        "extra_requesters": req.extra_requesters or "[]",
        "overview": req.overview,
        "arr_id": req.arr_id,
        "arr_slug": req.arr_slug,
        "arr_instance_id": req.arr_instance_id,
        "has_vf": req.has_vf,
    }


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    """Page principale : stats globales + 10 demandes récentes + graphique timeline (JS).

    Réservée aux admins ; un utilisateur 'user' est redirigé vers /discover."""
    settings = db.query(Settings).first()
    recent = db.query(MediaRequest).order_by(MediaRequest.requested_at.desc()).limit(10).all()
    pending_approval = (
        db.query(MediaRequest)
        .filter(MediaRequest.status == RequestStatus.pending_approval)
        .order_by(MediaRequest.requested_at.desc())
        .limit(10)
        .all()
    )
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
            "pending_approval": pending_approval,
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
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Page des demandes avec tri, recherche et pagination côté serveur."""
    from urllib.parse import urlencode

    params = {
        "view": "requests",
        "user": user,
        "search": search,
        "status": status,
        "type": type,
        "source": source,
        "vf": vf,
        "page": page,
        "per_page": per_page,
        "sort": sort,
        "order": order,
    }
    qs = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return RedirectResponse(f"/library?{qs}", status_code=302)

    # Compteurs globaux (avant filtre statut/type et pagination, après filtre user/search/source)
    # Appliquer les filtres de statut et de type de média
    # Filtre VFF (uniquement pertinent sur les médias disponibles)
    # Extraire les sources uniques pour le filtre


@router.get("/library", response_class=HTMLResponse)
def library_page(
    request: Request,
    type: str = None,
    vf: str = None,
    view: str = "all",
    user: str = None,
    search: str = None,
    status: str = None,
    source: str = None,
    page: int = 1,
    per_page: int = 60,
    sort: str = "date",
    order: str = "desc",
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Bibliothèque : union des médias présents dans Plex (library_items) et des
    demandes non encore en bibliothèque, avec état VF/VFF. Films et Séries sont
    deux entrées distinctes ; par défaut on affiche les Films. Seule la recherche
    globale de demandes (view=requests) reste transversale aux deux types."""
    settings = db.query(Settings).first()

    # Séparation complète Films / Séries : hors recherche globale, un type est
    # toujours actif (Films par défaut).
    if type not in ("movie", "show") and view != "requests":
        type = "movie"

    lib_q = db.query(LibraryItem)
    req_q = db.query(MediaRequest)
    if type in ("movie", "show"):
        lib_q = lib_q.filter(LibraryItem.media_type == type)
        req_q = req_q.filter(MediaRequest.media_type == type)

    users_map = build_users_map(db)
    index: dict = {}
    by_library_id: dict[int, dict] = {}
    items: list = []

    for li in lib_q.all():
        vm = {
            "kind": "library",
            "ref_id": li.id,
            "library_id": li.id,
            "in_library": True,
            "title": li.title,
            "year": li.year,
            "media_type": li.media_type,
            "poster_url": li.poster_url,
            "has_vf": li.has_vf,
            "vf_granularity": li.vf_granularity,
            "arr_slug": li.arr_slug,
            "arr_id": li.arr_id,
            "arr_instance_id": li.arr_instance_id,
            "plex_guid": li.plex_guid,
            "request_status": None,
            "requested_by": None,
            "requests": [],
            "sort_at": li.added_at,
            "available_sort_at": None,
        }
        items.append(vm)
        by_library_id[li.id] = vm
        for k in _identity_keys(li):
            index.setdefault(k, vm)

    request_rows = req_q.all()
    for r in request_rows:
        matched = by_library_id.get(r.library_item_id) if r.library_item_id else None
        if not matched:
            for k in _identity_keys(r):
                if k in index:
                    matched = index[k]
                    break

        summary = _request_summary(r, users_map)
        if matched:
            matched["request_status"] = _status_value(r)
            matched["requested_by"] = users_map.get(r.plex_user_id, r.plex_user or r.plex_user_id)
            matched["requests"].append(summary)
        else:
            vm = {
                "kind": "request",
                "ref_id": r.id,
                "library_id": None,
                "in_library": False,
                "title": r.title,
                "year": r.year,
                "media_type": r.media_type,
                "poster_url": r.poster_url,
                "has_vf": r.has_vf,
                "vf_granularity": r.vf_granularity,
                "arr_slug": r.arr_slug,
                "arr_id": r.arr_id,
                "arr_instance_id": r.arr_instance_id,
                "plex_guid": r.plex_guid,
                "request_status": _status_value(r),
                "requested_by": users_map.get(r.plex_user_id, r.plex_user or r.plex_user_id),
                "requests": [summary],
                "sort_at": r.requested_at,
                "available_sort_at": r.available_at,
            }
            items.append(vm)
            for k in _identity_keys(r):
                index.setdefault(k, vm)

    from datetime import datetime as _dt

    status_priority = {"failed": 0, "pending": 1, "sent_to_arr": 2, "available": 3}
    for vm in items:
        reqs = vm["requests"]
        vm["request_ids"] = [r["id"] for r in reqs]
        vm["primary_request_id"] = vm["request_ids"][0] if vm["request_ids"] else None
        vm["request_count"] = len(reqs)
        statuses = sorted({r["status"] for r in reqs}, key=lambda s: status_priority.get(s, 99))
        vm["request_statuses"] = statuses
        vm["request_status"] = statuses[0] if statuses else None
        # Anomalie Plex : *arr a traité la demande (statut disponible) mais le média
        # reste introuvable dans la bibliothèque Plex synchronisée (bug d'indexation Plex).
        vm["plex_anomaly"] = (not vm["in_library"]) and ("available" in statuses)
        vm["request_sources"] = sorted({r["source"] for r in reqs if r["source"]})
        names = []
        for req in reqs:
            for name in req["requesters"]:
                if name not in names:
                    names.append(name)
        vm["requested_by"] = ", ".join(names) if names else vm.get("requested_by")
        if not vm["sort_at"] and reqs:
            vm["sort_at"] = max((r["requested_at"] for r in reqs if r["requested_at"]), default=None)
        available_dates = [r["available_at"] for r in reqs if r["available_at"]]
        if available_dates:
            vm["available_sort_at"] = max(available_dates)

    counts = {
        "vf": sum(1 for v in items if v["in_library"] and v["has_vf"] is True),
        "vo": sum(1 for v in items if v["in_library"] and v["has_vf"] is False),
        "season_partial": sum(
            1 for v in items if v["in_library"] and v["has_vf"] is False and v["vf_granularity"] == "season_partial"
        ),
        "episode_partial": sum(
            1 for v in items if v["in_library"] and v["has_vf"] is False and v["vf_granularity"] == "episode_partial"
        ),
        "unchecked": sum(1 for v in items if v["in_library"] and v["has_vf"] is None),
        "requested": sum(1 for v in items if not v["in_library"]),
        "plex_anomaly": sum(1 for v in items if v["plex_anomaly"]),
        "requests": sum(1 for v in items if v["request_ids"]),
        "total": len(items),
    }
    status_counts = {"failed": 0, "pending": 0, "sent_to_arr": 0, "available": 0}
    for r in request_rows:
        s = _status_value(r)
        if s in status_counts:
            status_counts[s] += 1

    def _matches_request_filter(vm: dict, predicate) -> bool:
        return any(predicate(r) for r in vm["requests"])

    if view == "requests":
        items = [v for v in items if v["request_ids"]]
    if search:
        sq = search.lower()
        items = [v for v in items if sq in (v["title"] or "").lower()]
    if user:
        items = [v for v in items if _matches_request_filter(v, lambda r: user in r["requester_ids"])]
    if status:
        items = [v for v in items if _matches_request_filter(v, lambda r: r["status"] == status)]
    if source:
        items = [v for v in items if _matches_request_filter(v, lambda r: r["source"] == source)]

    # Filtre VF/VO/non analysé/demandé (counts calculés avant filtrage → totaux)
    if vf == "vf":
        items = [v for v in items if v["in_library"] and v["has_vf"] is True]
    elif vf == "season_partial":
        items = [
            v for v in items if v["in_library"] and v["has_vf"] is False and v["vf_granularity"] == "season_partial"
        ]
    elif vf == "episode_partial":
        items = [
            v for v in items if v["in_library"] and v["has_vf"] is False and v["vf_granularity"] == "episode_partial"
        ]
    elif vf == "vo":
        items = [v for v in items if v["in_library"] and v["has_vf"] is False]
    elif vf == "unchecked":
        items = [v for v in items if v["in_library"] and v["has_vf"] is None]
    elif vf == "requested":
        items = [v for v in items if not v["in_library"]]
    elif vf == "plex_anomaly":
        items = [v for v in items if v["plex_anomaly"]]

    reverse = order != "asc"
    if sort == "title":
        items.sort(key=lambda v: (v["title"] or "").lower(), reverse=reverse)
    elif sort == "type":
        items.sort(key=lambda v: v["media_type"] or "", reverse=reverse)
    elif sort == "status":
        items.sort(key=lambda v: status_priority.get(v.get("request_status"), 99), reverse=reverse)
    elif sort == "available_date":
        items.sort(key=lambda v: v["available_sort_at"] or _dt.min, reverse=reverse)
    else:
        items.sort(key=lambda v: v["sort_at"] or _dt.min, reverse=reverse)

    total = len(items)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    page_items = items[(page - 1) * per_page : page * per_page]
    distinct_sources = [r[0] for r in db.query(MediaRequest.source).distinct().all() if r[0]]

    return templates.TemplateResponse(
        request,
        "library.html",
        {
            "page": "library",
            "settings": settings,
            "items": page_items,
            "active_view": view or "all",
            "active_type": type or "",
            "active_vf": vf or "",
            "active_user": user or "",
            "active_search": search or "",
            "active_status": status or "",
            "active_source": source or "",
            "counts": counts,
            "status_counts": status_counts,
            "users_map": users_map,
            "users_obj_map": {u.plex_user_id: u for u in db.query(PlexUser).all()},
            "all_users": db.query(PlexUser).order_by(PlexUser.display_name).all(),
            "sources": distinct_sources,
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
        },
    )


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request, _: None = Depends(require_admin), db: Session = Depends(get_db)):
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
    seer_enabled = bool(settings and settings.seer_url and settings.seer_api_key)
    user_summary = {
        "total": len(users),
        "enabled": sum(1 for u in users if u.enabled),
        "disabled": sum(1 for u in users if not u.enabled),
        "seer_linked": sum(1 for u in users if u.seer_user_id),
        "seer_only": sum(1 for u in users if u.source == "seer"),
    }

    instances = db.query(ArrInstance).filter(ArrInstance.enabled).all()
    sonarr_instances = [i for i in instances if i.arr_type == "sonarr"]
    radarr_instances = [i for i in instances if i.arr_type == "radarr"]

    return templates.TemplateResponse(
        request,
        "users.html",
        {
            "users": users,
            "counts_map": counts_map,
            "user_summary": user_summary,
            "seer_enabled": seer_enabled,
            "sonarr_instances": sonarr_instances,
            "radarr_instances": radarr_instances,
        },
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
def user_detail_page(user_id: int, request: Request, _: None = Depends(require_admin), db: Session = Depends(get_db)):
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
def downloads_page(request: Request, _: None = Depends(require_admin)):
    """Page Téléchargements : file d'attente *arr unifiée (auto-rafraîchie)."""
    return templates.TemplateResponse(request, "downloads.html", {"page": "downloads"})


@router.get("/calendar", response_class=HTMLResponse)
def calendar_page(request: Request, _: None = Depends(require_auth)):
    """Page Calendrier : sorties films/séries des prochains jours (Sonarr/Radarr)."""
    return templates.TemplateResponse(request, "calendar.html", {"page": "calendar"})


@router.get("/discover", response_class=HTMLResponse)
def discover_page(request: Request, _: None = Depends(require_auth), db: Session = Depends(get_db)):
    """Page Découvrir : catalogue TMDB (tendances, populaires, genres, recherche)."""
    s = db.query(Settings).first()
    return templates.TemplateResponse(
        request,
        "discover.html",
        {
            "page": "discover",
            "tmdb_configured": bool(s and (s.tmdb_api_key or "").strip()),
            "seer_requests_enabled": bool(s and s.seer_send_requests and s.seer_url and s.seer_api_key),
        },
    )


@router.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request, _: None = Depends(require_admin)):
    """Page des logs applicatifs en temps réel."""
    return templates.TemplateResponse(request, "logs.html")


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    """Page de configuration globale de l'application."""
    s = db.query(Settings).first()
    base_url = str(request.base_url).rstrip("/")
    users = db.query(PlexUser).order_by(PlexUser.display_name).all()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "s": s,
            "webhook_url": f"{base_url}/webhook",
            "webhook_secret": (s.webhook_secret if s else "") or "",
            "users": users,
            "request_template": (s.email_request_template if s else None) or DEFAULT_REQUEST_TEMPLATE,
            "available_template": (s.email_available_template if s else None) or DEFAULT_AVAILABLE_TEMPLATE,
            "failure_template": (s.email_failure_template if s else None) or DEFAULT_FAILURE_TEMPLATE,
            "available_vf_template": (s.email_available_vf_template if s else None) or DEFAULT_AVAILABLE_VF_TEMPLATE,
            "available_vo_tracking_template": (s.email_available_vo_tracking_template if s else None)
            or DEFAULT_AVAILABLE_VO_TRACKING_TEMPLATE,
            "vf_upgrade_template": (s.email_vf_upgrade_template if s else None) or DEFAULT_VF_AVAILABLE_TEMPLATE,
            "language_episode_template": (s.email_language_episode_template if s else None)
            or DEFAULT_LANGUAGE_EPISODE_TEMPLATE,
            "language_season_start_template": (s.email_language_season_start_template if s else None)
            or DEFAULT_LANGUAGE_SEASON_START_TEMPLATE,
            "language_season_complete_template": (s.email_language_season_complete_template if s else None)
            or DEFAULT_LANGUAGE_SEASON_COMPLETE_TEMPLATE,
            "language_series_complete_template": (s.email_language_series_complete_template if s else None)
            or DEFAULT_LANGUAGE_SERIES_COMPLETE_TEMPLATE,
            "request_subject": (s.email_request_subject if s else None) or "",
            "available_subject": (s.email_available_subject if s else None) or "",
            "failure_subject": (s.email_failure_subject if s else None) or "",
            "available_vf_subject": (s.email_available_vf_subject if s else None) or "",
            "available_vo_tracking_subject": (s.email_available_vo_tracking_subject if s else None) or "",
            "vf_upgrade_subject": (s.email_vf_upgrade_subject if s else None) or "",
            "language_episode_subject": (s.email_language_episode_subject if s else None) or "",
            "language_season_start_subject": (s.email_language_season_start_subject if s else None) or "",
            "language_season_complete_subject": (s.email_language_season_complete_subject if s else None) or "",
            "language_series_complete_subject": (s.email_language_series_complete_subject if s else None) or "",
        },
    )
