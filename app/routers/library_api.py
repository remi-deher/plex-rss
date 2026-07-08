import logging
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_auth
from ..models import ArrInstance, LibraryItem, MediaRequest, PlexUser, RequestStatus, Settings
from ..services import radarr, sonarr
from ..services import seer as seer_service
from ..utils import get_or_404, identity_keys
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
    quality_profile_id: Optional[int] = None
    root_folder: Optional[str] = None
    tag_ids: list[int] = []
    plex_user_id: Optional[str] = None
    instance_id: Optional[int] = None  # None = Seer ou instance par défaut
    use_seer: bool = False


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
                data = await sonarr.lookup_series(inst.url, inst.api_key, tvdb_id=item.tvdb_id)
                series_id = data.get("id") if data else None
            if not series_id and getattr(item, "source", None) != "seer" and item.arr_id:
                series_id = item.arr_id
                data = data or await sonarr.lookup_series(inst.url, inst.api_key, arr_id=series_id)
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

    selected_request = None
    library_item = None
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
    from ..serializers import serialize_media_request, format_datetime
    request_payloads = [serialize_media_request(req, users) for req in related_requests]
    schedule = await _media_schedule_payload(db, media_obj)

    return {
        "media": {
            "kind": "library" if library_item else "request",
            "library_id": library_item.id if library_item else None,
            "request_id": selected_request.id if selected_request else (related_requests[0].id if related_requests else None),
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
        "timeline": schedule["timeline"],
        "calendar": schedule["events"],
    }


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


@router.post("/media/add")
async def media_add(body: MediaAddRequest, db: Session = Depends(get_db)):
    """Ajoute un média via Seer (prioritaire) ou directement dans Sonarr/Radarr."""
    s = db.query(Settings).first()
    item = body.model_dump()

    arr_id = None
    already = False
    via = None

    seer_eligible = s and s.seer_send_requests and s.seer_url and s.seer_api_key
    if body.use_seer or (not body.instance_id and seer_eligible):
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

        try:
            if arr_type == "sonarr":
                arr_id, already, _ = await sonarr.add_series(
                    inst.url, inst.api_key, qp_id, rf, item, tag_ids=body.tag_ids
                )
            else:
                arr_id, already, _ = await radarr.add_movie(
                    inst.url, inst.api_key, qp_id, rf, item, tag_ids=body.tag_ids
                )
            via = arr_type
        except Exception as e:
            raise HTTPException(502, f"Erreur {arr_type} : {e}")

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
            source="manual_search",
            arr_id=arr_id if isinstance(arr_id, int) else None,
        )
        db.add(req)
        db.commit()

    return {"ok": True, "via": via, "already_existed": already, "id": arr_id}
