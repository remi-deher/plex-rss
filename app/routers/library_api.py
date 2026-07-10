import logging
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import current_user, require_admin, require_auth
from ..models import ArrInstance, LibraryItem, MediaIssue, MediaRequest, PlexUser, RequestStatus, Settings
from ..services import radarr, sonarr
from ..services import seer as seer_service
from ..utils import get_or_404, identity_keys, now_utc_naive
from .arr_api import _resolve_arr_instance

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["library"], dependencies=[Depends(require_auth)])


class MediaAddRequest(BaseModel):
    title: str
    year: Optional[int] = None
    media_type: str  # "movie" | "show"
    tmdb_id: Optional[int] = None
    tvdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    poster_url: Optional[str] = None
    overview: Optional[str] = None
    quality_profile_id: Optional[int] = None
    root_folder: Optional[str] = None
    tag_ids: list[int] = Field(default_factory=list)
    seasons: Optional[list[int]] = None
    plex_user_id: Optional[str] = None
    instance_id: Optional[int] = None  # None = Seer ou instance par défaut
    use_seer: bool = False
    bypass_seer: bool = False
    auto_search: bool = False


class MediaIssueCreate(BaseModel):
    library_id: Optional[int] = None
    request_id: Optional[int] = None
    issue_type: str = Field(..., min_length=2, max_length=50)
    message: Optional[str] = Field(default=None, max_length=2000)


class MediaIssueUpdate(BaseModel):
    status: Optional[str] = None
    admin_note: Optional[str] = Field(default=None, max_length=2000)


def _serialize_issue(issue: MediaIssue) -> dict:
    return {
        "id": issue.id,
        "created_at": issue.created_at.isoformat() if issue.created_at else None,
        "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
        "status": issue.status,
        "issue_type": issue.issue_type,
        "message": issue.message,
        "reporter_plex_user_id": issue.reporter_plex_user_id,
        "reporter_name": issue.reporter_name,
        "library_item_id": issue.library_item_id,
        "request_id": issue.request_id,
        "title": issue.title,
        "media_type": issue.media_type,
        "admin_note": issue.admin_note,
    }


def _media_identity_filter(db: Session, item) -> list[MediaRequest]:
    """Retourne les demandes qui représentent le même média qu'un LibraryItem ou une demande."""
    matches: dict[int, MediaRequest] = {}
    if isinstance(item, LibraryItem):
        for req in db.query(MediaRequest).filter(MediaRequest.library_item_id == item.id).all():
            matches[req.id] = req
    for key in identity_keys(item):
        kind = key[0]
        value = key[1] if len(key) > 1 else None
        col = {
            "guid": MediaRequest.plex_guid,
            "tmdb": MediaRequest.tmdb_id,
            "tvdb": MediaRequest.tvdb_id,
            "imdb": MediaRequest.imdb_id,
        }.get(kind)
        if col is not None:
            for req in db.query(MediaRequest).filter(col == value).all():
                matches[req.id] = req
    if getattr(item, "title", None) and getattr(item, "media_type", None):
        q = db.query(MediaRequest).filter(
            MediaRequest.title.ilike(item.title),
            MediaRequest.media_type == item.media_type,
        )
        if getattr(item, "year", None):
            q = q.filter(MediaRequest.year == item.year)
        for req in q.all():
            matches[req.id] = req
    return sorted(matches.values(), key=lambda r: r.requested_at or datetime.min, reverse=True)


async def _media_schedule_payload(db: Session, item) -> dict:
    timeline = {
        "first_aired": None,
        "next_episode_at": None,
        "last_aired_at": None,
        "ended_at": None,
        "series_status": None,
        "in_cinemas": None,
        "digital_release": None,
        "physical_release": None,
        "release_date": None,
    }
    events: list[dict] = []

    if item.media_type == "show":
        try:
            inst = _resolve_arr_instance(db, item.arr_instance_id, "sonarr")
            data = None
            series_id = None
            if item.tvdb_id:
                data = await sonarr.lookup_series(
                    inst.url,
                    inst.api_key,
                    tvdb_id=item.tvdb_id,
                    tmdb_id=item.tmdb_id,
                    imdb_id=item.imdb_id,
                )
                series_id = data.get("id") if data else None
            if not series_id and getattr(item, "source", None) != "seer" and item.arr_id:
                series_id = item.arr_id
                data = data or await sonarr.lookup_series(
                    inst.url,
                    inst.api_key,
                    arr_id=series_id,
                    tvdb_id=item.tvdb_id,
                    tmdb_id=item.tmdb_id,
                    imdb_id=item.imdb_id,
                )
            if data:
                timeline["first_aired"] = data.get("firstAired")
                timeline["next_episode_at"] = data.get("nextAiring")
                timeline["series_status"] = data.get("status")
                series_id = series_id or data.get("id")
            if series_id:
                episodes = await sonarr.get_episodes(inst.url, inst.api_key, series_id)
                dated = []
                for ep in episodes:
                    air = ep.get("airDateUtc") or ep.get("airDate")
                    if not air or ep.get("seasonNumber") == 0:
                        continue
                    dated.append(air)
                    events.append(
                        {
                            "type": "episode",
                            "date": air,
                            "title": item.title,
                            "subtitle": f"S{ep.get('seasonNumber', 0):02d}E{ep.get('episodeNumber', 0):02d}"
                            + (f" — {ep.get('title')}" if ep.get("title") else ""),
                            "has_file": bool(ep.get("hasFile")),
                            "instance": inst.name,
                        }
                    )
                if dated:
                    timeline["last_aired_at"] = max(dated)
                    if timeline["series_status"] == "ended":
                        timeline["ended_at"] = max(dated)
        except Exception as e:
            logger.debug(f"media detail: calendrier Sonarr indisponible pour '{item.title}': {e}")
    else:
        try:
            inst = _resolve_arr_instance(db, item.arr_instance_id, "radarr")
            data = await radarr.lookup_movie(
                inst.url, inst.api_key, arr_id=item.arr_id, tmdb_id=item.tmdb_id, imdb_id=item.imdb_id
            )
            if data:
                date_fields = [
                    ("in_cinemas", "Cinema", data.get("inCinemas")),
                    ("digital_release", "Digital", data.get("digitalRelease")),
                    ("physical_release", "Physique", data.get("physicalRelease")),
                ]
                for key, label, value in date_fields:
                    timeline[key] = value
                    if value:
                        events.append(
                            {
                                "type": "movie",
                                "date": value,
                                "title": item.title,
                                "subtitle": label,
                                "has_file": bool(data.get("hasFile")),
                                "instance": inst.name,
                            }
                        )
                timeline["release_date"] = (
                    timeline["in_cinemas"] or timeline["digital_release"] or timeline["physical_release"]
                )
        except Exception as e:
            logger.debug(f"media detail: calendrier Radarr indisponible pour '{item.title}': {e}")

    events.sort(key=lambda e: e["date"])
    return {"timeline": timeline, "events": events}


@router.get("/plex/sections")
async def plex_sections(db: Session = Depends(get_db)):
    """Liste les bibliothèques Plex locales (nom + type) pour la configuration VFF."""
    s = db.query(Settings).first()
    if not s or not s.plex_url or not s.plex_token:
        return []
    try:
        async with httpx.AsyncClient(timeout=10, verify=s.plex_verify_ssl) as client:
            r = await client.get(
                f"{s.plex_url.rstrip('/')}/library/sections",
                params={"X-Plex-Token": s.plex_token},
                headers={"Accept": "application/json"},
            )
            r.raise_for_status()
            dirs = r.json().get("MediaContainer", {}).get("Directory", [])
            return [{"name": d.get("title", ""), "type": d.get("type", "")} for d in dirs]
    except Exception as e:
        logger.warning(f"Plex sections fetch failed: {e}")
        return []


@router.get("/library/{item_id}")
def get_library_item(item_id: int, db: Session = Depends(get_db)):
    """Détail d'un élément de bibliothèque (pour la modale : identité + lien *arr)."""
    item = get_or_404(db, LibraryItem, item_id, "Library item not found")
    from ..serializers import serialize_library_item

    return serialize_library_item(item)


@router.get("/media/detail")
async def media_detail(
    library_id: Optional[int] = None,
    request_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Détail média unifié pour la modale Bibliothèque."""
    if not library_id and not request_id:
        raise HTTPException(400, "library_id or request_id is required")

    selected_request: Optional[MediaRequest] = None
    library_item: Optional[LibraryItem] = None
    media_obj: LibraryItem | MediaRequest
    if library_id:
        library_item = get_or_404(db, LibraryItem, library_id, "Library item not found")
        media_obj = library_item
    else:
        selected_request = get_or_404(db, MediaRequest, request_id, "Request not found")
        if selected_request.library_item_id:
            library_item = db.query(LibraryItem).filter(LibraryItem.id == selected_request.library_item_id).first()
        media_obj = library_item or selected_request

    related_requests = _media_identity_filter(db, media_obj)
    if selected_request and selected_request.id not in {r.id for r in related_requests}:
        related_requests.insert(0, selected_request)

    users = {u.plex_user_id: (u.custom_name or u.display_name or u.plex_user_id) for u in db.query(PlexUser).all()}
    from ..serializers import format_datetime, serialize_media_request

    request_payloads = [serialize_media_request(req, users) for req in related_requests]
    schedule = await _media_schedule_payload(db, media_obj)
    request_ids = [req.id for req in related_requests]
    issue_q = db.query(MediaIssue).filter(MediaIssue.status != "closed")
    if library_item and request_ids:
        issue_q = issue_q.filter(
            (MediaIssue.library_item_id == library_item.id) | (MediaIssue.request_id.in_(request_ids))
        )
    elif library_item:
        issue_q = issue_q.filter(MediaIssue.library_item_id == library_item.id)
    elif selected_request:
        issue_q = issue_q.filter(MediaIssue.request_id == selected_request.id)
    open_issues = issue_q.order_by(MediaIssue.created_at.desc()).all()

    return {
        "media": {
            "kind": "library" if library_item else "request",
            "library_id": library_item.id if library_item else None,
            "request_id": selected_request.id
            if selected_request
            else (related_requests[0].id if related_requests else None),
            "vf_source_type": "library" if library_item else "request",
            "vf_source_id": library_item.id if library_item else (selected_request.id if selected_request else None),
            "title": media_obj.title,
            "year": media_obj.year,
            "media_type": media_obj.media_type,
            "poster_url": media_obj.poster_url,
            "overview": media_obj.overview,
            "has_vf": media_obj.has_vf,
            "vf_granularity": media_obj.vf_granularity,
            "arr_id": media_obj.arr_id,
            "arr_slug": media_obj.arr_slug,
            "arr_instance_id": media_obj.arr_instance_id,
            "tmdb_id": media_obj.tmdb_id,
            "tvdb_id": media_obj.tvdb_id,
            "imdb_id": media_obj.imdb_id,
            "plex_guid": media_obj.plex_guid,
            "in_library": library_item is not None,
            "added_at": format_datetime(library_item.added_at) if library_item else None,
        },
        "requests": request_payloads,
        "issues": [_serialize_issue(issue) for issue in open_issues],
        "timeline": schedule["timeline"],
        "calendar": schedule["events"],
    }


@router.post("/media/issues")
def create_media_issue(
    body: MediaIssueCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    if not body.library_id and not body.request_id:
        raise HTTPException(400, "library_id or request_id is required")
    library_item = db.query(LibraryItem).filter(LibraryItem.id == body.library_id).first() if body.library_id else None
    media_request = db.query(MediaRequest).filter(MediaRequest.id == body.request_id).first() if body.request_id else None
    if body.library_id and not library_item:
        raise HTTPException(404, "Library item not found")
    if body.request_id and not media_request:
        raise HTTPException(404, "Request not found")

    media_obj = library_item or media_request
    user = current_user(request, db)
    issue = MediaIssue(
        issue_type=body.issue_type.strip(),
        message=(body.message or "").strip() or None,
        reporter_plex_user_id=user.get("plex_user_id") if user else None,
        reporter_name=user.get("username") if user else None,
        library_item_id=library_item.id if library_item else None,
        request_id=media_request.id if media_request else None,
        title=media_obj.title,
        media_type=media_obj.media_type,
        tmdb_id=getattr(media_obj, "tmdb_id", None),
        tvdb_id=getattr(media_obj, "tvdb_id", None),
        imdb_id=getattr(media_obj, "imdb_id", None),
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return _serialize_issue(issue)


@router.get("/media/issues", dependencies=[Depends(require_admin)])
def list_media_issues(status: Optional[str] = "open", db: Session = Depends(get_db)):
    q = db.query(MediaIssue)
    if status:
        q = q.filter(MediaIssue.status == status)
    return [_serialize_issue(issue) for issue in q.order_by(MediaIssue.created_at.desc()).limit(200).all()]


@router.patch("/media/issues/{issue_id}", dependencies=[Depends(require_admin)])
def update_media_issue(issue_id: int, body: MediaIssueUpdate, db: Session = Depends(get_db)):
    issue = get_or_404(db, MediaIssue, issue_id, "Issue not found")
    if body.status is not None:
        if body.status not in {"open", "investigating", "resolved", "closed"}:
            raise HTTPException(400, "Invalid issue status")
        issue.status = body.status
    if body.admin_note is not None:
        issue.admin_note = body.admin_note
    issue.updated_at = now_utc_naive()
    db.commit()
    db.refresh(issue)
    return _serialize_issue(issue)


@router.post("/media/issues/{issue_id}/retry", dependencies=[Depends(require_admin)])
async def retry_issue_media_search(issue_id: int, db: Session = Depends(get_db)):
    issue = get_or_404(db, MediaIssue, issue_id, "Issue not found")
    arr_id = None
    arr_instance_id = None

    if issue.library_item_id:
        lib_item = db.query(LibraryItem).filter(LibraryItem.id == issue.library_item_id).first()
        if lib_item:
            arr_id = lib_item.arr_id
            arr_instance_id = lib_item.arr_instance_id

    if not arr_id and issue.request_id:
        req = db.query(MediaRequest).filter(MediaRequest.id == issue.request_id).first()
        if req:
            arr_id = req.arr_id
            arr_instance_id = req.arr_instance_id

    if not arr_id or not arr_instance_id:
        raise HTTPException(status_code=400, detail="Média non associé à une instance Sonarr/Radarr")

    try:
        if issue.media_type in ("show", "series"):
            inst = _resolve_arr_instance(db, arr_instance_id, "sonarr")
            success = await sonarr.search_series(inst.url, inst.api_key, arr_id)
        else:
            inst = _resolve_arr_instance(db, arr_instance_id, "radarr")
            success = await radarr.search_movie(inst.url, inst.api_key, arr_id)
        return {"success": success}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur d'appel *arr : {e}")


@router.post("/media/recheck-plex")
async def recheck_plex(
    request_id: Optional[int] = None,
    library_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Revérifie si un média (souvent une « anomalie Plex ») est désormais indexé par Plex.

    Cas d'usage : Sonarr/Radarr a bien importé le fichier (demande « disponible »)
    mais Plex ne le trouvait pas. On relance une recherche ciblée (GUID > IDs
    externes > titre) dans les bibliothèques configurées ; si le média est trouvé,
    on crée le LibraryItem correspondant et on y rattache les demandes — il cesse
    alors d'être une anomalie.
    """
    import asyncio

    from ..services.plex_sync import _find_library_item_by_ids
    from ..services.vff import connect, find_item_in_libraries
    from ..services.vff_scanner import _parse_vff_libraries
    from ..utils import now_utc_naive

    if not request_id and not library_id:
        raise HTTPException(400, "request_id or library_id is required")

    if library_id:
        get_or_404(db, LibraryItem, library_id, "Library item not found")
        return {"found": True, "already_in_library": True, "library_id": library_id}
    media = get_or_404(db, MediaRequest, request_id, "Request not found")

    settings = db.query(Settings).first()
    if not settings or not settings.plex_url or not settings.plex_token:
        raise HTTPException(400, "Plex non configuré")
    libs = _parse_vff_libraries(settings)
    if not libs:
        raise HTTPException(400, "Aucune bibliothèque Plex configurée")

    if media.media_type == "movie":
        lib_names = [lib["name"] for lib in libs if lib["kind"] == "movie"]
    else:
        lib_names = [lib["name"] for lib in libs if lib["kind"] in ("series", "anime")]

    def _search():
        plex = connect(settings.plex_url, settings.plex_token)
        return find_item_in_libraries(
            plex,
            lib_names,
            media.title,
            media.year,
            media.tmdb_id,
            media.tvdb_id,
            media.imdb_id,
            plex_guid=media.plex_guid,
        )

    try:
        found = await asyncio.to_thread(_search)
    except Exception as e:
        logger.warning(f"Recheck Plex échoué pour {media.title!r}: {e}")
        raise HTTPException(502, f"Erreur de connexion Plex : {e}")

    if not found:
        return {"found": False}

    # Extraire les identifiants externes du média Plex trouvé
    tmdb_id = tvdb_id = imdb_id = None
    for g in getattr(found, "guids", []) or []:
        gid = g.id or ""
        if gid.startswith("tmdb://"):
            tmdb_id = gid.split("tmdb://")[-1]
        elif gid.startswith("tvdb://"):
            tvdb_id = gid.split("tvdb://")[-1]
        elif gid.startswith("imdb://"):
            imdb_id = gid.split("imdb://")[-1]
    plex_guid = getattr(found, "guid", None)
    now = now_utc_naive()

    lib_item = _find_library_item_by_ids(
        db, plex_guid, tmdb_id, tvdb_id, imdb_id, found.title, getattr(found, "year", None), media.media_type
    )
    if not lib_item:
        thumb = getattr(found, "thumb", None)
        added = getattr(found, "addedAt", None)
        if added and added.tzinfo:
            added = added.replace(tzinfo=None)
        lib_item = LibraryItem(
            title=found.title,
            year=getattr(found, "year", None),
            media_type=media.media_type,
            tmdb_id=tmdb_id,
            tvdb_id=tvdb_id,
            imdb_id=imdb_id,
            plex_guid=plex_guid,
            poster_url=(
                f"{settings.plex_url.rstrip('/')}{thumb}?X-Plex-Token={settings.plex_token}"
                if thumb
                else media.poster_url
            ),
            overview=getattr(found, "summary", None) or media.overview,
            added_at=added,
            arr_instance_id=media.arr_instance_id,
            arr_id=media.arr_id,
            arr_slug=media.arr_slug,
            has_vf=None,
            created_at=now,
            updated_at=now,
        )
        db.add(lib_item)
        db.flush()

    # Rattacher toutes les demandes qui représentent ce média
    for req in _media_identity_filter(db, lib_item):
        req.library_item_id = lib_item.id
    if media.library_item_id != lib_item.id:
        media.library_item_id = lib_item.id
    db.commit()

    return {"found": True, "library_id": lib_item.id}


@router.get("/media/capabilities")
def media_capabilities(db: Session = Depends(get_db)):
    """Retourne les services disponibles pour orienter le flux de recherche côté frontend."""
    s = db.query(Settings).first()
    instances = db.query(ArrInstance).filter(ArrInstance.enabled).all()
    arr_types = {i.arr_type for i in instances}
    return {
        "has_sonarr": "sonarr" in arr_types,
        "has_radarr": "radarr" in arr_types,
        "has_prowlarr": "prowlarr" in arr_types,
        "has_seer": bool(s and s.seer_send_requests and s.seer_url and s.seer_api_key),
        "seer_fallback_arr": bool(s and s.seer_fallback_arr),
    }


@router.get("/media/lookup")
async def media_lookup(query: str, type: str = "movie", db: Session = Depends(get_db)):
    """Cherche un titre via l'API Sonarr ou Radarr et retourne les métadonnées enrichies."""
    instances = db.query(ArrInstance).filter(ArrInstance.enabled).all()
    arr_type = "sonarr" if type == "show" else "radarr"
    inst = next((i for i in instances if i.arr_type == arr_type and i.is_default), None)
    if not inst:
        inst = next((i for i in instances if i.arr_type == arr_type), None)

    if not inst:
        return []

    base = inst.url.rstrip("/")
    headers = {"X-Api-Key": inst.api_key}
    endpoint = "/api/v3/series/lookup" if arr_type == "sonarr" else "/api/v3/movie/lookup"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{base}{endpoint}", params={"term": query}, headers=headers)
            r.raise_for_status()
            results = r.json()
    except Exception as e:
        logger.warning(f"Media lookup failed ({arr_type}): {e}")
        return []

    def _poster(item: dict) -> Optional[str]:
        for img in item.get("images", []):
            if img.get("coverType") == "poster":
                remote = img.get("remoteUrl") or img.get("url", "")
                if remote:
                    return remote
        return None

    normalized = []
    for item in results[:10]:
        if arr_type == "sonarr":
            normalized.append(
                {
                    "title": item.get("title", ""),
                    "year": item.get("year"),
                    "overview": item.get("overview", ""),
                    "poster": _poster(item),
                    "tvdb_id": item.get("tvdbId"),
                    "tmdb_id": None,
                    "media_type": "show",
                    "already_added": item.get("id") is not None,
                    "arr_id": item.get("id"),
                    "arr_instance_id": inst.id,
                    "status": item.get("status", ""),
                }
            )
        else:
            normalized.append(
                {
                    "title": item.get("title", ""),
                    "year": item.get("year"),
                    "overview": item.get("overview", ""),
                    "poster": _poster(item),
                    "tmdb_id": item.get("tmdbId"),
                    "tvdb_id": None,
                    "media_type": "movie",
                    "already_added": item.get("id") is not None,
                    "arr_id": item.get("id"),
                    "arr_instance_id": inst.id,
                    "status": item.get("status", ""),
                }
            )
    return normalized


def _needs_approval(db: Session, settings: Optional[Settings], caller: Optional[dict], plex_user_id: Optional[str]) -> bool:
    """Détermine si une demande doit passer par la file de validation admin.

    Jamais pour un admin/owner (ni un appel token API). Sinon uniquement si
    l'approbation est activée globalement ET que l'utilisateur n'est pas auto-approuvé.
    """
    if not caller or caller.get("is_owner") or caller.get("role") == "admin":
        return False
    if not (settings and settings.require_approval):
        return False
    if plex_user_id:
        pu = db.query(PlexUser).filter(PlexUser.plex_user_id == plex_user_id).first()
        if pu and pu.auto_approve:
            return False
    return True


def _create_pending_request(db: Session, body: "MediaAddRequest") -> dict:
    """Enregistre une demande en attente de validation (aucune soumission à *arr)."""
    tmdb_str = str(body.tmdb_id) if body.tmdb_id else None
    tvdb_str = str(body.tvdb_id) if body.tvdb_id else None

    existing = None
    if tmdb_str:
        existing = db.query(MediaRequest).filter(MediaRequest.tmdb_id == tmdb_str).first()
    if not existing and tvdb_str:
        existing = db.query(MediaRequest).filter(MediaRequest.tvdb_id == tvdb_str).first()
    if not existing:
        existing = (
            db.query(MediaRequest)
            .filter(MediaRequest.title == body.title, MediaRequest.media_type == body.media_type)
            .first()
        )
    if existing:
        # Média déjà connu : on ne recrée pas de doublon en attente.
        return {"ok": True, "pending_approval": True, "already_existed": True, "id": existing.id}

    user_id = body.plex_user_id or "manual"
    user_label = user_id
    pu = db.query(PlexUser).filter(PlexUser.plex_user_id == user_id).first()
    if pu:
        user_label = pu.custom_name or pu.display_name or pu.plex_user_id

    req = MediaRequest(
        plex_user_id=user_id,
        plex_user=user_label,
        title=body.title,
        year=body.year,
        media_type=body.media_type,
        tmdb_id=tmdb_str,
        tvdb_id=tvdb_str,
        imdb_id=body.imdb_id,
        status=RequestStatus.pending_approval,
        source="user_request",
        poster_url=body.poster_url,
        overview=body.overview,
        requested_at=now_utc_naive(),
    )
    db.add(req)
    db.commit()
    return {"ok": True, "pending_approval": True, "already_existed": False, "id": req.id}


@router.post("/media/add")
async def media_add(body: MediaAddRequest, request: Request, db: Session = Depends(get_db)):
    """Ajoute un média via Seer (prioritaire) ou directement dans Sonarr/Radarr.

    Contrôle d'accès : un utilisateur 'user' ne peut demander que pour lui-même
    (le plex_user_id de la session prime sur le corps de requête). Si l'approbation
    est activée et que cet utilisateur n'est pas auto-approuvé, la demande est mise
    en file d'attente (pending_approval) sans être envoyée à *arr.
    """
    s = db.query(Settings).first()
    item = body.model_dump()

    caller = current_user(request, db)
    caller_is_admin = bool(caller and (caller.get("is_owner") or caller.get("role") == "admin"))
    if not caller_is_admin and caller and caller.get("plex_user_id"):
        # Un 'user' demande forcément pour lui-même : on ignore body.plex_user_id.
        body.plex_user_id = caller["plex_user_id"]
        item["plex_user_id"] = caller["plex_user_id"]

    pending = _needs_approval(db, s, caller, body.plex_user_id)
    if pending:
        return _create_pending_request(db, body)

    arr_id = None
    already = False
    via = None
    chosen_instance_id = None  # instance *arr choisie (pour le suivi de statut)
    chosen_slug = None

    seer_eligible = s and s.seer_send_requests and s.seer_url and s.seer_api_key
    if not body.bypass_seer and (body.use_seer or (not body.instance_id and seer_eligible)):
        if not seer_eligible:
            raise HTTPException(400, "Seer n'est pas configuré.")
        try:
            seer_id, already, _ = await seer_service.request_media(s.seer_url, s.seer_api_key, item)
            arr_id = seer_id
            via = "seer"
        except Exception as e:
            if body.use_seer or not s.seer_fallback_arr:
                raise HTTPException(502, f"Erreur Seer : {e}")
            logger.warning(f"Seer failed, falling back to arr: {e}")

    if via is None:
        instances = db.query(ArrInstance).filter(ArrInstance.enabled).all()
        arr_type = "sonarr" if body.media_type == "show" else "radarr"

        if body.instance_id:
            inst = next((i for i in instances if i.id == body.instance_id and i.arr_type == arr_type), None)
            if not inst:
                raise HTTPException(400, f"Instance {body.instance_id} introuvable ou désactivée.")
        else:
            inst = next((i for i in instances if i.arr_type == arr_type and i.is_default), None)
            if not inst:
                inst = next((i for i in instances if i.arr_type == arr_type), None)

        if not inst:
            raise HTTPException(400, "Aucune instance Sonarr/Radarr configurée et Seer non activé.")

        base = inst.url.rstrip("/")
        headers = {"X-Api-Key": inst.api_key}

        qp_id = body.quality_profile_id
        rf = body.root_folder
        if not qp_id or not rf:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    if not qp_id:
                        qp_resp = await client.get(f"{base}/api/v3/qualityprofile", headers=headers)
                        profiles = qp_resp.json()
                        qp_id = profiles[0]["id"] if profiles else 1
                    if not rf:
                        rf_resp = await client.get(f"{base}/api/v3/rootfolder", headers=headers)
                        folders = rf_resp.json()
                        rf = folders[0]["path"] if folders else "/"
            except Exception as e:
                raise HTTPException(502, f"Impossible de récupérer la config {arr_type}: {e}")

        search_triggered = False
        try:
            if arr_type == "sonarr":
                item["seasons"] = body.seasons
                arr_id, already, chosen_slug = await sonarr.add_series(
                    inst.url, inst.api_key, qp_id, rf, item, tag_ids=body.tag_ids
                )
                if already and body.auto_search and isinstance(arr_id, int):
                    search_triggered = await sonarr.search_series(inst.url, inst.api_key, arr_id)
                elif body.auto_search and not already:
                    search_triggered = True
            else:
                arr_id, already, chosen_slug = await radarr.add_movie(
                    inst.url, inst.api_key, qp_id, rf, item, tag_ids=body.tag_ids
                )
                if already and body.auto_search and isinstance(arr_id, int):
                    search_triggered = await radarr.search_movie(inst.url, inst.api_key, arr_id)
                elif body.auto_search and not already:
                    search_triggered = True
            via = arr_type
            chosen_instance_id = inst.id
        except Exception as e:
            raise HTTPException(502, f"Erreur {arr_type} : {e}")
    else:
        search_triggered = False

    tmdb_str = str(body.tmdb_id) if body.tmdb_id else None
    tvdb_str = str(body.tvdb_id) if body.tvdb_id else None
    existing = (
        db.query(MediaRequest)
        .filter(
            MediaRequest.title == body.title,
            MediaRequest.media_type == body.media_type,
        )
        .first()
    )
    if tmdb_str and not existing:
        existing = db.query(MediaRequest).filter(MediaRequest.tmdb_id == tmdb_str).first()
    if tvdb_str and not existing:
        existing = db.query(MediaRequest).filter(MediaRequest.tvdb_id == tvdb_str).first()

    # Source de suivi : "seer" → suivi par seer_sync (interroge Overseerr) ;
    # sinon → suivi par check_arr_statuses via l'instance *arr enregistrée.
    source_val = "seer" if via == "seer" else "manual_search"

    if not existing:
        user_id = body.plex_user_id or "manual"
        user_label = "Recherche manuelle"
        if body.plex_user_id:
            pu = db.query(PlexUser).filter(PlexUser.plex_user_id == body.plex_user_id).first()
            if pu:
                user_label = pu.display_name or pu.plex_user_id
        req = MediaRequest(
            plex_user_id=user_id,
            plex_user=user_label,
            title=body.title,
            year=body.year,
            media_type=body.media_type,
            tmdb_id=tmdb_str,
            tvdb_id=tvdb_str,
            imdb_id=body.imdb_id,
            status=RequestStatus.sent_to_arr,
            source=source_val,
            arr_id=arr_id if isinstance(arr_id, int) else None,
            arr_slug=chosen_slug,
            arr_instance_id=chosen_instance_id,
            poster_url=body.poster_url,
            overview=body.overview,
        )
        db.add(req)
        db.commit()
    else:
        # Ré-attache le contexte de suivi à une demande existante qui n'en avait pas
        # (ancienne demande manuelle, ou média re-demandé), pour que le statut repasse.
        if chosen_instance_id and not existing.arr_instance_id:
            existing.arr_instance_id = chosen_instance_id
        if chosen_slug and not existing.arr_slug:
            existing.arr_slug = chosen_slug
        if isinstance(arr_id, int) and not existing.arr_id:
            existing.arr_id = arr_id
        if via == "seer" and existing.source != "seer":
            existing.source = "seer"
        if body.poster_url and not existing.poster_url:
            existing.poster_url = body.poster_url
        if body.overview and not existing.overview:
            existing.overview = body.overview
        # Ré-attribue un demandeur réel si la demande était orpheline ("manual")
        if body.plex_user_id and existing.plex_user_id == "manual":
            existing.plex_user_id = body.plex_user_id
            pu = db.query(PlexUser).filter(PlexUser.plex_user_id == body.plex_user_id).first()
            existing.plex_user = (pu.display_name or pu.plex_user_id) if pu else body.plex_user_id
        if existing.status in (RequestStatus.failed, RequestStatus.pending):
            existing.status = RequestStatus.sent_to_arr
        db.commit()

    return {"ok": True, "via": via, "already_existed": already, "id": arr_id, "search_triggered": search_triggered}
