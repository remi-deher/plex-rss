import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_admin
from ..models import ArrInstance, DownloadClient, LibraryItem, MediaRequest, RequestStatus, Settings
from ..services import prowlarr, radarr, sonarr
from ..services.download_clients import (
    add_torrent_file_to_client,
    add_torrent_to_client,
    check_client_connection,
)
from ..utils import get_or_404

router = APIRouter(prefix="/api", tags=["arr"], dependencies=[Depends(require_admin)])


def _set_single_default(db: Session, model, type_col: str, type_val: str, exclude_id: Optional[int] = None) -> None:
    """Remet is_default=False sur toutes les instances du même type, sauf exclude_id."""
    q = db.query(model).filter(getattr(model, type_col) == type_val)
    if exclude_id is not None:
        q = q.filter(model.id != exclude_id)
    q.update({"is_default": False})


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


class ProwlarrGrabRequest(BaseModel):
    guid: str
    indexer_id: int
    instance_id: int
    request_id: Optional[int] = None


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


class ArrGrabRequest(BaseModel):
    media_type: str  # "movie" | "show"
    guid: str
    indexer_id: int
    instance_id: Optional[int] = None
    request_id: Optional[int] = None


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
            return ArrInstance(
                url=settings.sonarr_url,
                api_key=settings.sonarr_api_key,
                root_folder=settings.sonarr_root_folder,
            )
        elif arr_type == "radarr" and settings and settings.radarr_url:
            return ArrInstance(
                url=settings.radarr_url,
                api_key=settings.radarr_api_key,
                root_folder=settings.radarr_root_folder,
                minimum_availability=settings.radarr_minimum_availability or "released",
            )
        raise HTTPException(400, f"Aucune instance par défaut configurée pour {arr_type}")
    return inst


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


async def _arr_folders(
    url: Optional[str],
    api_key: Optional[str],
    instance_id: Optional[int],
    arr_type: str,
    db: Session,
    coro_fn,
):
    default_root = None
    if url and api_key:
        folders = await coro_fn(url, api_key)
    else:
        inst = _resolve_arr_instance(db, instance_id, arr_type)
        default_root = inst.root_folder
        folders = await coro_fn(inst.url, inst.api_key)

    out = []
    for folder in folders:
        data = {"path": folder} if isinstance(folder, str) else dict(folder)
        path = data.get("path")
        data["is_default"] = bool(default_root and path == default_root)
        out.append(data)
    return out


@router.get("/arr-instances")
def list_arr_instances(db: Session = Depends(get_db)):
    return db.query(ArrInstance).all()


@router.get("/arr/capabilities")
def arr_capabilities(db: Session = Depends(get_db)):
    all_instances = db.query(ArrInstance).all()
    enabled_instances = [i for i in all_instances if i.enabled]
    configured_types = {i.arr_type for i in all_instances}
    enabled_types = {i.arr_type for i in enabled_instances}
    has_enabled_clients = db.query(DownloadClient).filter(DownloadClient.enabled).first() is not None
    has_clients = db.query(DownloadClient).first() is not None
    return {
        "has_sonarr": "sonarr" in enabled_types,
        "has_radarr": "radarr" in enabled_types,
        "has_prowlarr": "prowlarr" in enabled_types,
        "sonarr_configured": "sonarr" in configured_types,
        "radarr_configured": "radarr" in configured_types,
        "prowlarr_configured": "prowlarr" in configured_types,
        "sonarr_disabled": "sonarr" in configured_types and "sonarr" not in enabled_types,
        "radarr_disabled": "radarr" in configured_types and "radarr" not in enabled_types,
        "prowlarr_disabled": "prowlarr" in configured_types and "prowlarr" not in enabled_types,
        "has_arr_downloads": bool({"sonarr", "radarr"} & enabled_types),
        "arr_downloads_disabled": bool({"sonarr", "radarr"} & configured_types)
        and not bool({"sonarr", "radarr"} & enabled_types),
        "has_download_clients": has_enabled_clients,
        "download_clients_configured": has_clients,
        "download_clients_disabled": has_clients and not has_enabled_clients,
    }


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
    """Indique si Prowlarr a lui-même un client de téléchargement actif."""
    inst = get_or_404(db, ArrInstance, instance_id, "Instance Prowlarr introuvable")
    clients = await prowlarr.get_download_clients(inst.url, inst.api_key)
    return {"has_client": any(c.get("enable") for c in clients)}


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


@router.get("/download-clients")
def list_download_clients(db: Session = Depends(get_db)):
    return db.query(DownloadClient).all()


@router.post("/download-clients")
def create_download_client(data: DownloadClientCreate, db: Session = Depends(get_db)):
    if data.is_default:
        db.query(DownloadClient).update({"is_default": False})
    client = DownloadClient(**data.model_dump())
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@router.put("/download-clients/{client_id}")
def update_download_client(client_id: int, data: DownloadClientCreate, db: Session = Depends(get_db)):
    client = get_or_404(db, DownloadClient, client_id, "Client introuvable")
    if data.is_default:
        db.query(DownloadClient).filter(DownloadClient.id != client_id).update({"is_default": False})
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

    try:
        inst = _resolve_arr_instance(db, instance_id, "prowlarr")
    except HTTPException:
        raise HTTPException(400, "Aucune instance Prowlarr configurée et active")

    results = await prowlarr.search(
        url=inst.url,
        api_key=inst.api_key,
        query=query,
        media_type=media_type,
        indexer_ids=None,
    )

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

    formatted_results.sort(key=lambda x: x["seeders"], reverse=True)
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


@router.get("/arr/releases")
async def arr_interactive_releases(
    media_type: str,
    arr_id: int,
    instance_id: Optional[int] = None,
    episode_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Recherche interactive Sonarr/Radarr : releases déjà scorées (qualité + custom format + langue) avec marquage VF."""
    arr_type = "radarr" if media_type == "movie" else "sonarr"
    inst = _resolve_arr_instance(db, instance_id, arr_type)
    if media_type == "movie":
        releases = await radarr.get_releases(inst.url, inst.api_key, arr_id)
    else:
        releases = await sonarr.get_releases(inst.url, inst.api_key, series_id=arr_id, episode_id=episode_id)

    for rel in releases:
        rel["is_french"] = _release_is_french(rel)

    releases.sort(key=lambda r: (r["is_french"], r.get("custom_format_score", 0), r.get("seeders", 0)), reverse=True)
    return releases


@router.post("/arr/grab")
async def arr_grab_release(body: ArrGrabRequest, db: Session = Depends(get_db)):
    """Grab d'une release via Sonarr/Radarr."""
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
    """File d'attente de téléchargement unifiée : agrège les queues de toutes les instances Sonarr/Radarr actives."""
    instances = db.query(ArrInstance).filter(ArrInstance.enabled).all()

    # Pré-charge les demandes/items bibliothèque par (arr_instance_id, arr_id) pour lier
    # chaque ligne de la file à sa fiche média (lien "Voir la fiche" côté UI).
    req_by_key: dict[tuple[int, int], MediaRequest] = {}
    lib_by_key: dict[tuple[int, int], LibraryItem] = {}
    for req in db.query(MediaRequest).filter(MediaRequest.arr_id.isnot(None)).all():
        if req.arr_instance_id:
            req_by_key[(req.arr_instance_id, req.arr_id)] = req
    for li in db.query(LibraryItem).filter(LibraryItem.arr_id.isnot(None)).all():
        if li.arr_instance_id:
            lib_by_key[(li.arr_instance_id, li.arr_id)] = li

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
            rec["instance_id"] = inst.id
            rec["arr_type"] = inst.arr_type
            arr_media_id = rec.get("arr_media_id")
            key = (inst.id, arr_media_id) if arr_media_id else None
            li = lib_by_key.get(key) if key else None
            req = req_by_key.get(key) if key else None
            rec["library_id"] = li.id if li else None
            rec["request_id"] = req.id if (req and not li) else None
            items.append(rec)
    items.sort(key=lambda x: x.get("progress") or 0)
    return items


@router.delete("/arr/queue/{instance_id}/{queue_id}")
async def delete_arr_queue_item(
    instance_id: int,
    queue_id: int,
    blocklist: bool = False,
    search: bool = True,
    db: Session = Depends(get_db),
):
    """Supprime un item de la file *arr (avec blocklist et relance de recherche optionnelles)."""
    inst = get_or_404(db, ArrInstance, instance_id, "Instance introuvable")
    if inst.arr_type == "sonarr":
        ok, msg = await sonarr.delete_queue_item(inst.url, inst.api_key, queue_id, blocklist=blocklist, search=search)
    elif inst.arr_type == "radarr":
        ok, msg = await radarr.delete_queue_item(inst.url, inst.api_key, queue_id, blocklist=blocklist, search=search)
    else:
        raise HTTPException(400, "Instance non applicable (ni Sonarr ni Radarr)")
    if not ok:
        raise HTTPException(502, msg)
    return {"status": "ok", "message": msg}


@router.get("/downloads/direct")
async def direct_downloads(db: Session = Depends(get_db)):
    """Torrents poussés en direct-client (hors *arr), suivis via download_client_id + torrent_hash sur les demandes."""
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
                "request_id": req.id,
                "library_id": req.library_item_id,
            }
        )
    return out


@router.get("/downloads/history")
def downloads_history(
    limit: int = 100,
    media_type: Optional[str] = None,
    source: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Historique des téléchargements terminés (Sonarr/Radarr/Plex/torrent direct)."""
    from ..models import DownloadHistory

    q = db.query(DownloadHistory)
    if media_type in ("movie", "show"):
        q = q.filter(DownloadHistory.media_type == media_type)
    if source:
        q = q.filter(DownloadHistory.source == source)
    rows = q.order_by(DownloadHistory.completed_at.desc()).limit(min(limit, 500)).all()
    return [
        {
            "id": h.id,
            "title": h.title,
            "year": h.year,
            "media_type": h.media_type,
            "source": h.source,
            "instance_name": h.instance_name,
            "poster_url": h.poster_url,
            "request_id": h.request_id,
            "completed_at": h.completed_at.isoformat() if h.completed_at else None,
        }
        for h in rows
    ]


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
    return await _arr_folders(url, api_key, instance_id, "sonarr", db, sonarr.get_root_folders)


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
    return await _arr_folders(url, api_key, instance_id, "radarr", db, radarr.get_root_folders)


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
