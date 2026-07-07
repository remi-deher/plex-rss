"""
API REST JSON de l'application.

Endpoints regroupés par domaine :
- /api/settings          : lecture et mise à jour de la configuration
- /api/test/*            : tests de connectivité (Plex, Sonarr, Radarr, SMTP, Discord, Telegram)
- /api/sonarr|radarr/*  : helpers de configuration (profils, dossiers)
- /api/users             : CRUD utilisateurs Plex
- /api/requests          : lecture, retry, suppression, polling manuel
- /api/stats/*           : compteurs, timeline, par utilisateur
- /api/health            : état des services
- /api/activity          : journal d'événements récents
- /api/notifications/*   : médias récemment disponibles
- /api/next-poll         : temps restant avant le prochain polling
- /api/onboarding        : checklist de configuration initiale
"""

import asyncio
import hmac
import json as _json
import logging
import os as _os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import metrics as app_metrics
from ..database import get_db
from ..models import (
    ArrInstance,
    DownloadClient,
    LibraryItem,
    MediaRequest,
    NotificationLog,
    PlexUser,
    PollHistory,
    RequestStatus,
    Settings,
    VfEpisodeStatus,
)
from ..notification_queue import enqueue as enqueue_notification
from ..scheduler import _send_digest, check_arr_statuses, poll_watchlists, update_poll_interval
from ..scheduler import scheduler as _scheduler
from ..services import email_service, prowlarr, radarr, sonarr
from ..services import seer as seer_service
from ..services.download_clients import add_torrent_file_to_client, add_torrent_to_client, check_client_connection
from ..services.email_service import DEFAULT_AVAILABLE_TEMPLATE, DEFAULT_REQUEST_TEMPLATE, add_email_footer, render_template
from ..services.email_service import _send as smtp_send
from ..services.plex_api import check_connection as plex_test
from ..services.plex_rss import test_rss
from ..services.seer import check_connection as seer_test
from ..utils import get_or_404, identity_keys, parse_email_list

logger = logging.getLogger(__name__)


def _set_single_default(db: Session, model, type_col: str, type_val: str, exclude_id: Optional[int] = None) -> None:
    """Remet is_default=False sur toutes les instances du même type, sauf exclude_id."""
    q = db.query(model).filter(getattr(model, type_col) == type_val)
    if exclude_id is not None:
        q = q.filter(model.id != exclude_id)
    q.update({"is_default": False})


def _format_datetime(dt: Optional[datetime]) -> Optional[str]:
    """Force timezone info to UTC for serialization, resolving timezone offset issues in client-side JS."""
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat()
    return dt.isoformat()


def _delete_vf_episode_cache(db: Session, request_id: int) -> None:
    """Purge le cache VF par épisode d'une demande supprimée (évite les lignes orphelines)."""
    db.query(VfEpisodeStatus).filter(
        VfEpisodeStatus.source_type == "request", VfEpisodeStatus.source_id == request_id
    ).delete()


def _request_status_value(req: MediaRequest) -> str:
    return req.status.value if hasattr(req.status, "value") else str(req.status)


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


def _request_summary_payload(req: MediaRequest, users: dict[str, str]) -> dict:
    requester_ids = [req.plex_user_id]
    extras = []
    try:
        extras = _json.loads(req.extra_requesters or "[]")
        for extra in extras:
            uid = extra.get("plex_user_id")
            if uid:
                requester_ids.append(uid)
                extra["display_name"] = users.get(uid, extra.get("display_name") or uid)
    except Exception:
        extras = []
    requesters = [users.get(uid, uid) for uid in requester_ids]
    return {
        "id": req.id,
        "title": req.title,
        "year": req.year,
        "media_type": req.media_type,
        "status": _request_status_value(req),
        "source": req.source,
        "plex_user_id": req.plex_user_id,
        "plex_user": users.get(req.plex_user_id, req.plex_user or req.plex_user_id),
        "requesters": requesters,
        "requested_by": ", ".join(requesters),
        "extra_requesters": _json.dumps(extras),
        "requested_at": _format_datetime(req.requested_at),
        "available_at": _format_datetime(req.available_at),
        "request_mail_sent": req.request_mail_sent,
        "available_mail_sent": req.available_mail_sent,
        "overview": req.overview,
        "has_vf": req.has_vf,
        "arr_id": req.arr_id,
        "arr_slug": req.arr_slug,
        "arr_instance_id": req.arr_instance_id,
        "library_item_id": req.library_item_id,
    }


def require_auth(request: Request, db: Session = Depends(get_db)):
    """Dépendance API : session cookie OU header X-Api-Key."""
    if request.session.get("authenticated"):
        return
    token = request.headers.get("X-Api-Key")
    if token:
        s = db.query(Settings).first()
        if s and s.api_token and hmac.compare_digest(s.api_token, token):
            return
    raise HTTPException(status_code=401, detail="Non authentifié")


router = APIRouter(prefix="/api", tags=["api"], dependencies=[Depends(require_auth)])


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SERIES_NOTIFY_MODES = {
    "every_episode",
    "season_complete",
    "series_complete",
    "season_start_and_complete",
}


def _validate_series_notify_modes(payload: dict):
    for key in ("series_vo_notify_mode", "series_vf_notify_mode"):
        value = payload.get(key)
        if value is not None and value not in SERIES_NOTIFY_MODES:
            raise HTTPException(status_code=400, detail=f"Mode de notification invalide: {value}")


class SettingsUpdate(BaseModel):
    plex_url: Optional[str] = None
    plex_token: Optional[str] = None
    plex_verify_ssl: Optional[bool] = None
    plex_rss_url: Optional[str] = None
    watchlist_source_priority: Optional[str] = None
    watchlist_fallback_enabled: Optional[bool] = None
    poll_interval_minutes: Optional[int] = None
    sonarr_url: Optional[str] = None
    sonarr_api_key: Optional[str] = None
    sonarr_quality_profile_id: Optional[int] = None
    sonarr_root_folder: Optional[str] = None
    sonarr_enabled: Optional[bool] = None
    radarr_url: Optional[str] = None
    radarr_api_key: Optional[str] = None
    radarr_quality_profile_id: Optional[int] = None
    radarr_root_folder: Optional[str] = None
    radarr_enabled: Optional[bool] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_tls: Optional[bool] = None
    email_on_request: Optional[bool] = None
    email_on_available: Optional[bool] = None
    discord_webhook_url: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    admin_notification_email: Optional[str] = None
    radarr_minimum_availability: Optional[str] = None
    seer_url: Optional[str] = None
    seer_api_key: Optional[str] = None
    seer_enabled: Optional[bool] = None  # legacy
    seer_send_requests: Optional[bool] = None
    seer_fallback_arr: Optional[bool] = None
    notification_log_retention_days: Optional[int] = None
    email_request_template: Optional[str] = None
    email_available_template: Optional[str] = None
    email_request_subject: Optional[str] = None
    email_available_subject: Optional[str] = None
    digest_enabled: Optional[bool] = None
    digest_hour: Optional[int] = None
    torrent_required_keywords: Optional[str] = None
    torrent_forbidden_keywords: Optional[str] = None
    torrent_min_size_gb: Optional[float] = None
    torrent_max_size_gb: Optional[float] = None
    torrent_ratio_limit: Optional[float] = None
    torrent_seed_time_limit_hours: Optional[int] = None
    torrent_auto_delete_files: Optional[bool] = None
    # --- VFF ---
    vff_enabled: Optional[bool] = None
    vff_libraries: Optional[str] = None
    vff_recheck_interval_minutes: Optional[int] = None
    vff_auto_search: Optional[bool] = None
    email_on_vf_available: Optional[bool] = None
    partial_notify_frequency: Optional[str] = None
    movie_vo_notify: Optional[bool] = None
    movie_vf_notify: Optional[bool] = None
    series_vo_notify_mode: Optional[str] = None
    series_vf_notify_mode: Optional[str] = None


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    """Retourne la configuration complète. Le mot de passe SMTP est masqué."""
    s = db.query(Settings).first()
    if not s:
        raise HTTPException(404, "Settings not found")
    d = {c.name: getattr(s, c.name) for c in s.__table__.columns}
    if d.get("smtp_password"):
        d["smtp_password"] = "••••••••"
    return d


@router.put("/settings")
def update_settings(data: SettingsUpdate, db: Session = Depends(get_db)):
    """Met à jour la configuration. Ignore la valeur masquée du mot de passe SMTP."""
    s = db.query(Settings).first()
    if not s:
        raise HTTPException(status_code=404, detail="Paramètres non initialisés")
    # Champs qui peuvent être explicitement effacés avec null (template custom → retour au défaut)
    _nullable_fields = {
        "email_request_template",
        "email_available_template",
        "email_request_subject",
        "email_available_subject",
        "torrent_required_keywords",
        "torrent_forbidden_keywords",
        "torrent_min_size_gb",
        "torrent_max_size_gb",
        "torrent_ratio_limit",
        "torrent_seed_time_limit_hours",
    }
    payload = data.model_dump()
    _validate_series_notify_modes(payload)
    for key, val in payload.items():
        if val is None and key not in _nullable_fields:
            continue
        if key == "smtp_password" and val == "••••••••":
            continue
        if key == "notification_log_retention_days" and val == 0:
            val = None
        setattr(s, key, val)
    db.commit()
    if data.poll_interval_minutes:
        update_poll_interval(data.poll_interval_minutes)
    # Replanifier le digest si l'heure ou l'activation change
    if data.digest_enabled is not None or data.digest_hour is not None:
        hour = s.digest_hour or 8
        if s.digest_enabled:
            _scheduler.add_job(_send_digest, "cron", hour=hour, minute=0, id="digest", replace_existing=True)
        else:
            try:
                _scheduler.remove_job("digest")
            except Exception:
                pass
    # Replanifier le job VFF si l'intervalle a changé
    if data.vff_recheck_interval_minutes:
        from apscheduler.triggers.interval import IntervalTrigger

        try:
            _scheduler.reschedule_job(
                "vf_status_check", trigger=IntervalTrigger(minutes=data.vff_recheck_interval_minutes)
            )
        except Exception:
            pass
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Instances Sonarr / Radarr / Prowlarr
# ---------------------------------------------------------------------------


class ArrInstanceCreate(BaseModel):
    name: str
    arr_type: str
    url: str
    api_key: str
    quality_profile_id: Optional[int] = None
    root_folder: Optional[str] = None
    minimum_availability: Optional[str] = "released"
    enabled: Optional[bool] = True
    is_default: Optional[bool] = False
    indexer_ids: Optional[str] = None


class TestArrInstanceBody(BaseModel):
    url: str
    api_key: str
    arr_type: str


@router.get("/arr-instances")
def list_arr_instances(db: Session = Depends(get_db)):
    return db.query(ArrInstance).all()


@router.post("/arr-instances")
def create_arr_instance(data: ArrInstanceCreate, db: Session = Depends(get_db)):
    if data.is_default:
        _set_single_default(db, ArrInstance, "arr_type", data.arr_type)
    inst = ArrInstance(**data.model_dump())
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


@router.put("/arr-instances/{instance_id}")
def update_arr_instance(instance_id: int, data: ArrInstanceCreate, db: Session = Depends(get_db)):
    inst = get_or_404(db, ArrInstance, instance_id, "Instance introuvable")
    if data.is_default:
        _set_single_default(db, ArrInstance, "arr_type", data.arr_type, exclude_id=instance_id)
    for k, v in data.model_dump().items():
        setattr(inst, k, v)
    db.commit()
    db.refresh(inst)
    return inst


@router.delete("/arr-instances/{instance_id}")
def delete_arr_instance(instance_id: int, db: Session = Depends(get_db)):
    inst = get_or_404(db, ArrInstance, instance_id, "Instance introuvable")
    db.delete(inst)
    db.commit()
    return {"status": "deleted"}


@router.post("/test/arr-instance")
async def test_arr_instance(body: TestArrInstanceBody):
    if body.arr_type == "prowlarr":
        ok = await prowlarr.check_connection(body.url, body.api_key)
        return {"success": ok, "message": "Prowlarr connecté" if ok else "Erreur de connexion Prowlarr"}
    elif body.arr_type == "sonarr":
        ok, msg = await sonarr.check_connection(body.url, body.api_key)
        return {"success": ok, "message": msg}
    elif body.arr_type == "radarr":
        ok, msg = await radarr.check_connection(body.url, body.api_key)
        return {"success": ok, "message": msg}
    return {"success": False, "message": f"Type d'instance inconnu : {body.arr_type}"}


@router.get("/prowlarr/indexers")
async def get_prowlarr_indexers(
    instance_id: Optional[int] = None,
    url: Optional[str] = None,
    api_key: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if url and api_key:
        indexers = await prowlarr.get_indexers(url, api_key)
        return [{"id": idx["id"], "name": idx["name"]} for idx in indexers]
    inst = _resolve_arr_instance(db, instance_id, "prowlarr")
    indexers = await prowlarr.get_indexers(inst.url, inst.api_key)
    return [{"id": idx["id"], "name": idx["name"]} for idx in indexers]


@router.get("/prowlarr/{instance_id}/download-client-status")
async def get_prowlarr_download_client_status(instance_id: int, db: Session = Depends(get_db)):
    """Indique si Prowlarr a lui-même un client de téléchargement actif.

    Si oui, on peut lui déléguer le grab (`/prowlarr/grab`) au lieu d'exiger un client
    de téléchargement configuré séparément dans l'app.
    """
    inst = get_or_404(db, ArrInstance, instance_id, "Instance Prowlarr introuvable")
    clients = await prowlarr.get_download_clients(inst.url, inst.api_key)
    return {"has_client": any(c.get("enable") for c in clients)}


class ProwlarrGrabRequest(BaseModel):
    guid: str
    indexer_id: int
    instance_id: int
    request_id: Optional[int] = None


@router.post("/prowlarr/grab")
async def prowlarr_grab_release(body: ProwlarrGrabRequest, db: Session = Depends(get_db)):
    """Grab d'une release via le client de téléchargement configuré dans Prowlarr lui-même."""
    inst = get_or_404(db, ArrInstance, body.instance_id, "Instance Prowlarr introuvable")
    ok, msg = await prowlarr.grab(inst.url, inst.api_key, body.guid, body.indexer_id)
    if not ok:
        raise HTTPException(500, msg)
    if body.request_id:
        req = db.query(MediaRequest).filter(MediaRequest.id == body.request_id).first()
        if req and req.status not in (RequestStatus.available,):
            req.status = RequestStatus.sent_to_arr
            db.commit()
    return {"success": True, "message": msg}


# ---------------------------------------------------------------------------
# Clients de téléchargement & Moteur de recherche Prowlarr
# ---------------------------------------------------------------------------


class DownloadClientCreate(BaseModel):
    name: str
    client_type: str
    url: str
    username: Optional[str] = None
    password: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    is_default: Optional[bool] = False
    enabled: Optional[bool] = True


class TestDownloadClientBody(BaseModel):
    client_type: str
    url: str
    username: Optional[str] = None
    password: Optional[str] = None


class DownloadReleaseRequest(BaseModel):
    torrent_url_or_magnet: str
    client_id: int
    category: Optional[str] = None
    tags: Optional[str] = None
    request_id: Optional[int] = None


@router.get("/download-clients")
def list_download_clients(db: Session = Depends(get_db)):
    return db.query(DownloadClient).all()


@router.post("/download-clients")
def create_download_client(data: DownloadClientCreate, db: Session = Depends(get_db)):
    if data.is_default:
        _set_single_default(db, DownloadClient, "client_type", data.client_type)
    client = DownloadClient(**data.model_dump())
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@router.put("/download-clients/{client_id}")
def update_download_client(client_id: int, data: DownloadClientCreate, db: Session = Depends(get_db)):
    client = get_or_404(db, DownloadClient, client_id, "Client introuvable")
    if data.is_default:
        _set_single_default(db, DownloadClient, "client_type", data.client_type, exclude_id=client_id)
    for k, v in data.model_dump().items():
        setattr(client, k, v)
    db.commit()
    db.refresh(client)
    return client


@router.patch("/download-clients/{client_id}/toggle")
def toggle_download_client(client_id: int, db: Session = Depends(get_db)):
    client = get_or_404(db, DownloadClient, client_id, "Client introuvable")
    client.enabled = not client.enabled
    db.commit()
    return {"id": client.id, "enabled": client.enabled}


@router.delete("/download-clients/{client_id}")
def delete_download_client(client_id: int, db: Session = Depends(get_db)):
    client = get_or_404(db, DownloadClient, client_id, "Client introuvable")
    db.delete(client)
    db.commit()
    return {"status": "deleted"}


@router.post("/test/download-client")
async def test_download_client(body: TestDownloadClientBody):
    ok, msg = await check_client_connection(body.client_type, body.url, body.username, body.password)
    return {"success": ok, "message": msg}


# Cache en mémoire pour la recherche Prowlarr (60 minutes)
# clé: (query, media_type, instance_id), valeur: (timestamp, results)
_search_cache: dict[tuple[str, str, int | None], tuple[float, list[dict]]] = {}


@router.get("/search")
async def search_prowlarr(
    query: str,
    media_type: str = "movie",
    instance_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Effectue une recherche via Prowlarr avec un cache en mémoire de 60 minutes."""
    cache_key = (query, media_type, instance_id)
    now = time.time()

    if cache_key in _search_cache:
        cached_time, cached_results = _search_cache[cache_key]
        if now - cached_time < 3600:  # 60 minutes
            return cached_results

    # Résolution de l'instance Prowlarr à utiliser
    try:
        inst = _resolve_arr_instance(db, instance_id, "prowlarr")
    except HTTPException:
        raise HTTPException(400, "Aucune instance Prowlarr configurée et active")

    results = await prowlarr.search(
        url=inst.url,
        api_key=inst.api_key,
        query=query,
        media_type=media_type,
        indexer_ids=None,  # utiliser tous les indexeurs par défaut
    )

    # Filtrer et formater pour l'UI
    formatted_results = []
    for r in results:
        formatted_results.append(
            {
                "title": r.get("title"),
                "size": r.get("size"),
                "seeders": r.get("seeders", 0),
                "leechers": r.get("leechers", 0),
                "guid": r.get("guid"),
                "indexerId": r.get("indexerId"),
                "downloadUrl": r.get("downloadUrl") or r.get("magnetUrl"),
                "indexer": r.get("indexer"),
                "protocol": r.get("protocol"),
                "publishDate": r.get("publishDate"),
                "infoUrl": r.get("infoUrl"),
            }
        )

    # Tri par seeders décroissant
    formatted_results.sort(key=lambda x: x["seeders"], reverse=True)

    # Enregistrement dans le cache
    _search_cache[cache_key] = (now, formatted_results)
    return formatted_results


@router.post("/download")
async def download_release(body: DownloadReleaseRequest, db: Session = Depends(get_db)):
    client = get_or_404(db, DownloadClient, body.client_id, "Client de téléchargement introuvable")

    ok, msg, info_hash = await add_torrent_to_client(
        client_type=client.client_type,
        url=client.url,
        username=client.username,
        password=client.password,
        torrent_url_or_magnet=body.torrent_url_or_magnet,
        category=body.category or client.category,
        tags=body.tags or client.tags,
    )

    if not ok:
        raise HTTPException(status_code=500, detail=msg)

    if body.request_id and info_hash:
        req = db.query(MediaRequest).filter(MediaRequest.id == body.request_id).first()
        if req:
            req.download_client_id = client.id
            req.torrent_hash = info_hash
            req.status = "sent_to_arr"
            db.commit()

    return {"success": True, "message": msg, "info_hash": info_hash}


@router.post("/download/file")
async def download_torrent_file(
    file: UploadFile,
    client_id: int,
    category: Optional[str] = None,
    tags: Optional[str] = None,
    request_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Upload d'un fichier .torrent directement vers un client de téléchargement."""
    client = get_or_404(db, DownloadClient, client_id, "Client de téléchargement introuvable")
    torrent_bytes = await file.read()
    ok, msg, info_hash = await add_torrent_file_to_client(
        client_type=client.client_type,
        url=client.url,
        username=client.username,
        password=client.password,
        torrent_bytes=torrent_bytes,
        filename=file.filename or "upload.torrent",
        category=category or client.category,
        tags=tags or client.tags,
    )
    if not ok:
        raise HTTPException(500, msg)
    if request_id and info_hash:
        req = db.query(MediaRequest).filter(MediaRequest.id == request_id).first()
        if req:
            req.download_client_id = client.id
            req.torrent_hash = info_hash
            req.status = "sent_to_arr"
            db.commit()
    return {"success": True, "message": msg, "info_hash": info_hash}


_FRENCH_LANG_NAMES = {"french", "français", "francais"}
_FRENCH_TITLE_WORDS = {"french", "truefrench", "vff", "vf", "vfi", "vfq", "multi"}


def _release_is_french(rel: dict) -> bool:
    """Heuristique VF pour une release : langue « French » déclarée ou marqueur dans le titre."""
    if any((lang or "").lower() in _FRENCH_LANG_NAMES for lang in rel.get("languages", [])):
        return True
    title = (rel.get("title") or "").lower()
    words = set(title.replace(".", " ").replace("-", " ").replace("_", " ").split())
    return bool(words & _FRENCH_TITLE_WORDS)


class ArrGrabRequest(BaseModel):
    media_type: str  # "movie" | "show"
    guid: str
    indexer_id: int
    instance_id: Optional[int] = None
    request_id: Optional[int] = None


@router.get("/arr/releases")
async def arr_interactive_releases(
    media_type: str,
    arr_id: int,
    instance_id: Optional[int] = None,
    episode_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Recherche interactive Sonarr/Radarr : releases déjà scorées (qualité + custom
    format + langue), avec marquage VF. Prioritaire sur Prowlarr (fallback)."""
    arr_type = "radarr" if media_type == "movie" else "sonarr"
    inst = _resolve_arr_instance(db, instance_id, arr_type)
    if media_type == "movie":
        releases = await radarr.get_releases(inst.url, inst.api_key, arr_id)
    else:
        releases = await sonarr.get_releases(inst.url, inst.api_key, series_id=arr_id, episode_id=episode_id)

    for rel in releases:
        rel["is_french"] = _release_is_french(rel)

    # Tri : VF d'abord, puis score custom format, puis seeders.
    releases.sort(key=lambda r: (r["is_french"], r.get("custom_format_score", 0), r.get("seeders", 0)), reverse=True)
    return releases


@router.post("/arr/grab")
async def arr_grab_release(body: ArrGrabRequest, db: Session = Depends(get_db)):
    """Grab d'une release via Sonarr/Radarr : *arr télécharge ET importe (renommage,
    suivi, upgrade ultérieur gérés par *arr)."""
    arr_type = "radarr" if body.media_type == "movie" else "sonarr"
    inst = _resolve_arr_instance(db, body.instance_id, arr_type)
    svc = radarr if body.media_type == "movie" else sonarr
    ok, msg = await svc.grab_release(inst.url, inst.api_key, body.guid, body.indexer_id)
    if not ok:
        raise HTTPException(500, msg)
    if body.request_id:
        req = db.query(MediaRequest).filter(MediaRequest.id == body.request_id).first()
        if req and req.status not in (RequestStatus.available,):
            req.status = RequestStatus.sent_to_arr
            db.commit()
    return {"success": True, "message": msg}


@router.get("/arr/queue")
async def arr_download_queue(db: Session = Depends(get_db)):
    """File d'attente de téléchargement unifiée : agrège les queues de toutes les
    instances Sonarr/Radarr actives (téléchargements gérés par *arr)."""
    instances = db.query(ArrInstance).filter(ArrInstance.enabled).all()
    items = []
    for inst in instances:
        if inst.arr_type == "radarr":
            records = await radarr.get_queue(inst.url, inst.api_key)
        elif inst.arr_type == "sonarr":
            records = await sonarr.get_queue(inst.url, inst.api_key)
        else:
            continue
        for rec in records:
            rec["instance"] = inst.name
            rec["arr_type"] = inst.arr_type
            items.append(rec)
    # Tri : en cours d'abord (progression croissante), terminés/en attente ensuite.
    items.sort(key=lambda x: (x.get("progress") or 0))
    return items


@router.get("/downloads/direct")
async def direct_downloads(db: Session = Depends(get_db)):
    """Torrents poussés en direct-client (hors *arr), suivis via download_client_id +
    torrent_hash sur les demandes. Complète /arr/queue pour un suivi unifié."""
    from ..services.download_clients import get_torrent_status

    reqs = (
        db.query(MediaRequest)
        .filter(MediaRequest.torrent_hash.isnot(None), MediaRequest.download_client_id.isnot(None))
        .all()
    )
    clients = {c.id: c for c in db.query(DownloadClient).all()}
    out = []
    for req in reqs:
        client = clients.get(req.download_client_id)
        if not client or not client.enabled:
            continue
        try:
            st = await get_torrent_status(
                client.client_type, client.url, client.username, client.password, req.torrent_hash
            )
        except Exception:
            st = None
        if not st:
            continue
        progress = round(st.get("progress") or 0, 1)
        eta = st.get("eta") or 0
        if progress >= 100 or eta <= 0:
            timeleft = "—"
        else:
            h, m = eta // 3600, (eta % 3600) // 60
            timeleft = f"{h}h {m}m" if h else f"{m}m"
        out.append(
            {
                "title": req.title + (f" ({req.year})" if req.year else ""),
                "status": "completed" if progress >= 100 else "downloading",
                "progress": progress,
                "size": None,
                "sizeleft": None,
                "timeleft": timeleft,
                "download_client": client.name,
                "indexer": None,
                "instance": client.name,
                "arr_type": "direct",
                "error": None,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Authentification Plex SSO (OAuth)
# ---------------------------------------------------------------------------


@router.post("/plex/sso/pin")
async def plex_sso_pin(request: Request):
    """Crée une demande de PIN Plex SSO et retourne l'URL d'authentification."""
    from ..services.plex_api import get_auth_pin

    try:
        # Reconstruit l'URL de base en respectant X-Forwarded-Proto (reverse proxy HTTPS)
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.url.netloc)
        forward_url = f"{scheme}://{host}/settings"
        return await get_auth_pin(forward_url=forward_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur d'initialisation SSO Plex : {str(e)}")


@router.get("/plex/sso/check/{pin_id}")
async def plex_sso_check(pin_id: int):
    """Vérifie si le PIN Plex a été validé et retourne le token."""
    from ..services.plex_api import check_auth_pin

    try:
        token = await check_auth_pin(pin_id)
        return {"authenticated": bool(token), "token": token}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Tests de connectivité
# ---------------------------------------------------------------------------


@router.post("/test/plex-api")
async def test_plex_api(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s:
        return {"success": False, "message": "Paramètres non initialisés"}
    ok, msg = await plex_test(s.plex_url or "", s.plex_token or "", verify_ssl=s.plex_verify_ssl)
    return {"success": ok, "message": msg}


@router.post("/test/plex-rss")
async def test_plex_rss(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s:
        return {"success": False, "message": "Paramètres non initialisés"}
    ok, msg = await test_rss(s.plex_rss_url or "")
    return {"success": ok, "message": msg}


@router.post("/test/sonarr")
async def test_sonarr(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s:
        return {"success": False, "message": "Paramètres non initialisés"}
    ok, msg = await sonarr.check_connection(s.sonarr_url or "", s.sonarr_api_key or "")
    return {"success": ok, "message": msg}


@router.post("/test/radarr")
async def test_radarr(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s:
        return {"success": False, "message": "Paramètres non initialisés"}
    ok, msg = await radarr.check_connection(s.radarr_url or "", s.radarr_api_key or "")
    return {"success": ok, "message": msg}


@router.post("/test/discord")
async def test_discord(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s or not s.discord_webhook_url:
        return {"success": False, "message": "Webhook Discord non configuré"}
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(s.discord_webhook_url, json={"content": "Test Plexarr — Discord OK !"})
            r.raise_for_status()
        return {"success": True, "message": "Message Discord envoyé !"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/test/telegram")
async def test_telegram(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s or not s.telegram_bot_token or not s.telegram_chat_id:
        return {"success": False, "message": "Telegram non configuré"}
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
                json={"chat_id": s.telegram_chat_id, "text": "Test Plexarr — Telegram OK !"},
            )
            r.raise_for_status()
        return {"success": True, "message": "Message Telegram envoyé !"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/test/ntfy")
async def test_ntfy(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s or not s.ntfy_url:
        return {"success": False, "message": "ntfy non configuré"}
    from ..services.notifications import send_ntfy

    try:
        await send_ntfy(s.ntfy_url, s.ntfy_token, "Test Plexarr", "Test de notification ntfy OK !")
        return {"success": True, "message": "Notification ntfy envoyée !"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/test/gotify")
async def test_gotify(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s or not s.gotify_url or not s.gotify_token:
        return {"success": False, "message": "Gotify non configuré"}
    from ..services.notifications import send_gotify

    try:
        await send_gotify(s.gotify_url, s.gotify_token, "Test Plexarr", "Test de notification Gotify OK !")
        return {"success": True, "message": "Notification Gotify envoyée !"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/test/seer")
async def test_seer(db: Session = Depends(get_db)):
    from ..services.seer import check_connection as seer_test

    s = db.query(Settings).first()
    if not s or not s.seer_url or not s.seer_api_key:
        return {"success": False, "message": "Seer non configuré"}
    ok, msg = await seer_test(s.seer_url, s.seer_api_key)
    return {"success": ok, "message": msg}


class SmtpTestRequest(BaseModel):
    recipient: str


@router.post("/test/smtp")
async def test_smtp(body: SmtpTestRequest, db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    ok, msg = await email_service.test_smtp(s, body.recipient)
    return {"success": ok, "message": msg}


# ---------------------------------------------------------------------------
# Helpers Sonarr / Radarr (pour les selects de configuration)
# ---------------------------------------------------------------------------


async def _arr_call(
    url: Optional[str],
    api_key: Optional[str],
    instance_id: Optional[int],
    arr_type: str,
    db: Session,
    coro_fn,
):
    """Appelle coro_fn(url, api_key) en résolvant l'instance si url/api_key ne sont pas fournis inline."""
    if url and api_key:
        return await coro_fn(url, api_key)
    inst = _resolve_arr_instance(db, instance_id, arr_type)
    return await coro_fn(inst.url, inst.api_key)


def _resolve_arr_instance(db: Session, instance_id: Optional[int], arr_type: str) -> ArrInstance:
    if instance_id is not None:
        inst = db.query(ArrInstance).filter(ArrInstance.id == instance_id, ArrInstance.arr_type == arr_type).first()
        if not inst:
            raise HTTPException(404, f"Instance {instance_id} ({arr_type}) introuvable")
        return inst
    inst = db.query(ArrInstance).filter(ArrInstance.is_default, ArrInstance.arr_type == arr_type).first()
    if not inst:
        # Fallback de compatibilité avec settings globales
        settings = db.query(Settings).first()
        if arr_type == "sonarr" and settings and settings.sonarr_url:
            return ArrInstance(url=settings.sonarr_url, api_key=settings.sonarr_api_key)
        elif arr_type == "radarr" and settings and settings.radarr_url:
            return ArrInstance(
                url=settings.radarr_url,
                api_key=settings.radarr_api_key,
                minimum_availability=settings.radarr_minimum_availability or "released",
            )
        raise HTTPException(400, f"Aucune instance par défaut configurée pour {arr_type}")
    return inst


@router.get("/sonarr/profiles")
async def sonarr_profiles(
    instance_id: Optional[int] = None,
    url: Optional[str] = None,
    api_key: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return await _arr_call(url, api_key, instance_id, "sonarr", db, sonarr.get_quality_profiles)


@router.get("/sonarr/folders")
async def sonarr_folders(
    instance_id: Optional[int] = None,
    url: Optional[str] = None,
    api_key: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return await _arr_call(url, api_key, instance_id, "sonarr", db, sonarr.get_root_folders)


@router.get("/radarr/profiles")
async def radarr_profiles(
    instance_id: Optional[int] = None,
    url: Optional[str] = None,
    api_key: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return await _arr_call(url, api_key, instance_id, "radarr", db, radarr.get_quality_profiles)


@router.get("/radarr/folders")
async def radarr_folders(
    instance_id: Optional[int] = None,
    url: Optional[str] = None,
    api_key: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return await _arr_call(url, api_key, instance_id, "radarr", db, radarr.get_root_folders)


@router.get("/sonarr/tags")
async def sonarr_tags(
    instance_id: Optional[int] = None,
    url: Optional[str] = None,
    api_key: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return await _arr_call(url, api_key, instance_id, "sonarr", db, sonarr.get_tags)


@router.get("/radarr/tags")
async def radarr_tags(
    instance_id: Optional[int] = None,
    url: Optional[str] = None,
    api_key: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return await _arr_call(url, api_key, instance_id, "radarr", db, radarr.get_tags)


# ---------------------------------------------------------------------------
# Utilisateurs Plex
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    plex_user_id: str
    display_name: Optional[str] = None
    custom_name: Optional[str] = None
    plex_email: Optional[str] = None
    notification_email: Optional[str] = None
    enabled: bool = True
    notify_admin: bool = True
    notify_on_request: Optional[bool] = True
    notify_on_available: Optional[bool] = True
    notify_digest: Optional[bool] = False
    notify_vf_movie: Optional[bool] = True
    notify_vf_series: Optional[bool] = True
    notify_vf_anime: Optional[bool] = False
    partial_notify_frequency: Optional[str] = None
    movie_vo_notify: Optional[bool] = None
    movie_vf_notify: Optional[bool] = None
    series_vo_notify_mode: Optional[str] = None
    series_vf_notify_mode: Optional[str] = None
    discord_webhook_url: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    seer_active: Optional[bool] = None
    sonarr_instance_id: Optional[int] = None
    radarr_instance_id: Optional[int] = None


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    return db.query(PlexUser).all()


@router.get("/users/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db)):
    """Détail complet d'un utilisateur + ses stats de demandes (pour la modale hub)."""
    user = get_or_404(db, PlexUser, user_id, "User not found")
    rows = db.query(MediaRequest.status, MediaRequest.requested_at).filter(
        MediaRequest.plex_user_id == user.plex_user_id
    ).all()
    stats = {"total": 0, "available": 0, "failed": 0, "sent": 0, "pending": 0, "last_requested_at": None}
    for status, req_at in rows:
        stats["total"] += 1
        s = status.value if hasattr(status, "value") else str(status)
        if s in stats:
            stats[s] += 1
        if req_at and (stats["last_requested_at"] is None or req_at > stats["last_requested_at"]):
            stats["last_requested_at"] = req_at
    data = {c.name: getattr(user, c.name) for c in user.__table__.columns}
    data["last_requested_at"] = _format_datetime(stats.pop("last_requested_at"))
    data["stats"] = stats
    return data


@router.post("/users")
def create_user(data: UserCreate, db: Session = Depends(get_db)):
    payload = data.model_dump()
    _validate_series_notify_modes(payload)
    existing = db.query(PlexUser).filter(PlexUser.plex_user_id == data.plex_user_id).first()
    if existing:
        raise HTTPException(409, "User already exists")
    user = PlexUser(**payload)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/users/{user_id}")
def update_user(user_id: int, data: UserCreate, db: Session = Depends(get_db)):
    user = get_or_404(db, PlexUser, user_id, "User not found")
    payload = data.model_dump()
    _validate_series_notify_modes(payload)
    for k, v in payload.items():
        setattr(user, k, v)
    # Propager le nouveau display_name sur les demandes existantes
    resolved = data.display_name or user.plex_user_id
    db.query(MediaRequest).filter(MediaRequest.plex_user_id == user.plex_user_id).update({"plex_user": resolved})
    db.commit()
    return user


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = get_or_404(db, PlexUser, user_id, "User not found")
    db.delete(user)
    db.commit()
    return {"status": "deleted"}


@router.post("/seer/sync/users")
async def seer_sync_users():
    """Synchronise uniquement les liaisons utilisateurs Plex ↔ Seer."""
    from ..scheduler import sync_seer_users

    await sync_seer_users()
    return {"status": "ok"}


@router.post("/seer/sync/requests")
async def seer_sync_requests():
    """Synchronise uniquement les demandes Seer (titres, statuts, historique)."""
    from ..scheduler import sync_seer_requests

    await sync_seer_requests()
    return {"status": "ok"}


@router.post("/seer/sync")
async def seer_sync():
    """Déclenche manuellement la synchronisation Seer complète : utilisateurs + demandes."""
    from ..scheduler import sync_seer_requests, sync_seer_users

    await sync_seer_users()
    await sync_seer_requests()
    return {"status": "ok"}


@router.get("/seer/users")
async def list_seer_users(db: Session = Depends(get_db)):
    """Retourne la liste des utilisateurs Seer avec leur statut de liaison."""
    from ..services.seer import get_users as seer_get_users

    s = db.query(Settings).first()
    if not s or not s.seer_enabled or not s.seer_url or not s.seer_api_key:
        return {"seer_users": [], "error": "Seer non configuré"}

    seer_users = await seer_get_users(s.seer_url, s.seer_api_key)
    linked_ids = {u.seer_user_id for u in db.query(PlexUser).filter(PlexUser.seer_user_id.isnot(None)).all()}

    result = []
    for email, info in seer_users.items():
        result.append(
            {
                "id": info["id"],
                "email": email,
                "display_name": info["display_name"],
                "plex_username": info.get("plex_username", ""),
                "plex_id": info.get("plex_id"),
                "user_type": info.get("user_type", 1),
                "request_count": info["request_count"],
                "linked": info["id"] in linked_ids,
            }
        )
    result.sort(key=lambda x: (x["display_name"] or x["email"]).lower())
    return {"seer_users": result}


@router.put("/users/{user_id}/seer-link")
def link_seer_user(user_id: int, data: dict, db: Session = Depends(get_db)):
    """Lie manuellement un PlexUser à un compte Seer."""
    user = get_or_404(db, PlexUser, user_id, "User not found")
    seer_id = data.get("seer_user_id")
    seer_email = data.get("seer_email")
    if seer_id is None:
        raise HTTPException(400, "seer_user_id requis")
    user.seer_user_id = int(seer_id)
    if seer_email and not user.plex_email:
        user.plex_email = seer_email
    # Liaison Seer = désactiver les emails par défaut (Seer gère ses propres notifs)
    user.notify_on_request = False
    user.notify_on_available = False
    db.commit()
    return {"status": "linked", "seer_user_id": user.seer_user_id}


@router.delete("/users/{user_id}/seer-link")
def unlink_seer_user(user_id: int, db: Session = Depends(get_db)):
    """Supprime la liaison Seer d'un PlexUser."""
    user = get_or_404(db, PlexUser, user_id, "User not found")
    user.seer_user_id = None
    user.seer_active = None
    db.commit()
    return {"status": "unlinked"}


@router.post("/users/{user_id}/seer-automatch")
async def seer_automatch_user(user_id: int, db: Session = Depends(get_db)):
    """Lance l'automatch Seer (3 passes) pour un seul utilisateur."""
    from ..models import MediaRequest as MR
    from ..services.seer import get_user_requests as seer_get_user_requests
    from ..services.seer import get_users as seer_get_users

    user = get_or_404(db, PlexUser, user_id, "User not found")
    s = db.query(Settings).first()
    if not s or not s.seer_url or not s.seer_api_key:
        raise HTTPException(400, "Seer non configuré")

    seer_users = await seer_get_users(s.seer_url, s.seer_api_key)
    if not seer_users:
        return {"matched": False, "method": None}

    matched_ids = {
        u.seer_user_id
        for u in db.query(PlexUser).filter(PlexUser.id != user_id, PlexUser.seer_user_id.isnot(None)).all()
    }
    by_plex_username = {
        (info.get("plex_username") or "").lower().strip(): info
        for info in seer_users.values()
        if info.get("plex_username")
    }

    info = None
    method = None

    email = (user.plex_email or "").lower().strip()
    if email and email in seer_users:
        cand = seer_users[email]
        if cand["id"] not in matched_ids:
            info, method = cand, "email"

    if not info:
        name = (user.display_name or "").lower().strip()
        if name and name in by_plex_username:
            cand = by_plex_username[name]
            if cand["id"] not in matched_ids:
                info, method = cand, "plex_username"

    if not info:
        rows = db.query(MR.tmdb_id).filter(MR.plex_user_id == user.plex_user_id, MR.tmdb_id.isnot(None)).all()
        user_tmdb_ids = {r[0] for r in rows}
        if len(user_tmdb_ids) >= 2:
            best_count = 0
            for seer_info in seer_users.values():
                if seer_info["id"] in matched_ids:
                    continue
                reqs = await seer_get_user_requests(s.seer_url, s.seer_api_key, seer_info["id"])
                common = len(user_tmdb_ids & {r["tmdb_id"] for r in reqs if r.get("tmdb_id")})
                if common >= 2 and common > best_count:
                    best_count, info = common, seer_info
                    method = f"media/{common}"

    if info:
        user.seer_user_id = info["id"]
        user.seer_active = info["request_count"] > 0
        db.commit()
        return {"matched": True, "method": method, "seer_user_id": info["id"], "display_name": info["display_name"]}

    return {"matched": False, "method": None}


@router.post("/users/{seer_only_id}/merge-into/{target_id}")
def merge_seer_only_into_rss(seer_only_id: int, target_id: int, db: Session = Depends(get_db)):
    """Fusionne un utilisateur Seer-only vers un utilisateur RSS existant.

    - Copie seer_user_id + seer_active sur le user cible
    - Réattribue les MediaRequest du user seer-only vers le user cible
    - Supprime l'entrée seer-only
    """
    seer_user = get_or_404(db, PlexUser, seer_only_id, "Utilisateur Seer-only introuvable")
    if seer_user.source != "seer":
        raise HTTPException(400, "Cet utilisateur n'est pas un utilisateur Seer-only")

    target = get_or_404(db, PlexUser, target_id, "Utilisateur cible introuvable")
    if target.source == "seer":
        raise HTTPException(400, "La cible ne peut pas être un utilisateur Seer-only")

    # Transférer la liaison Seer
    target.seer_user_id = seer_user.seer_user_id
    target.seer_active = seer_user.seer_active

    # Réattribuer les demandes
    old_pid = seer_user.plex_user_id
    new_pid = target.plex_user_id
    new_name = target.custom_name or target.display_name or new_pid
    requests_moved = (
        db.query(MediaRequest)
        .filter(MediaRequest.plex_user_id == old_pid)
        .update({"plex_user_id": new_pid, "plex_user": new_name})
    )

    db.delete(seer_user)
    db.commit()

    return {
        "status": "merged",
        "requests_moved": requests_moved,
        "target_plex_user_id": new_pid,
        "seer_user_id": target.seer_user_id,
    }


@router.put("/users/{user_id}/custom-name")
def update_custom_name(user_id: int, data: dict, db: Session = Depends(get_db)):
    """Met à jour le nom d'usage personnalisé d'un utilisateur."""
    user = get_or_404(db, PlexUser, user_id, "User not found")
    user.custom_name = data.get("custom_name") or None
    db.commit()
    return {"status": "ok", "custom_name": user.custom_name}


@router.post("/users/{user_id}/seer-complete")
async def seer_complete_user(user_id: int, db: Session = Depends(get_db)):
    """Complète les infos d'un PlexUser depuis son compte Seer lié.

    Copie : display_name Seer → custom_name (si vide), email Seer → plex_email (si vide).
    """
    user = get_or_404(db, PlexUser, user_id, "User not found")
    if not user.seer_user_id:
        raise HTTPException(400, "Utilisateur non lié à Seer")
    s = db.query(Settings).first()
    if not s or not s.seer_url or not s.seer_api_key:
        raise HTTPException(400, "Seer non configuré")

    from ..services.seer import get_users as seer_get_users

    seer_users = await seer_get_users(s.seer_url, s.seer_api_key)
    seer_email = None
    seer_info = None
    for email, info in seer_users.items():
        if info["id"] == user.seer_user_id:
            seer_email = email
            seer_info = info
            break

    if not seer_info:
        raise HTTPException(404, "Compte Seer introuvable (id inconnu)")

    changes: dict = {}
    if seer_info.get("display_name") and not user.custom_name:
        user.custom_name = seer_info["display_name"]
        changes["custom_name"] = user.custom_name
    if seer_email:
        if not user.plex_email:
            user.plex_email = seer_email
            changes["plex_email"] = user.plex_email
        if not user.notification_email:
            user.notification_email = seer_email
            changes["notification_email"] = user.notification_email
    db.commit()
    return {"status": "ok", "changes": changes}


@router.post("/users/discover")
async def discover_users(db: Session = Depends(get_db)):
    """Scanne le flux RSS, auto-crée les nouveaux utilisateurs et retourne un résumé."""
    from ..scheduler import sync_users_from_feed
    from ..services.plex_rss import fetch_watchlist_rss

    s = db.query(Settings).first()
    if not s or not s.plex_rss_url:
        raise HTTPException(400, "URL RSS non configurée")

    known_before = {u.plex_user_id for u in db.query(PlexUser).all()}
    items = await fetch_watchlist_rss(s.plex_rss_url)
    await sync_users_from_feed(items, db)

    all_users = db.query(PlexUser).all()
    new_ids = {u.plex_user_id for u in all_users} - known_before

    return {
        "total": len(all_users),
        "added": len(new_ids),
        "users": [
            {"plex_user_id": u.plex_user_id, "display_name": u.display_name, "enabled": u.enabled} for u in all_users
        ],
    }


# ---------------------------------------------------------------------------
# Santé des services
# ---------------------------------------------------------------------------


@router.get("/onboarding")
def onboarding_status(db: Session = Depends(get_db)):
    """Retourne l'état d'avancement de la configuration initiale (checklist)."""
    s = db.query(Settings).first()
    users_count = db.query(PlexUser).count()
    steps = [
        {"id": "rss", "label": "Flux RSS Plex configuré", "done": bool(s and s.plex_rss_url)},
        {"id": "sonarr", "label": "Sonarr configuré", "done": bool(s and s.sonarr_url and s.sonarr_api_key)},
        {"id": "radarr", "label": "Radarr configuré", "done": bool(s and s.radarr_url and s.radarr_api_key)},
        {"id": "smtp", "label": "Email (SMTP) configuré", "done": bool(s and s.smtp_host)},
        {"id": "users", "label": "Au moins un utilisateur détecté", "done": users_count > 0},
        {
            "id": "webhooks",
            "label": "Webhooks Sonarr/Radarr configurés",
            "done": bool(s and s.sonarr_url),
            "optional": True,
        },
    ]
    return {"steps": steps, "complete": all(s["done"] for s in steps if not s.get("optional"))}


async def _timed_check(coro) -> tuple[bool | None, str, float | None]:
    """Exécute une coroutine de connectivité et retourne (ok, message, latence_ms)."""
    t0 = time.monotonic()
    ok, msg = await coro
    return ok, msg, round((time.monotonic() - t0) * 1000, 1)


@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """État structuré de tous les services connectés avec latences.

    Les vérifications réseau (Sonarr/Radarr/Seer/Plex) sont lancées en parallèle :
    le temps total est celui du service le plus lent, pas la somme de tous.
    """
    s = db.query(Settings).first()
    not_configured = {"ok": None, "message": "Non configuré", "response_ms": None}

    checks: dict[str, tuple] = {}
    if s and s.sonarr_url and s.sonarr_api_key:
        checks["sonarr"] = ("failed", _timed_check(sonarr.check_connection(s.sonarr_url, s.sonarr_api_key)))
    if s and s.radarr_url and s.radarr_api_key:
        checks["radarr"] = ("failed", _timed_check(radarr.check_connection(s.radarr_url, s.radarr_api_key)))
    if s and s.seer_url and s.seer_api_key:
        checks["seer"] = ("degraded", _timed_check(seer_test(s.seer_url, s.seer_api_key)))
    if s and s.plex_url and s.plex_token:
        checks["plex"] = ("failed", _timed_check(plex_test(s.plex_url, s.plex_token, verify_ssl=s.plex_verify_ssl)))

    results = dict(zip(checks.keys(), await asyncio.gather(*(coro for _, coro in checks.values()))))

    services: dict[str, dict] = {}
    failed = 0
    degraded = 0
    for name in ("sonarr", "radarr", "seer", "plex"):
        if name not in checks:
            services[name] = not_configured
            continue
        severity, _ = checks[name]
        ok, msg, ms = results[name]
        services[name] = {"ok": ok, "message": msg, "response_ms": ms}
        if not ok:
            if severity == "degraded":
                degraded += 1
            else:
                failed += 1

    # SMTP & RSS — pas de test réseau, on vérifie juste la configuration
    services["smtp"] = {
        "ok": bool(s and s.smtp_host),
        "message": "Configuré" if s and s.smtp_host else "Non configuré",
        "response_ms": None,
    }
    services["rss"] = {
        "ok": bool(s and s.plex_rss_url),
        "message": "Configuré" if s and s.plex_rss_url else "Non configuré",
        "response_ms": None,
    }

    if failed > 0:
        overall = "down"
    elif degraded > 0:
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "status": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "services": services,
    }


# ---------------------------------------------------------------------------
# Statistiques
# ---------------------------------------------------------------------------


@router.get("/stats/timeline")
def stats_timeline(db: Session = Depends(get_db)):
    """Retourne le nombre de demandes par jour sur les 30 derniers jours."""
    from sqlalchemy import func

    days = 30
    start = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(
            func.date(MediaRequest.requested_at).label("day"),
            func.count().label("count"),
        )
        .filter(MediaRequest.requested_at >= start)
        .group_by(func.date(MediaRequest.requested_at))
        .all()
    )
    data = {r.day: r.count for r in rows}
    labels, values = [], []
    for i in range(days):
        d = (start + timedelta(days=i + 1)).strftime("%Y-%m-%d")
        labels.append(d)
        values.append(data.get(d, 0))
    return {"labels": labels, "values": values}


@router.get("/stats/by-user")
def stats_by_user(db: Session = Depends(get_db)):
    """Retourne le nombre de demandes par utilisateur, trié par volume décroissant."""
    from sqlalchemy import func

    rows = (
        db.query(MediaRequest.plex_user_id, func.count().label("total"))
        .group_by(MediaRequest.plex_user_id)
        .order_by(func.count().desc())
        .all()
    )
    users = {u.plex_user_id: (u.display_name or u.plex_user_id) for u in db.query(PlexUser).all()}
    return [
        {"plex_user_id": r.plex_user_id, "display_name": users.get(r.plex_user_id, r.plex_user_id), "total": r.total}
        for r in rows
    ]


@router.get("/stats/counts")
def stats_counts(db: Session = Depends(get_db)):
    """Retourne les compteurs par statut, globaux et ventilés par type de média.

    Les clés globales (failed, pending, …) sont conservées pour compatibilité ;
    `by_type` fournit le détail Films (movie) / Séries (show) pour les badges de navigation.
    """
    from sqlalchemy import func

    rows = (
        db.query(MediaRequest.media_type, MediaRequest.status, func.count().label("n"))
        .group_by(MediaRequest.media_type, MediaRequest.status)
        .all()
    )

    def _empty():
        return {"failed": 0, "pending": 0, "sent_to_arr": 0, "available": 0, "total": 0}

    by_type = {"movie": _empty(), "show": _empty()}
    globals_ = _empty()
    for media_type, status, n in rows:
        bucket = by_type.setdefault(media_type, _empty())
        if status in bucket:
            bucket[status] += n
        bucket["total"] += n
        if status in globals_:
            globals_[status] += n
        globals_["total"] += n

    return {**globals_, "by_type": by_type}


@router.get("/vff/counts")
def vff_counts(db: Session = Depends(get_db)):
    """Compteurs VFF sur la bibliothèque : VO en attente de VF, VF obtenues, non analysés."""
    base = db.query(LibraryItem)
    vo_only = base.filter(LibraryItem.has_vf.is_(False)).count()
    vf_ok = base.filter(LibraryItem.has_vf.is_(True)).count()
    unchecked = base.filter(LibraryItem.has_vf.is_(None)).count()
    return {"vo_only": vo_only, "vf_available": vf_ok, "unchecked": unchecked}


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


@router.post("/vff/scan")
async def vff_scan_now(force: bool = False, db: Session = Depends(get_db)):
    """Déclenche immédiatement une analyse VFF en arrière-plan.

    `force=true` : purge tout le cache par épisode ET réinitialise has_vf sur tous les
    médias déjà marqués complets (sinon ils resteraient exclus de l'analyse), pour un
    re-scan intégral depuis zéro — utile si le cache est suspecté d'être obsolète.
    """
    from ..scheduler import _invalidate_vf_cache, check_vf_statuses, vff_scan_state

    if vff_scan_state["status"] == "running":
        return {"status": "already_running"}

    if force:
        _invalidate_vf_cache(db)
        db.query(MediaRequest).filter(MediaRequest.has_vf.is_(True)).update({"has_vf": None})
        db.query(LibraryItem).filter(LibraryItem.has_vf.is_(True)).update({"has_vf": None})
        db.commit()

    asyncio.create_task(check_vf_statuses())
    return {"status": "started"}


@router.get("/vff/scan-status")
def get_vff_scan_status():
    """Retourne l'état actuel de l'analyse VFF en arrière-plan."""
    from ..scheduler import vff_scan_state
    return vff_scan_state


@router.post("/vff/sync-plex")
async def vff_sync_plex():
    """Déclenche immédiatement la synchronisation de la bibliothèque Plex en arrière-plan."""
    from ..scheduler import plex_sync_state, sync_plex_media

    if plex_sync_state["status"] == "running":
        return {"status": "already_running"}

    asyncio.create_task(sync_plex_media())
    return {"status": "started"}


@router.get("/vff/sync-status")
def get_vff_sync_status():
    """Retourne l'état actuel de la synchronisation de la bibliothèque Plex."""
    from ..scheduler import plex_sync_state
    return plex_sync_state


@router.post("/requests/{request_id}/vff-scan")
async def vff_scan_single_request(
    request_id: int,
    force: bool = False,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Déclenche immédiatement une analyse VFF pour une demande spécifique.

    `force=true` purge le cache par épisode avant de scanner, pour re-vérifier des
    épisodes déjà marqués VF (utile si le cache est suspecté d'être obsolète) :
    - sans `season`/`episode`  : toute la série
    - avec `season` seul      : uniquement cette saison
    - avec `season`+`episode` : uniquement cet épisode
    """
    import asyncio

    from ..scheduler import (
        _invalidate_vf_cache,
        _load_known_vf_episodes,
        _notify,
        _notify_vf,
        _parse_vff_libraries,
        _persist_episode_status,
        _trigger_vf_search,
    )
    from ..services import vff as vff_svc

    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    settings = db.query(Settings).first()
    if not settings:
        raise HTTPException(400, "Settings not initialized")
    if not settings.vff_enabled:
        raise HTTPException(400, "VFF tracking is disabled")
    if not settings.plex_url or not settings.plex_token:
        raise HTTPException(400, "Plex is not configured")

    if force:
        _invalidate_vf_cache(db, "request", req.id, season_number=season, episode_number=episode)
        db.commit()

    libs = _parse_vff_libraries(settings)
    if not libs:
        raise HTTPException(400, "No Plex libraries configured for VFF")

    movie_libs = [lib["name"] for lib in libs if lib["kind"] == "movie"]
    show_libs = [(lib["name"], lib["kind"]) for lib in libs if lib["kind"] in ("series", "anime")]
    known_vf = _load_known_vf_episodes(db, "request", [req.id]).get(req.id, {})

    def _scan_single_blocking():
        try:
            plex = vff_svc.connect(settings.plex_url, settings.plex_token)
        except Exception as exc:
            return {"found": False, "error": f"Plex connection error: {exc}"}

        try:
            return vff_svc.scan_media_vf(
                plex, req.media_type, movie_libs, show_libs,
                req.title, req.year, req.tmdb_id, req.tvdb_id, req.imdb_id,
                plex_guid=req.plex_guid,
                known_vf=known_vf,
            )
        except Exception as exc:
            return {"found": False, "error": str(exc)}

    res = await asyncio.to_thread(_scan_single_blocking)
    if not res.get("found"):
        raise HTTPException(404, res.get("error", "Media not found in Plex libraries"))

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    was_tracking = req.has_vf is False
    req.vf_category = res.get("category") or req.vf_category
    req.vf_checked_at = now
    episode_status = res.get("episode_status")
    if episode_status:
        _persist_episode_status(db, "request", req.id, episode_status, now)

    has_vf_new = res["has_vf"]
    if has_vf_new:
        req.has_vf = True
        req.vf_granularity = "full"
        if was_tracking:
            req.vf_available_at = now
            db.commit()
            _notify_vf("vf_available", settings, req, db)
        else:
            db.commit()
            _notify("available", settings, req, db)
    else:
        req.has_vf = False
        req.vf_granularity = vff_svc.compute_vf_granularity(episode_status)
        if not was_tracking:
            if not req.available_mail_sent:
                req.available_mail_sent = True
                db.commit()
                _notify_vf("vo_only", settings, req, db)
            else:
                db.commit()
            if settings.vff_auto_search:
                await _trigger_vf_search(db, settings, req)
        else:
            db.commit()

    # Si la demande est liée à un LibraryItem, on synchronise aussi son has_vf pour
    # éviter de réintroduire un décalage Bibliothèque/Demandes après un scan manuel.
    if req.library_item_id:
        li = db.query(LibraryItem).filter(LibraryItem.id == req.library_item_id).first()
        if li:
            prev_li_vf = li.has_vf
            li.vf_category = req.vf_category or li.vf_category
            li.vf_checked_at = now
            li.has_vf = req.has_vf
            li.vf_granularity = req.vf_granularity
            if li.has_vf and prev_li_vf is False:
                li.vf_available_at = now
            db.commit()

    return {
        "status": "ok",
        "has_vf": req.has_vf,
        "vf_category": req.vf_category,
        "vf_checked_at": _format_datetime(req.vf_checked_at),
    }


@router.post("/requests/{request_id}/vff-ignore")
async def vff_ignore_request(request_id: int, db: Session = Depends(get_db)):
    """Arrête manuellement le suivi VFF pour une demande spécifique (force has_vf = True)."""
    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    req.has_vf = True
    db.commit()
    return {"status": "ok", "has_vf": req.has_vf}


@router.get("/requests/{request_id}/vf-detail")
async def request_vf_detail(request_id: int, db: Session = Depends(get_db)):
    """Détail VF d'une demande (voir _vf_detail_payload)."""
    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    return await _vf_detail_payload(db, req)


@router.get("/library/{item_id}/vf-detail")
async def library_vf_detail(item_id: int, db: Session = Depends(get_db)):
    """Détail VF d'un élément de bibliothèque."""
    item = get_or_404(db, LibraryItem, item_id, "Library item not found")
    return await _vf_detail_payload(db, item)


async def _vf_detail_payload(db: Session, req):
    """Détail VF (modale) : pistes audio (film) ou statut par saison/épisode (série).

    `req` est une demande (MediaRequest) ou un élément de bibliothèque (LibraryItem) —
    seuls les attributs média communs sont utilisés. Pour les séries, croise la liste
    attendue de Sonarr avec la VF réelle détectée dans Plex.
    """
    import asyncio

    from ..scheduler import _load_known_vf_episodes, _parse_vff_libraries, _persist_episode_status
    from ..services import vff as vff_svc
    from ..services.radarr import lookup_movie
    from ..services.sonarr import get_episodes, lookup_series

    settings = db.query(Settings).first()
    if not settings:
        return {"enabled": False}

    source_type = "request" if isinstance(req, MediaRequest) else "library_item"

    # La détection VF (Plex) n'est active que si VFF est configuré. La liste
    # saisons/épisodes (Sonarr) reste disponible indépendamment.
    libs = _parse_vff_libraries(settings)
    vf_detected = bool(settings.vff_enabled and settings.plex_url and settings.plex_token and libs)
    movie_libs = [lib["name"] for lib in libs if lib["kind"] == "movie"]
    show_libs = [lib["name"] for lib in libs if lib["kind"] in ("series", "anime")]

    # ── Film : liste des pistes audio (nécessite Plex + VFF) + date de sortie ──
    if req.media_type == "movie":
        release_date = None
        try:
            radarr_inst = _resolve_arr_instance(db, req.arr_instance_id, "radarr")
            movie_data = await lookup_movie(
                radarr_inst.url, radarr_inst.api_key, arr_id=req.arr_id, tmdb_id=req.tmdb_id, imdb_id=req.imdb_id
            )
            if movie_data:
                release_date = (
                    movie_data.get("inCinemas") or movie_data.get("digitalRelease") or movie_data.get("physicalRelease")
                )
        except Exception as e:
            logger.debug(f"vf-detail: date de sortie Radarr indisponible pour '{req.title}': {e}")

        if not vf_detected:
            return {"enabled": True, "media_type": "movie", "vf_available": False, "release_date": release_date}
        res = await asyncio.to_thread(
            vff_svc.get_movie_audio_detail_blocking,
            settings.plex_url,
            settings.plex_token,
            movie_libs,
            req.title,
            req.year,
            req.tmdb_id,
            req.tvdb_id,
            req.imdb_id,
        )
        return {"enabled": True, "media_type": "movie", "vf_available": True, "release_date": release_date, **res}

    # ── Série : Sonarr (liste attendue) + Plex (VF réelle, si VFF actif) ────────
    # known_vf : épisodes déjà confirmés VF lors d'un scan précédent (scheduler ou
    # ouverture de modale antérieure) — ils ne sont pas re-scannés dans Plex ici.
    known_vf = _load_known_vf_episodes(db, source_type, [req.id]).get(req.id, {})
    plex_task = (
        asyncio.to_thread(
            vff_svc.get_show_episode_vf_blocking,
            settings.plex_url,
            settings.plex_token,
            show_libs,
            req.title,
            req.year,
            req.tmdb_id,
            req.tvdb_id,
            req.imdb_id,
            known_vf,
        )
        if vf_detected
        else None
    )

    sonarr_episodes = None
    first_aired = None
    next_episode_at = None
    try:
        inst = _resolve_arr_instance(db, req.arr_instance_id, "sonarr")
        # Résolution de l'ID série Sonarr : on privilégie le tvdb_id (fiable quelle que
        # soit la source). req.arr_id n'est utilisable que pour les demandes non-Seer
        # (pour Seer, arr_id désigne l'ID de la demande Seer, pas la série Sonarr).
        series_id = None
        data = None
        if req.tvdb_id:
            data = await lookup_series(inst.url, inst.api_key, tvdb_id=req.tvdb_id)
            series_id = data.get("id") if data else None
        if not series_id and getattr(req, "source", None) != "seer" and req.arr_id:
            series_id = req.arr_id
            data = data or await lookup_series(inst.url, inst.api_key, arr_id=series_id)
        if data:
            first_aired = data.get("firstAired")
            next_episode_at = data.get("nextAiring")
        if series_id:
            sonarr_episodes = await get_episodes(inst.url, inst.api_key, series_id)
    except Exception as e:
        logger.warning(f"vf-detail: liste épisodes Sonarr indisponible pour '{req.title}': {e}")

    plex_res = await plex_task if plex_task else {}
    plex_eps = plex_res.get("episodes", {}) if plex_res.get("found") else {}
    if plex_eps:
        _persist_episode_status(db, source_type, req.id, plex_eps, datetime.now(timezone.utc).replace(tzinfo=None))
        db.commit()

    def _status(in_plex, has_file):
        if vf_detected:
            if in_plex is True:
                return "vf"
            if in_plex is False:
                return "vo"
            if has_file:
                return "unknown"  # fichier présent mais VF non détectée dans Plex
            return "absent"
        # VFF inactif : on distingue seulement présent / manquant
        return "present" if has_file else "absent"

    seasons: dict[int, dict[int, dict]] = {}
    if sonarr_episodes:
        # Source de vérité pour la liste attendue : Sonarr (épisodes suivis)
        for ep in sonarr_episodes:
            if not ep.get("monitored", True):
                continue
            sn = ep.get("seasonNumber")
            en = ep.get("episodeNumber")
            if sn is None or en is None or sn == 0:  # ignore les specials (saison 0)
                continue
            status = _status(plex_eps.get(sn, {}).get(en), ep.get("hasFile"))
            seasons.setdefault(sn, {})[en] = {"episode": en, "title": ep.get("title") or "", "status": status}
    else:
        # Fallback Plex seul (Sonarr indisponible) : seulement les épisodes présents
        for sn, eps in plex_eps.items():
            if sn == 0:
                continue
            for en, has_vf in eps.items():
                seasons.setdefault(sn, {})[en] = {
                    "episode": en,
                    "title": "",
                    "status": "vf" if has_vf else "vo",
                }

    out_seasons = []
    for sn in sorted(seasons):
        eps = [seasons[sn][en] for en in sorted(seasons[sn])]
        counts = {"vf": 0, "vo": 0, "present": 0, "absent": 0, "unknown": 0}
        for e in eps:
            counts[e["status"]] = counts.get(e["status"], 0) + 1
        out_seasons.append({"season_number": sn, "counts": counts, "episodes": eps})

    return {
        "enabled": True,
        "media_type": "show",
        "vf_available": vf_detected,
        "found": bool(plex_res.get("found")) or bool(sonarr_episodes),
        "sonarr_available": sonarr_episodes is not None,
        "first_aired": first_aired,
        "next_episode_at": next_episode_at,
        "seasons": out_seasons,
    }


@router.get("/library/{item_id}")
def get_library_item(item_id: int, db: Session = Depends(get_db)):
    """Détail d'un élément de bibliothèque (pour la modale : identité + lien *arr)."""
    item = get_or_404(db, LibraryItem, item_id, "Library item not found")
    return {
        "id": item.id,
        "title": item.title,
        "year": item.year,
        "media_type": item.media_type,
        "has_vf": item.has_vf,
        "arr_id": item.arr_id,
        "arr_instance_id": item.arr_instance_id,
        "arr_slug": item.arr_slug,
    }


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
    request_payloads = [_request_summary_payload(req, users) for req in related_requests]
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
            "added_at": _format_datetime(library_item.added_at) if library_item else None,
        },
        "requests": request_payloads,
        "timeline": schedule["timeline"],
        "calendar": schedule["events"],
    }


@router.post("/library/{item_id}/vff-scan")
async def library_vff_scan(
    item_id: int,
    force: bool = False,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Analyse VFF immédiate d'un élément de bibliothèque (met à jour son état VF).

    `force=true` purge le cache par épisode avant de scanner (voir `vff_scan_single_request`
    pour la portée `season`/`episode`).
    """
    import asyncio

    from ..scheduler import (
        _invalidate_vf_cache,
        _load_known_vf_episodes,
        _parse_vff_libraries,
        _persist_episode_status,
    )
    from ..services import vff as vff_svc

    item = get_or_404(db, LibraryItem, item_id, "Library item not found")
    settings = db.query(Settings).first()
    if not settings or not settings.vff_enabled:
        raise HTTPException(400, "VFF tracking is disabled")
    if not settings.plex_url or not settings.plex_token:
        raise HTTPException(400, "Plex is not configured")

    if force:
        _invalidate_vf_cache(db, "library_item", item.id, season_number=season, episode_number=episode)
        db.commit()

    libs = _parse_vff_libraries(settings)
    if not libs:
        raise HTTPException(400, "No Plex libraries configured for VFF")
    movie_libs = [lib["name"] for lib in libs if lib["kind"] == "movie"]
    show_libs = [(lib["name"], lib["kind"]) for lib in libs if lib["kind"] in ("series", "anime")]
    known_vf = _load_known_vf_episodes(db, "library_item", [item.id]).get(item.id, {})

    def _blocking():
        try:
            plex = vff_svc.connect(settings.plex_url, settings.plex_token)
        except Exception as exc:
            return {"found": False, "error": f"Plex connection error: {exc}"}
        try:
            return vff_svc.scan_media_vf(
                plex, item.media_type, movie_libs, show_libs,
                item.title, item.year, item.tmdb_id, item.tvdb_id, item.imdb_id,
                plex_guid=item.plex_guid,
                known_vf=known_vf,
            )
        except Exception as exc:
            return {"found": False, "error": str(exc)}

    res = await asyncio.to_thread(_blocking)
    if not res.get("found"):
        raise HTTPException(404, res.get("error", "Media not found in Plex libraries"))

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    prev = item.has_vf
    item.vf_category = res.get("category") or item.vf_category
    item.vf_checked_at = now
    item.has_vf = bool(res["has_vf"])
    item.vf_granularity = "full" if item.has_vf else vff_svc.compute_vf_granularity(res.get("episode_status"))
    if item.has_vf and prev is False:
        item.vf_available_at = now
    item.updated_at = now
    episode_status = res.get("episode_status")
    if episode_status:
        _persist_episode_status(db, "library_item", item.id, episode_status, now)
    db.commit()
    return {"status": "ok", "has_vf": item.has_vf, "vf_category": item.vf_category}


@router.post("/library/{item_id}/vff-ignore")
async def library_vff_ignore(item_id: int, db: Session = Depends(get_db)):
    """Arrête le suivi VFF d'un élément de bibliothèque (force has_vf = True)."""
    item = get_or_404(db, LibraryItem, item_id, "Library item not found")
    item.has_vf = True
    item.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return {"status": "ok", "has_vf": item.has_vf}


@router.get("/stats/top-requested")
def stats_top_requested(db: Session = Depends(get_db), limit: int = 5):
    """Retourne les demandes ayant le plus de co-demandeurs (les plus réclamées)."""
    rows = (
        db.query(MediaRequest)
        .filter(MediaRequest.extra_requesters.isnot(None), MediaRequest.extra_requesters != "[]")
        .all()
    )
    items = []
    for r in rows:
        extras = _json.loads(r.extra_requesters or "[]")
        count = 1 + len(extras)
        if count < 2:
            continue
        items.append(
            {
                "id": r.id,
                "title": r.title,
                "media_type": r.media_type,
                "poster_url": r.poster_url,
                "status": r.status,
                "count": count,
            }
        )
    items.sort(key=lambda i: cast(int, i["count"]), reverse=True)
    return items[:limit]


@router.get("/disk-space")
async def disk_space(db: Session = Depends(get_db)):
    """Retourne l'espace disque des volumes Sonarr/Radarr, dédupliqué par chemin."""
    s = db.query(Settings).first()
    volumes: dict[str, dict] = {}

    async def add(label: str, coro):
        try:
            for d in await coro:
                key = d["path"]
                if key not in volumes:
                    volumes[key] = {**d, "sources": [label]}
                elif label not in volumes[key]["sources"]:
                    volumes[key]["sources"].append(label)
        except Exception:
            pass

    if s and s.sonarr_url and s.sonarr_api_key:
        await add("Sonarr", sonarr.get_disk_space(s.sonarr_url, s.sonarr_api_key))
    if s and s.radarr_url and s.radarr_api_key:
        await add("Radarr", radarr.get_disk_space(s.radarr_url, s.radarr_api_key))

    return list(volumes.values())


@router.get("/upcoming")
def upcoming_releases(db: Session = Depends(get_db), limit: int = 8):
    """Retourne les prochaines sorties parmi les demandes transmises mais pas encore disponibles.

    Lecture base de données uniquement : `next_release_at`/`next_release_label` sont
    alimentés en arrière-plan par le job `check_arr_statuses` (toutes les 15 min),
    pas d'appel réseau ici — le dashboard reste rapide même avec beaucoup de demandes.
    """
    rows = (
        db.query(MediaRequest)
        .filter(
            MediaRequest.status == RequestStatus.sent_to_arr,
            MediaRequest.next_release_at.isnot(None),
            MediaRequest.next_release_at > datetime.now(timezone.utc).replace(tzinfo=None),
        )
        .order_by(MediaRequest.next_release_at.asc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "title": r.title,
            "media_type": r.media_type,
            "poster_url": r.poster_url,
            "release_date": r.next_release_at.isoformat(),
            "label": r.next_release_label,
        }
        for r in rows
    ]


@router.get("/calendar")
async def unified_calendar(
    start: Optional[str] = None,
    end: Optional[str] = None,
    tracked_only: bool = False,
    type: Optional[str] = None,
    search: Optional[str] = None,
    user: Optional[str] = None,
    status: Optional[str] = None,
    vf: Optional[str] = None,
    source: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Calendrier unifié : épisodes Sonarr + sorties Radarr sur une plage de dates.

    Croise chaque entrée avec nos LibraryItem/MediaRequest (par tvdb_id/tmdb_id) pour
    marquer les médias suivis et réutiliser leur affiche déjà connue (pas d'appel
    supplémentaire aux images Sonarr/Radarr). `tracked_only=true` ne garde que les
    médias suivis (utilisé par l'onglet Calendrier de la Bibliothèque).

    Par défaut : 7 jours avant aujourd'hui à 21 jours après (contexte + à venir).
    """
    now = datetime.now(timezone.utc)
    start_dt = datetime.fromisoformat(start) if start else now - timedelta(days=7)
    end_dt = datetime.fromisoformat(end) if end else now + timedelta(days=21)

    # Index des médias suivis par identifiant externe, pour marquer/enrichir les entrées.
    shows_by_tvdb: dict[str, dict] = {}
    movies_by_tmdb: dict[str, dict] = {}
    library_items_by_id = {}

    for li in db.query(LibraryItem).all():
        entry = {
            "in_library": True,
            "library_item_id": li.id,
            "request_id": None,
            "request_status": None,
            "requested_by_ids": [],
            "request_sources": [],
            "has_vf": li.has_vf,
            "poster_url": li.poster_url,
        }
        library_items_by_id[li.id] = entry
        if li.media_type == "show" and li.tvdb_id:
            shows_by_tvdb[li.tvdb_id] = entry
        elif li.media_type == "movie" and li.tmdb_id:
            movies_by_tmdb[li.tmdb_id] = entry

    for r in db.query(MediaRequest).all():
        matched = library_items_by_id.get(r.library_item_id) if r.library_item_id else None
        if not matched:
            if r.media_type == "show" and r.tvdb_id:
                matched = shows_by_tvdb.get(r.tvdb_id)
            elif r.media_type == "movie" and r.tmdb_id:
                matched = movies_by_tmdb.get(r.tmdb_id)

        status_val = r.status.value if hasattr(r.status, "value") else str(r.status)
        requester_ids = [r.plex_user_id] if r.plex_user_id else []
        try:
            for extra in _json.loads(r.extra_requesters or "[]"):
                uid = extra.get("plex_user_id")
                if uid and uid not in requester_ids:
                    requester_ids.append(uid)
        except Exception:
            pass

        if matched:
            matched["request_id"] = r.id
            matched["request_status"] = status_val
            matched["requested_by_ids"] = list(set(matched["requested_by_ids"] + requester_ids))
            if r.source and r.source not in matched["request_sources"]:
                matched["request_sources"].append(r.source)
        else:
            entry = {
                "in_library": False,
                "library_item_id": None,
                "request_id": r.id,
                "request_status": status_val,
                "requested_by_ids": requester_ids,
                "request_sources": [r.source] if r.source else [],
                "has_vf": r.has_vf,
                "poster_url": r.poster_url,
            }
            if r.media_type == "show" and r.tvdb_id:
                shows_by_tvdb[r.tvdb_id] = entry
            elif r.media_type == "movie" and r.tmdb_id:
                movies_by_tmdb[r.tmdb_id] = entry

    instances = db.query(ArrInstance).filter(ArrInstance.enabled, ArrInstance.arr_type.in_(["sonarr", "radarr"])).all()
    events = []
    for inst in instances:
        try:
            if inst.arr_type == "sonarr":
                episodes = await sonarr.get_calendar(inst.url, inst.api_key, start_dt.isoformat(), end_dt.isoformat())
                for ep in episodes:
                    date = ep.get("airDateUtc")
                    if not date:
                        continue
                    series = ep.get("series") or {}
                    tvdb_id = str(series.get("tvdbId")) if series.get("tvdbId") else None
                    tracked = shows_by_tvdb.get(tvdb_id) if tvdb_id else None
                    if tracked_only and not tracked:
                        continue

                    # Filtres
                    if type == "movie":
                        continue
                    if search and search.lower() not in (series.get("title") or "").lower():
                        continue
                    if user and (not tracked or user not in tracked.get("requested_by_ids", [])):
                        continue
                    if status and (not tracked or tracked.get("request_status") != status):
                        continue
                    if source and (not tracked or source not in tracked.get("request_sources", [])):
                        continue
                    if vf:
                        if not tracked:
                            continue
                        if vf == "vf" and not (tracked.get("in_library") and tracked.get("has_vf") is True):
                            continue
                        elif vf == "vo" and not (tracked.get("in_library") and tracked.get("has_vf") is False):
                            continue
                        elif vf == "unchecked" and not (tracked.get("in_library") and tracked.get("has_vf") is None):
                            continue
                        elif vf == "requested" and tracked.get("in_library"):
                            continue

                    events.append({
                        "type": "episode",
                        "date": date,
                        "title": series.get("title") or "",
                        "subtitle": f"S{ep.get('seasonNumber', 0):02d}E{ep.get('episodeNumber', 0):02d}"
                        + (f" — {ep.get('title')}" if ep.get("title") else ""),
                        "poster_url": (tracked or {}).get("poster_url"),
                        "has_file": bool(ep.get("hasFile")),
                        "tracked": bool(tracked),
                        "library_item_id": (tracked or {}).get("library_item_id"),
                        "request_id": (tracked or {}).get("request_id"),
                        "instance": inst.name,
                    })
            else:
                movies = await radarr.get_calendar(inst.url, inst.api_key, start_dt.isoformat(), end_dt.isoformat())
                for m in movies:
                    date = m.get("inCinemas") or m.get("digitalRelease") or m.get("physicalRelease")
                    if not date:
                        continue
                    tmdb_id = str(m.get("tmdbId")) if m.get("tmdbId") else None
                    tracked = movies_by_tmdb.get(tmdb_id) if tmdb_id else None
                    if tracked_only and not tracked:
                        continue

                    # Filtres
                    if type == "show":
                        continue
                    title = m.get("title") or ""
                    if search and search.lower() not in title.lower():
                        continue
                    if user and (not tracked or user not in tracked.get("requested_by_ids", [])):
                        continue
                    if status and (not tracked or tracked.get("request_status") != status):
                        continue
                    if source and (not tracked or source not in tracked.get("request_sources", [])):
                        continue
                    if vf:
                        if not tracked:
                            continue
                        if vf == "vf" and not (tracked.get("in_library") and tracked.get("has_vf") is True):
                            continue
                        elif vf == "vo" and not (tracked.get("in_library") and tracked.get("has_vf") is False):
                            continue
                        elif vf == "unchecked" and not (tracked.get("in_library") and tracked.get("has_vf") is None):
                            continue
                        elif vf == "requested" and tracked.get("in_library"):
                            continue

                    events.append({
                        "type": "movie",
                        "date": date,
                        "title": title,
                        "subtitle": "Sortie",
                        "poster_url": (tracked or {}).get("poster_url"),
                        "has_file": bool(m.get("hasFile")),
                        "tracked": bool(tracked),
                        "library_item_id": (tracked or {}).get("library_item_id"),
                        "request_id": (tracked or {}).get("request_id"),
                        "instance": inst.name,
                    })
        except Exception as e:
            logger.warning(f"Calendar fetch failed for '{inst.name}': {e}")

    events.sort(key=lambda e: e["date"])
    return events


@router.get("/metrics")
def get_metrics(db: Session = Depends(get_db)):
    """Métriques runtime (session courante) + agrégats DB (total historique).

    Les compteurs runtime se réinitialisent au redémarrage du serveur.
    Les agrégats DB reflètent l'ensemble de l'historique.
    """
    from sqlalchemy import func

    # Agrégats DB
    total = db.query(MediaRequest).count()
    available = db.query(MediaRequest).filter(MediaRequest.status == "available").count()
    failed = db.query(MediaRequest).filter(MediaRequest.status == "failed").count()
    notif_sent = db.query(MediaRequest).filter(MediaRequest.available_mail_sent.is_(True)).count()
    notif_missed = (
        db.query(MediaRequest)
        .filter(
            MediaRequest.status == "available",
            MediaRequest.available_mail_sent.is_(False),
        )
        .count()
    )
    notif_total = notif_sent + notif_missed
    notif_failure_pct_db = round(notif_missed / notif_total * 100, 1) if notif_total else None

    return {
        "runtime": app_metrics.snapshot(),
        "db": {
            "total_requests": total,
            "available": available,
            "failed": failed,
            "success_rate_pct": round(available / total * 100, 1) if total else None,
            "notifications": {
                "sent": notif_sent,
                "missed": notif_missed,
                "failure_rate_pct": notif_failure_pct_db,
            },
        },
    }


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


@router.get("/next-poll")
def next_poll_info():
    """Retourne le nombre de secondes avant le prochain polling (pour le countdown UI)."""

    from ..scheduler import scheduler

    job = scheduler.get_job("watchlist_poll")
    if not job or not job.next_run_time:
        return {"next_run_seconds": None, "next_run_iso": None}
    now = datetime.now(timezone.utc)
    delta = (job.next_run_time - now).total_seconds()
    return {
        "next_run_seconds": max(0, int(delta)),
        "next_run_iso": job.next_run_time.isoformat(),
    }


# ---------------------------------------------------------------------------
# Demandes (MediaRequest)
# ---------------------------------------------------------------------------


@router.get("/requests")
def list_requests(query: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(MediaRequest)
    if query:
        q = q.filter(MediaRequest.title.ilike(f"%{query}%"))
    return q.order_by(MediaRequest.requested_at.desc()).limit(200).all()


@router.get("/plex/library-search")
async def plex_library_search(query: str, db: Session = Depends(get_db)):
    """Cherche un titre dans la bibliothèque Plex locale."""
    s = db.query(Settings).first()
    if not s or not s.plex_url or not s.plex_token:
        return []
    try:
        async with httpx.AsyncClient(timeout=10, verify=s.plex_verify_ssl) as client:
            r = await client.get(
                f"{s.plex_url.rstrip('/')}/search",
                params={"query": query, "X-Plex-Token": s.plex_token, "limit": 10},
                headers={"Accept": "application/json"},
            )
            r.raise_for_status()
            data = r.json()
            items = data.get("MediaContainer", {}).get("Metadata", [])
            return [
                {
                    "title": i.get("title", ""),
                    "year": i.get("year"),
                    "media_type": "show" if i.get("type") in ("show", "season", "episode") else "movie",
                    "thumb": f"{s.plex_url.rstrip('/')}{i['thumb']}?X-Plex-Token={s.plex_token}"
                    if i.get("thumb")
                    else None,
                    "summary": i.get("summary", ""),
                    "plex_type": i.get("type", ""),
                }
                for i in items
                if i.get("type") in ("movie", "show")
            ]
    except Exception as e:
        logger.warning(f"Plex library search failed: {e}")
        return []


@router.get("/requests/{request_id}")
async def get_request(request_id: int, db: Session = Depends(get_db)):
    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    d = {c.name: getattr(req, c.name) for c in req.__table__.columns}
    d["requested_at"] = _format_datetime(req.requested_at)
    d["available_at"] = _format_datetime(req.available_at)

    if req.torrent_hash and req.download_client_id:
        client = db.query(DownloadClient).filter(DownloadClient.id == req.download_client_id).first()
        if client and client.enabled:
            try:
                from ..services.download_clients import get_torrent_status

                status = await get_torrent_status(
                    client.client_type, client.url, client.username, client.password, req.torrent_hash
                )
                if status:
                    d["_torrent_status"] = status
            except Exception as e:
                logger.warning(f"Could not retrieve torrent status: {e}")

    settings = db.query(Settings).first()
    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    raw = (user_obj.notification_email if user_obj else None) or (settings.smtp_from if settings else "") or ""
    user_emails = parse_email_list(raw)
    notify_admin = bool(user_obj and getattr(user_obj, "notify_admin", True))
    admin_emails = parse_email_list(settings.admin_notification_email if settings and notify_admin else None)
    d["_user_emails"] = user_emails
    d["_admin_emails"] = admin_emails
    d["_notify_admin"] = notify_admin

    # Résolution des noms en direct : le demandeur principal et les co-demandeurs
    # (extra_requesters) peuvent avoir été stockés avec l'ID Plex brut. On les
    # rattache au nom lisible courant (nom d'usage → display_name → ID).
    import json as _json

    users = {u.plex_user_id: (u.custom_name or u.display_name or u.plex_user_id) for u in db.query(PlexUser).all()}
    d["plex_user"] = users.get(req.plex_user_id, req.plex_user or req.plex_user_id)
    try:
        extras = _json.loads(req.extra_requesters or "[]")
        for extra in extras:
            extra["display_name"] = users.get(
                extra.get("plex_user_id"), extra.get("display_name") or extra.get("plex_user_id")
            )
        d["extra_requesters"] = _json.dumps(extras)
    except Exception:
        pass
    return d


@router.get("/email/preview")
def preview_email_template(event: str = "request", user_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Rend le template email avec des données fictives et retourne le HTML."""
    settings = db.query(Settings).first()

    plex_user_name = "Jean Dupont"
    recipient_email = "jean.dupont@plex.local"
    if user_id:
        user = db.query(PlexUser).filter(PlexUser.id == user_id).first()
        if user:
            plex_user_name = user.custom_name or user.display_name or user.plex_user_id
            recipient_email = user.notification_email or user.plex_email or "utilisateur@plex.local"

    fake = MediaRequest(
        title="Dune : Deuxième Partie",
        year=2024,
        media_type="movie",
        plex_user=plex_user_name,
        overview="Paul Atréides s'unit aux Fremen pour mener la guerre sainte contre ceux qui ont détruit sa famille.",
        poster_url="https://image.tmdb.org/t/p/w300/1pdfLvkbY9ohJlCjQH2CZjjYVvJ.jpg",
    )
    ctx = {
        "title": fake.title,
        "year": fake.year,
        "poster_url": fake.poster_url,
        "plex_user": fake.plex_user,
        "media_type": fake.media_type,
        "media_type_label": "Film",
        "media_type_label_cap": "Le film",
        "overview": fake.overview,
        "genres": "Science-Fiction, Aventure",
        "language_reason": "VF film complet",
    }

    if event == "available":
        tpl = (
            settings.email_available_template
            if (settings and isinstance(settings.email_available_template, str))
            else None
        ) or DEFAULT_AVAILABLE_TEMPLATE
        subject_tmpl = (
            settings.email_available_subject
            if (settings and isinstance(settings.email_available_subject, str))
            else None
        ) or "[Plexarr] {{ title }} est disponible sur Plex !"
    else:
        tpl = (
            settings.email_request_template if (settings and isinstance(settings.email_request_template, str)) else None
        ) or DEFAULT_REQUEST_TEMPLATE
        subject_tmpl = (
            settings.email_request_subject if (settings and isinstance(settings.email_request_subject, str)) else None
        ) or "[Plexarr] Nouvelle demande : {{ title }}"

    rendered_subject = render_template(subject_tmpl, ctx)
    if rendered_subject.startswith("<p>Erreur de template"):
        rendered_subject = (
            f"[Plexarr] Nouvelle demande : {fake.title}"
            if event == "request"
            else f"[Plexarr] {fake.title} est disponible sur Plex !"
        )

    html = render_template(tpl, ctx)

    # Prepend email client headers
    header_html = f"""
    <div style="background:#2a2a2a; color:#fff; font-family:sans-serif; padding:12px 20px; border-bottom:1px solid #333; margin-bottom:15px; font-size:13px;">
      <div style="margin-bottom:4px;"><strong>Objet :</strong> <span style="color:#e5a00d; font-weight:bold;">{rendered_subject}</span></div>
      <div style="margin-bottom:4px;"><strong>De :</strong> {(settings.smtp_from if settings else None) or "plex-rss@monitor.local"}</div>
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

    return HTMLResponse(content=add_email_footer(html))


@router.get("/notifications/log")
def list_notification_logs(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    q = db.query(NotificationLog).order_by(NotificationLog.sent_at.desc())
    total = q.count()
    logs = q.offset(offset).limit(min(limit, 200)).all()
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "id": log.id,
                "sent_at": _format_datetime(log.sent_at),
                "event": log.event,
                "recipient": log.recipient,
                "is_admin": log.is_admin,
                "media_title": log.media_title,
                "media_type": log.media_type,
                "success": log.success,
                "error_msg": log.error_msg,
                "req_id": log.req_id,
            }
            for log in logs
        ],
    }


@router.post("/notifications/{log_id}/resend")
async def resend_notification(log_id: int, db: Session = Depends(get_db)):
    log = db.query(NotificationLog).filter(NotificationLog.id == log_id).first()
    if not log:
        raise HTTPException(404, "Log introuvable")
    if not log.req_id:
        raise HTTPException(400, "req_id manquant sur cette entrée de log (envoi antérieur à la v2.1)")
    req = get_or_404(db, MediaRequest, log.req_id, "Demande originale introuvable")
    enqueue_notification(log.event, req.id, [log.recipient])
    return {"status": "queued", "recipient": log.recipient, "event": log.event}


@router.post("/users/{user_id}/test-email")
async def send_test_email(user_id: int, db: Session = Depends(get_db)):
    user = get_or_404(db, PlexUser, user_id, "User not found")
    settings = db.query(Settings).first()
    if not settings:
        raise HTTPException(500, "Settings manquants")
    recipient = user.notification_email or user.plex_email
    if not recipient:
        raise HTTPException(400, "Aucune adresse email configurée pour cet utilisateur")
    name = user.custom_name or user.display_name or user.plex_user_id
    html = f"""<!DOCTYPE html>
<html><body style="background:#141414;font-family:Arial,sans-serif;padding:32px">
<div style="max-width:480px;margin:auto;background:#1f1f1f;border-radius:10px;padding:28px;color:#fff">
  <h2 style="color:#e5a00d;margin:0 0 16px">Test de notification</h2>
  <p style="color:#ccc">Bonjour <strong>{name}</strong>,</p>
  <p style="color:#ccc">Cet email confirme que les notifications fonctionnent correctement pour ton compte Plexarr.</p>
  <p style="color:#888;font-size:12px;margin-top:24px">Plexarr — email de test</p>
</div>
</body></html>"""
    try:
        await smtp_send(settings, recipient, "[Plexarr] Test de notification", html)
    except Exception as e:
        raise HTTPException(500, f"Échec SMTP : {e}")
    return {"status": "sent", "recipient": recipient}


class BulkAction(BaseModel):
    ids: list[int]


@router.post("/requests/bulk/retry")
async def bulk_retry_requests(body: BulkAction, db: Session = Depends(get_db)):
    """Repasse plusieurs demandes en pending et lance un polling."""
    reqs = db.query(MediaRequest).filter(MediaRequest.id.in_(body.ids)).all()
    count = 0
    for req in reqs:
        if req.status in ("failed", "pending"):
            req.status = "pending"
            count += 1
    if count > 0:
        db.commit()
        await poll_watchlists()
    return {"status": "success", "count": count}


@router.post("/requests/bulk/mark-processed")
def bulk_mark_requests_processed(body: BulkAction, db: Session = Depends(get_db)):
    """Marque plusieurs demandes comme traitées (disponibles) sans email."""
    reqs = db.query(MediaRequest).filter(MediaRequest.id.in_(body.ids)).all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for req in reqs:
        req.status = "available"
        req.request_mail_sent = True
        req.available_mail_sent = True
        if not req.available_at:
            req.available_at = now
    db.commit()
    return {"status": "success", "count": len(reqs)}


@router.post("/requests/bulk/delete")
def bulk_delete_requests(body: BulkAction, db: Session = Depends(get_db)):
    """Supprime plusieurs demandes définitivement."""
    reqs = db.query(MediaRequest).filter(MediaRequest.id.in_(body.ids)).all()
    count = len(reqs)
    for req in reqs:
        _delete_vf_episode_cache(db, req.id)
        db.delete(req)
    db.commit()
    return {"status": "success", "count": count}


@router.post("/requests/{request_id}/retry")
async def retry_request(request_id: int, db: Session = Depends(get_db)):
    """Repasse une demande en `pending` et déclenche un polling immédiat."""
    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    if req.status not in ("failed", "pending"):
        raise HTTPException(400, "Only failed or pending requests can be retried")
    req.status = "pending"
    db.commit()
    await poll_watchlists()
    return {"status": "retrying"}


@router.post("/requests/retry-failed")
async def retry_all_failed(db: Session = Depends(get_db)):
    """Repasse toutes les demandes 'failed' en 'pending' et déclenche un polling."""
    failed = db.query(MediaRequest).filter(MediaRequest.status == "failed").all()
    count = len(failed)
    for req in failed:
        req.status = "pending"
    db.commit()
    await poll_watchlists()
    return {"status": "ok", "retried": count}


@router.post("/requests/recalculate-dates")
async def recalculate_dates():
    """Re-joue sync_seer_requests pour corriger requested_at et available_at depuis Seer."""
    from ..scheduler import sync_seer_requests

    await sync_seer_requests()
    return {"status": "ok"}


@router.post("/requests/merge-duplicates")
def merge_duplicates_endpoint():
    """Fusionne les MediaRequest en double (même tmdb_id toutes sources)."""
    from scripts.merge_duplicate_requests import merge_duplicates

    merge_duplicates(dry_run=False)
    return {"status": "ok"}


@router.post("/requests/poll")
async def trigger_poll():
    """Déclenche manuellement le polling des watchlists ET la vérification des statuts *arr."""
    await poll_watchlists()
    await check_arr_statuses()
    return {"status": "poll triggered"}


@router.delete("/requests/{request_id}")
def delete_request(request_id: int, db: Session = Depends(get_db)):
    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    _delete_vf_episode_cache(db, req.id)
    db.delete(req)
    db.commit()
    return {"status": "deleted"}


@router.post("/requests/{request_id}/mark-processed")
def mark_request_processed(
    request_id: int,
    event: str = "available",
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    """Envoie manuellement le mail "demande" ou "disponible" pour une requête.

    - event="request" : renvoie le mail de demande, sans restriction ni clôture
      (peut être renvoyé autant de fois que nécessaire tant qu'on le souhaite).
    - event="available" (défaut) : envoie le mail de disponibilité et clôture
      automatiquement la demande (status -> available).
    """
    from ..scheduler import _notify

    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    settings = db.query(Settings).first()

    if event == "request":
        if settings:
            _notify("request", settings, req, db, force=True)
        req.request_mail_sent = True
    else:
        event = "available"
        if settings:
            _notify("available", settings, req, db, force=True)
        req.status = RequestStatus.available
        req.available_mail_sent = True
        if not req.available_at:
            req.available_at = datetime.now(timezone.utc).replace(tzinfo=None)

    db.commit()

    return {
        "status": "success",
        "message": "Demande marquée comme traitée",
        "notified": True,
        "event": event,
    }


# ---------------------------------------------------------------------------
# Activité et notifications
# ---------------------------------------------------------------------------


@router.get("/activity")
def activity_log(db: Session = Depends(get_db)):
    """Retourne les 25 événements les plus récents (7 derniers jours) pour le journal."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    reqs = (
        db.query(MediaRequest)
        .filter(MediaRequest.requested_at >= cutoff)
        .order_by(MediaRequest.requested_at.desc())
        .limit(50)
        .all()
    )
    # Résolution des noms en direct (nom d'usage → display_name → ID Plex),
    # pour ne pas afficher d'ID Plex brut figé pour les anciennes entrées.
    users = {u.plex_user_id: (u.custom_name or u.display_name or u.plex_user_id) for u in db.query(PlexUser).all()}

    events = []
    for r in reqs:
        user_name = users.get(r.plex_user_id) or r.plex_user or r.plex_user_id or "?"
        if r.requested_at:
            events.append(
                {
                    "type": r.status if r.status in ("failed",) else "request",
                    "title": r.title,
                    "user": user_name,
                    "media_type": r.media_type,
                    "time": _format_datetime(r.requested_at),
                }
            )
        if r.available_at and r.available_at >= cutoff:
            events.append(
                {
                    "type": "available",
                    "title": r.title,
                    "user": user_name,
                    "media_type": r.media_type,
                    "time": _format_datetime(r.available_at),
                }
            )
    events.sort(key=lambda e: e["time"], reverse=True)
    return events[:25]


@router.get("/notifications/recent-available")
def recent_available(since: str = None, db: Session = Depends(get_db)):
    """Retourne les médias devenus disponibles depuis `since` (ISO 8601).

    Utilisé par le dashboard pour afficher des toasts de disponibilité
    lors de la visite de la page.
    """
    from datetime import datetime, timezone

    q = db.query(MediaRequest).filter(MediaRequest.status == "available")
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            q = q.filter(MediaRequest.available_at >= since_dt)
        except ValueError:
            pass
    items = q.order_by(MediaRequest.available_at.desc()).limit(10).all()
    return [{"id": r.id, "title": r.title, "available_at": _format_datetime(r.available_at)} for r in items]


# ---------------------------------------------------------------------------
# Logs applicatifs
# ---------------------------------------------------------------------------


@router.get("/logs")
def get_logs(_: None = Depends(require_auth)):
    """Retourne les derniers logs applicatifs (buffer mémoire circulaire)."""
    from ..log_buffer import get_logs as _get_logs

    return _get_logs()


@router.get("/poll-history")
def get_poll_history(limit: int = 50, job: Optional[str] = None, db: Session = Depends(get_db)):
    """Retourne l'historique des exécutions du scheduler."""
    q = db.query(PollHistory)
    if job:
        q = q.filter(PollHistory.job == job)
    items = q.order_by(PollHistory.started_at.desc()).limit(limit).all()
    return [
        {
            "id": h.id,
            "job": h.job,
            "started_at": _format_datetime(h.started_at),
            "duration_ms": h.duration_ms,
            "items_processed": h.items_processed,
            "new_requests": h.new_requests,
            "newly_available": h.newly_available,
            "errors": h.errors,
            "error_detail": h.error_detail,
        }
        for h in items
    ]


# ---------------------------------------------------------------------------
# API token
# ---------------------------------------------------------------------------


@router.post("/settings/token")
def generate_api_token(db: Session = Depends(get_db)):
    """Génère un nouveau token d'API et le stocke dans les paramètres."""
    import secrets

    s = db.query(Settings).first()
    if not s:
        raise HTTPException(404, "Paramètres non initialisés")
    token = secrets.token_urlsafe(32)
    s.api_token = token
    db.commit()
    return {"api_token": token}


@router.delete("/settings/token")
def revoke_api_token(db: Session = Depends(get_db)):
    """Révoque le token d'API courant."""
    s = db.query(Settings).first()
    if not s:
        raise HTTPException(404, "Paramètres non initialisés")
    s.api_token = None
    db.commit()
    return {"status": "revoked"}


@router.get("/settings/token")
def get_api_token_status(db: Session = Depends(get_db)):
    """Indique si un token d'API est actif (sans révéler sa valeur)."""
    s = db.query(Settings).first()
    return {"active": bool(s and s.api_token)}


# ---------------------------------------------------------------------------
# Webhook secret
# ---------------------------------------------------------------------------


@router.post("/settings/webhook-secret")
def generate_webhook_secret(db: Session = Depends(get_db)):
    """Génère un nouveau secret de webhook et le stocke dans les paramètres."""
    import secrets

    s = db.query(Settings).first()
    if not s:
        raise HTTPException(404, "Paramètres non initialisés")
    secret = secrets.token_urlsafe(32)
    s.webhook_secret = secret
    db.commit()
    return {"webhook_secret": secret}


@router.delete("/settings/webhook-secret")
def revoke_webhook_secret(db: Session = Depends(get_db)):
    """Révoque le secret de webhook courant (désactive l'authentification des webhooks)."""
    s = db.query(Settings).first()
    if not s:
        raise HTTPException(404, "Paramètres non initialisés")
    s.webhook_secret = None
    db.commit()
    return {"status": "revoked"}


@router.get("/settings/webhook-secret")
def get_webhook_secret_status(db: Session = Depends(get_db)):
    """Indique si un secret de webhook est actif (sans révéler sa valeur)."""
    s = db.query(Settings).first()
    return {"active": bool(s and s.webhook_secret)}


# ---------------------------------------------------------------------------
# Métriques Prometheus
# ---------------------------------------------------------------------------


@router.get("/metrics/prometheus", response_class=__import__("fastapi").responses.PlainTextResponse)
def prometheus_metrics(db: Session = Depends(get_db)):
    """Expose les métriques au format Prometheus text (scraping externe)."""
    from fastapi.responses import PlainTextResponse
    from sqlalchemy import func

    snap = app_metrics.snapshot()

    total = db.query(MediaRequest).count()
    available = db.query(MediaRequest).filter(MediaRequest.status == "available").count()
    failed_db = db.query(MediaRequest).filter(MediaRequest.status == "failed").count()
    pending = db.query(MediaRequest).filter(MediaRequest.status == "pending").count()
    sent = db.query(MediaRequest).filter(MediaRequest.status == "sent_to_arr").count()

    lines = [
        "# HELP plex_rss_poll_total Total number of watchlist polls since startup",
        "# TYPE plex_rss_poll_total counter",
        f"plex_rss_poll_total {snap['poll']['count']}",
        "# HELP plex_rss_poll_errors_total Total number of failed polls since startup",
        "# TYPE plex_rss_poll_errors_total counter",
        f"plex_rss_poll_errors_total {snap['poll']['errors']}",
        "# HELP plex_rss_arr_submissions_total Total submissions to Sonarr/Radarr/Seer since startup",
        "# TYPE plex_rss_arr_submissions_total counter",
        f"plex_rss_arr_submissions_total {snap['arr']['submissions']}",
        "# HELP plex_rss_arr_errors_total Total failed submissions since startup",
        "# TYPE plex_rss_arr_errors_total counter",
        f"plex_rss_arr_errors_total {snap['arr']['errors']}",
        "# HELP plex_rss_notifications_sent_total Total notifications sent since startup",
        "# TYPE plex_rss_notifications_sent_total counter",
        f"plex_rss_notifications_sent_total {snap['notifications']['sent']}",
        "# HELP plex_rss_notifications_failed_total Total failed notifications since startup",
        "# TYPE plex_rss_notifications_failed_total counter",
        f"plex_rss_notifications_failed_total {snap['notifications']['failed']}",
        "# HELP plex_rss_sonarr_response_ms Average Sonarr response time (ms, last 50 calls)",
        "# TYPE plex_rss_sonarr_response_ms gauge",
        f"plex_rss_sonarr_response_ms {snap['arr']['sonarr_avg_response_ms'] or 0}",
        "# HELP plex_rss_radarr_response_ms Average Radarr response time (ms, last 50 calls)",
        "# TYPE plex_rss_radarr_response_ms gauge",
        f"plex_rss_radarr_response_ms {snap['arr']['radarr_avg_response_ms'] or 0}",
        "# HELP plex_rss_requests_total Total media requests in database",
        "# TYPE plex_rss_requests_total gauge",
        f"plex_rss_requests_total {total}",
        "# HELP plex_rss_requests_by_status Media requests grouped by status",
        "# TYPE plex_rss_requests_by_status gauge",
        f'plex_rss_requests_by_status{{status="available"}} {available}',
        f'plex_rss_requests_by_status{{status="failed"}} {failed_db}',
        f'plex_rss_requests_by_status{{status="pending"}} {pending}',
        f'plex_rss_requests_by_status{{status="sent_to_arr"}} {sent}',
    ]

    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


# ---------------------------------------------------------------------------
# Conflits de déduplication
# ---------------------------------------------------------------------------

_IGNORED_FILE = "data/ignored_conflicts.json"


def _load_ignored() -> set[str]:
    try:
        with open(_IGNORED_FILE) as f:
            return set(_json.load(f))
    except Exception:
        return set()


def _save_ignored(keys: set[str]):
    _os.makedirs("data", exist_ok=True)
    with open(_IGNORED_FILE, "w") as f:
        _json.dump(sorted(keys), f)


def _req_dict(r: MediaRequest) -> dict:
    return {
        "id": r.id,
        "title": r.title,
        "tmdb_id": r.tmdb_id,
        "tvdb_id": r.tvdb_id,
        "source": r.source,
        "status": r.status,
        "plex_user": r.plex_user,
        "plex_user_id": r.plex_user_id,
        "arr_id": r.arr_id,
        "poster_url": r.poster_url,
        "requested_at": _format_datetime(r.requested_at),
        "available_at": _format_datetime(r.available_at),
    }


def _merge_entries(keeper: MediaRequest, dup: MediaRequest, db):
    """Fusionne dup dans keeper : co-demandeurs + champs manquants."""
    extras: list[dict] = _json.loads(keeper.extra_requesters or "[]")
    existing_ids = {keeper.plex_user_id} | {e["plex_user_id"] for e in extras}
    for e in _json.loads(dup.extra_requesters or "[]"):
        if e["plex_user_id"] not in existing_ids:
            extras.append(e)
            existing_ids.add(e["plex_user_id"])
    if dup.plex_user_id not in existing_ids:
        extras.append({"plex_user_id": dup.plex_user_id, "display_name": dup.plex_user or dup.plex_user_id})
    # Seer tmdb_id fait référence
    if dup.source == "seer" and dup.tmdb_id:
        keeper.tmdb_id = dup.tmdb_id
    elif not keeper.tmdb_id and dup.tmdb_id:
        keeper.tmdb_id = dup.tmdb_id
    if not keeper.tvdb_id and dup.tvdb_id:
        keeper.tvdb_id = dup.tvdb_id
    if not keeper.poster_url and dup.poster_url:
        keeper.poster_url = dup.poster_url
    keeper.extra_requesters = _json.dumps(extras, ensure_ascii=False)
    db.delete(dup)


@router.get("/conflicts")
def list_conflicts(db: Session = Depends(get_db), _: None = Depends(require_auth)):
    """Retourne tous les conflits détectés, filtrés des ignorés."""
    ignored = _load_ignored()
    all_reqs = db.query(MediaRequest).all()
    known_user_ids = {u.plex_user_id for u in db.query(PlexUser).all()}
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # ── 1. Conflit tmdb via tvdb (Plex ≠ Seer) ──────────────────────────────
    tvdb_groups: dict[tuple, list[MediaRequest]] = defaultdict(list)
    for r in all_reqs:
        if r.tvdb_id:
            tvdb_groups[(r.media_type, r.tvdb_id)].append(r)

    tmdb_conflicts = []
    for (media_type, tvdb_id), rows in tvdb_groups.items():
        tmdb_ids = {r.tmdb_id for r in rows if r.tmdb_id}
        if len(tmdb_ids) <= 1:
            continue
        key = f"tmdb:{media_type}:{tvdb_id}"
        if key in ignored:
            continue
        seer_entry = next((r for r in rows if r.source == "seer"), None)
        recommended_id = seer_entry.id if seer_entry else None
        tmdb_conflicts.append(
            {
                "type": "tmdb_conflict",
                "key": key,
                "media_type": media_type,
                "tvdb_id": tvdb_id,
                "recommended_id": recommended_id,
                "entries": [_req_dict(r) for r in sorted(rows, key=lambda x: (x.source != "seer", x.id))],
            }
        )

    # ── 2. Demandes orphelines (utilisateur supprimé) ────────────────────────
    orphaned = []
    for r in all_reqs:
        if r.plex_user_id not in known_user_ids:
            key = f"orphan:{r.id}"
            if key in ignored:
                continue
            orphaned.append({"key": key, **_req_dict(r)})

    # ── 3. Jamais transmis à Sonarr/Radarr depuis >30 jours ─────────────────
    long_pending = []
    for r in all_reqs:
        if r.status != "pending":
            continue
        if not r.requested_at:
            continue
        age = (now - r.requested_at).days
        if age < 30:
            continue
        key = f"pending:{r.id}"
        if key in ignored:
            continue
        long_pending.append({"key": key, "age_days": age, **_req_dict(r)})

    return {
        "tmdb_conflicts": tmdb_conflicts,
        "orphaned": orphaned,
        "long_pending": long_pending,
    }


@router.post("/conflicts/resolve")
def resolve_conflict(body: dict, db: Session = Depends(get_db), _: None = Depends(require_auth)):
    keep_id: int = body.get("keep_id")
    delete_ids: list[int] = body.get("delete_ids", [])
    if not keep_id or not delete_ids:
        raise HTTPException(400, "keep_id et delete_ids requis")
    keeper = db.get(MediaRequest, keep_id)
    if not keeper:
        raise HTTPException(404, f"Entrée {keep_id} introuvable")
    for del_id in delete_ids:
        dup = db.get(MediaRequest, del_id)
        if dup:
            _merge_entries(keeper, dup, db)
    db.commit()
    return {"ok": True, "kept": keep_id, "deleted": delete_ids}


@router.post("/conflicts/auto-resolve")
def auto_resolve_conflicts(db: Session = Depends(get_db), _: None = Depends(require_auth)):
    """Résout automatiquement tous les conflits tmdb : garde l'entrée Seer."""
    all_reqs = db.query(MediaRequest).all()
    tvdb_groups: dict[tuple, list[MediaRequest]] = defaultdict(list)
    for r in all_reqs:
        if r.tvdb_id:
            tvdb_groups[(r.media_type, r.tvdb_id)].append(r)

    resolved = 0
    for (media_type, tvdb_id), rows in tvdb_groups.items():
        tmdb_ids = {r.tmdb_id for r in rows if r.tmdb_id}
        if len(tmdb_ids) <= 1:
            continue
        seer = next((r for r in rows if r.source == "seer"), None)
        keeper = seer or min(rows, key=lambda x: x.id)
        for dup in rows:
            if dup.id != keeper.id:
                _merge_entries(keeper, dup, db)
        resolved += 1

    db.commit()
    return {"ok": True, "resolved": resolved}


@router.post("/conflicts/ignore")
def ignore_conflict(body: dict, _: None = Depends(require_auth)):
    """Marque un conflit comme ignoré (ne réapparaîtra plus)."""
    key: str = body.get("key")
    if not key:
        raise HTTPException(400, "key requis")
    ignored = _load_ignored()
    ignored.add(key)
    _save_ignored(ignored)
    return {"ok": True}


@router.delete("/conflicts/ignore/{key:path}")
def unignore_conflict(key: str, _: None = Depends(require_auth)):
    """Retire un conflit de la liste des ignorés."""
    ignored = _load_ignored()
    ignored.discard(key)
    _save_ignored(ignored)
    return {"ok": True}


@router.delete("/conflicts/no-tmdb/{request_id}")
def delete_no_tmdb(request_id: int, db: Session = Depends(get_db), _: None = Depends(require_auth)):
    req = db.get(MediaRequest, request_id)
    if not req:
        raise HTTPException(404, "Entrée introuvable")
    if req.tmdb_id:
        raise HTTPException(400, "Cette entrée a un tmdb_id — utilisez /conflicts/resolve")
    _delete_vf_episode_cache(db, req.id)
    db.delete(req)
    db.commit()
    return {"ok": True}


@router.delete("/conflicts/orphan/{request_id}")
def delete_orphan(request_id: int, db: Session = Depends(get_db), _: None = Depends(require_auth)):
    req = db.get(MediaRequest, request_id)
    if not req:
        raise HTTPException(404, "Entrée introuvable")
    _delete_vf_episode_cache(db, req.id)
    db.delete(req)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Recherche unifiée de médias (lookup Sonarr/Radarr + add)
# ---------------------------------------------------------------------------


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


@router.post("/media/add")
async def media_add(body: MediaAddRequest, db: Session = Depends(get_db)):
    """Ajoute un média via Seer (prioritaire) ou directement dans Sonarr/Radarr."""
    s = db.query(Settings).first()
    item = body.model_dump()

    arr_id = None
    already = False
    via = None

    # --- Seer ---
    # use_seer=True : choix explicite ; instance_id=None + seer configuré : comportement par défaut
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

    # --- Sonarr / Radarr (instance explicite ou fallback) ---
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

    # --- Enregistrement dans la DB locale si absent ---
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
