"""Association et import manuel d'un telechargement que Sonarr/Radarr n'a pas su rattacher."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import get_db_async
from ..dependencies import require_admin
from ..models import ArrInstance, MediaRequest, RequestStatus
from ..services import radarr, sonarr
from ..utils import async_get_or_404
from .arr_shared import invalidate_arr_queue_cache

router = APIRouter(prefix="/api", tags=["arr"], dependencies=[Depends(require_admin)])
logger = logging.getLogger(__name__)

class ManualImportRequest(BaseModel):
    instance_id: int
    media_type: str  # "movie" | "show"
    title: str
    arr_id: int  # seriesId (sonarr) ou movieId (radarr) — déjà connu de l'instance *arr
    year: Optional[int] = None
    tmdb_id: Optional[int] = None
    tvdb_id: Optional[int] = None
    poster_url: Optional[str] = None

@router.post("/downloads/manual-import")
async def manual_import_download(body: ManualImportRequest, db: AsyncSession = Depends(get_db_async)):
    """Attache manuellement un item de la file *arr à une MediaRequest quand le
    rapprochement automatique (instance_id, arr_media_id) n'a rien trouvé — ex. média
    ajouté directement dans Sonarr/Radarr sans passer par l'app. Ne renvoie pas la
    notification "Nouvelle demande" : c'est un rattachement rétroactif, pas une vraie
    nouvelle demande utilisateur.
    """
    inst = await async_get_or_404(db, ArrInstance, body.instance_id, "Instance introuvable")
    expected_type = "sonarr" if body.media_type == "show" else "radarr"
    if inst.arr_type != expected_type:
        raise HTTPException(400, f"L'instance {inst.name} n'est pas de type {expected_type}")

    tmdb_str = str(body.tmdb_id) if body.tmdb_id else None
    tvdb_str = str(body.tvdb_id) if body.tvdb_id else None

    existing = (
        await db.execute(
            select(MediaRequest).filter(
                MediaRequest.arr_instance_id == inst.id,
                MediaRequest.arr_id == body.arr_id,
            )
        )
    ).scalars().first()
    if not existing and tmdb_str:
        existing = (await db.execute(select(MediaRequest).filter(MediaRequest.tmdb_id == tmdb_str))).scalars().first()
    if not existing and tvdb_str:
        existing = (await db.execute(select(MediaRequest).filter(MediaRequest.tvdb_id == tvdb_str))).scalars().first()

    if existing:
        if not existing.arr_instance_id:
            existing.arr_instance_id = inst.id
        if not existing.arr_id:
            existing.arr_id = body.arr_id
        if body.poster_url and not existing.poster_url:
            existing.poster_url = body.poster_url
        await db.commit()
        return {"status": "linked", "request_id": existing.id}

    req = MediaRequest(
        plex_user_id="manual",
        plex_user="Import manuel",
        title=body.title,
        year=body.year,
        media_type=body.media_type,
        tmdb_id=tmdb_str,
        tvdb_id=tvdb_str,
        status=RequestStatus.sent_to_arr,
        source="manual_import",
        arr_id=body.arr_id,
        arr_instance_id=inst.id,
        poster_url=body.poster_url,
    )
    db.add(req)
    await db.commit()
    return {"status": "created", "request_id": req.id}

@router.get("/downloads/sonarr-manual-import")
async def sonarr_manual_import_candidates(
    instance_id: int,
    series_id: int,
    download_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db_async),
):
    """Candidats + épisodes disponibles pour un import manuel Sonarr (cas où l'épisode
    n'est pas encore officiellement sorti dans les métadonnées Sonarr et ne peut donc
    pas être matché automatiquement).
    """
    inst = await async_get_or_404(db, ArrInstance, instance_id, "Instance introuvable")
    if inst.arr_type != "sonarr":
        raise HTTPException(400, "Cette instance n'est pas Sonarr")
    candidates = await sonarr.get_manual_import_candidates(inst.url, inst.api_key, download_id) if download_id else []
    episodes = await sonarr.get_episodes(inst.url, inst.api_key, series_id)
    return {"candidates": candidates, "episodes": episodes}

class SonarrManualImportBody(BaseModel):
    instance_id: int
    series_id: int
    episode_id: int
    path: str
    folder_name: Optional[str] = None
    download_id: Optional[str] = None
    quality: Optional[dict] = None
    languages: Optional[list] = None
    release_group: Optional[str] = None
    indexer_flags: Optional[int] = None

@router.post("/downloads/sonarr-manual-import")
async def sonarr_manual_import(body: SonarrManualImportBody, db: AsyncSession = Depends(get_db_async)):
    """Force l'import d'un fichier téléchargé sur l'épisode choisi manuellement par
    l'utilisateur (équivalent de l'import manuel natif de Sonarr).
    """
    inst = await async_get_or_404(db, ArrInstance, body.instance_id, "Instance introuvable")
    if inst.arr_type != "sonarr":
        raise HTTPException(400, "Cette instance n'est pas Sonarr")
    ok, msg = await sonarr.manual_import_episode(
        inst.url,
        inst.api_key,
        path=body.path,
        folder_name=body.folder_name,
        series_id=body.series_id,
        episode_id=body.episode_id,
        download_id=body.download_id,
        quality=body.quality,
        languages=body.languages,
        release_group=body.release_group,
        indexer_flags=body.indexer_flags,
    )
    if not ok:
        raise HTTPException(400, msg)
    # L'import Sonarr est asynchrone (commande en file) : invalide le cache de la file
    # pour que le prochain GET /arr/queue reflète l'état réel plutôt qu'une version
    # jusqu'à 60s périmée montrant encore l'item en erreur.
    await invalidate_arr_queue_cache()
    return {"status": "ok", "message": msg}

@router.get("/downloads/radarr-manual-import")
async def radarr_manual_import_candidates(
    instance_id: int,
    movie_id: int,
    download_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db_async),
):
    """Candidats pour un import manuel Radarr."""
    inst = await async_get_or_404(db, ArrInstance, instance_id, "Instance introuvable")
    if inst.arr_type != "radarr":
        raise HTTPException(400, "Cette instance n'est pas Radarr")
    candidates = await radarr.get_manual_import_candidates(inst.url, inst.api_key, download_id) if download_id else []
    return {"candidates": candidates}

class RadarrManualImportBody(BaseModel):
    instance_id: int
    movie_id: int
    path: str
    folder_name: Optional[str] = None
    download_id: Optional[str] = None
    quality: Optional[dict] = None
    languages: Optional[list] = None
    release_group: Optional[str] = None
    indexer_flags: Optional[int] = None

@router.post("/downloads/radarr-manual-import")
async def radarr_manual_import(body: RadarrManualImportBody, db: AsyncSession = Depends(get_db_async)):
    """Force l'import d'un fichier téléchargé pour un film (Radarr)."""
    inst = await async_get_or_404(db, ArrInstance, body.instance_id, "Instance introuvable")
    if inst.arr_type != "radarr":
        raise HTTPException(400, "Cette instance n'est pas Radarr")
    ok, msg = await radarr.manual_import_movie(
        inst.url,
        inst.api_key,
        path=body.path,
        folder_name=body.folder_name,
        movie_id=body.movie_id,
        download_id=body.download_id,
        quality=body.quality,
        languages=body.languages,
        release_group=body.release_group,
        indexer_flags=body.indexer_flags,
    )
    if not ok:
        raise HTTPException(400, msg)
    await invalidate_arr_queue_cache()
    return {"status": "ok", "message": msg}
