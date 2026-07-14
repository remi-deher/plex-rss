import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import sqlalchemy

from ..database import get_db_async
from ..dependencies import require_admin, require_auth
from ..models import LibraryItem, MediaRequest, RequestStatus, Settings, VfEpisodeStatus
from ..scheduler import (
    _invalidate_vf_cache,
    _load_known_vf_episodes,
    _parse_vff_libraries,
    _persist_episode_status,
    _trigger_vf_search,
    plex_sync_state,
    sync_plex_media,
    vff_scan_state,
)
from ..services.notification_orchestrator import _notify, _queue_milestone
from ..serializers import format_datetime
from ..services import plex_finder as vff_svc
from ..services.radarr import lookup_movie
from ..services.sonarr import get_episodes, lookup_series
from ..utils import async_get_or_404, now_utc_naive, wrap_image_proxy
from .arr_api import _resolve_arr_instance

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["vff"], dependencies=[Depends(require_auth)])


def _arr_image_url(images: list[dict] | None, *cover_types: str) -> str | None:
    """Return the best public image URL exposed by Sonarr/Radarr."""
    if not images:
        return None
    for cover_type in cover_types:
        for img in images:
            if img.get("coverType") != cover_type:
                continue
            url = img.get("remoteUrl") or img.get("url")
            if url:
                return url
    for img in images:
        url = img.get("remoteUrl") or img.get("url")
        if url:
            return url
    return None


async def _vf_detail_payload(db: AsyncSession, req):
    """Détail VF (modale) : pistes audio (film) ou statut par saison/épisode (série)."""
    settings = (await db.execute(select(Settings))).scalars().first()
    if not settings:
        return {"enabled": False}

    source_type = "request" if isinstance(req, MediaRequest) else "library_item"
    libs = _parse_vff_libraries(settings)
    vf_detected = bool(settings.vff_enabled and settings.plex_url and settings.plex_token and libs)
    movie_libs = [lib["name"] for lib in libs if lib["kind"] == "movie"]
    show_libs = [lib["name"] for lib in libs if lib["kind"] in ("series", "anime")]

    if req.media_type == "movie":
        release_date = None
        try:
            radarr_inst = await _resolve_arr_instance(db, req.arr_instance_id, "radarr")
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

    if vf_detected:
        rows = (await db.execute(
            select(VfEpisodeStatus).filter(
                VfEpisodeStatus.source_type == source_type,
                VfEpisodeStatus.source_id == req.id
            )
        )).scalars().all()
        plex_eps = {}
        plex_fr_default = {}
        for r in rows:
            plex_eps.setdefault(r.season_number, {})[r.episode_number] = r.has_vf
            plex_fr_default.setdefault(r.season_number, {})[r.episode_number] = r.fr_is_default
    else:
        plex_eps = {}
        plex_fr_default = {}

    sonarr_episodes = None
    first_aired = None
    next_episode_at = None
    series_poster_url = getattr(req, "poster_url", None)
    season_posters: dict[int, str] = {}
    try:
        inst = await _resolve_arr_instance(db, req.arr_instance_id, "sonarr")
        def wrap_local(url: Optional[str]) -> Optional[str]:
            if not url:
                return url
            if url.startswith("/"):
                url = f"{inst.url.rstrip('/')}{url}"
            return wrap_image_proxy(url)
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
            series_poster_url = _arr_image_url(data.get("images"), "poster") or series_poster_url
            for season in data.get("seasons") or []:
                sn = season.get("seasonNumber")
                poster_url = _arr_image_url(season.get("images"), "poster")
                if sn is not None and poster_url:
                    season_posters[sn] = poster_url
        if series_id:
            sonarr_episodes = await get_episodes(inst.url, inst.api_key, series_id)
    except Exception as e:
        logger.warning(f"vf-detail: liste épisodes Sonarr indisponible pour '{req.title}': {e}")

    # Les épisodes sont déjà stockés en BDD par le poll background,
    # on n'a plus besoin d'écrire en DB ici lors du GET.


    def _status(in_plex, has_file, fr_is_default=None):
        if vf_detected:
            if in_plex is True:
                if fr_is_default is False:
                    return "vf_secondary"
                return "vf"
            if in_plex is False:
                return "vo"
            if has_file:
                return "unknown"
            return "absent"
        return "present" if has_file else "absent"

    seasons: dict[int, dict[int, dict]] = {}
    if sonarr_episodes:
        for ep in sonarr_episodes:
            if not ep.get("monitored", True):
                continue
            sn = ep.get("seasonNumber")
            en = ep.get("episodeNumber")
            if sn is None or en is None or sn == 0:
                continue
            status = _status(
                plex_eps.get(sn, {}).get(en),
                ep.get("hasFile"),
                plex_fr_default.get(sn, {}).get(en),
            )
            seasons.setdefault(sn, {})[en] = {
                "episode": en,
                "title": ep.get("title") or "",
                "status": status,
                "air_date": ep.get("airDateUtc") or ep.get("airDate"),
                "has_file": bool(ep.get("hasFile")),
                "thumb_url": _arr_image_url(ep.get("images"), "screenshot", "poster"),
            }
    else:
        for sn, eps in plex_eps.items():
            if sn == 0:
                continue
            for en, has_vf in eps.items():
                seasons.setdefault(sn, {})[en] = {
                    "episode": en,
                    "title": "",
                    "status": "vf_secondary"
                    if has_vf and plex_fr_default.get(sn, {}).get(en) is False
                    else ("vf" if has_vf else "vo"),
                    "air_date": None,
                    "has_file": True,
                    "thumb_url": None,
                }

    out_seasons = []
    for sn in sorted(seasons):
        eps = [seasons[sn][en] for en in sorted(seasons[sn])]
        counts = {"vf": 0, "vf_secondary": 0, "vo": 0, "present": 0, "absent": 0, "unknown": 0}
        for ep_out in eps:
            counts[ep_out["status"]] = counts.get(ep_out["status"], 0) + 1
        out_seasons.append(
            {
                "season_number": sn,
                "poster_url": wrap_local(season_posters.get(sn) or series_poster_url),
                "counts": counts,
                "episodes": eps,
            }
        )

    return {
        "enabled": True,
        "media_type": "show",
        "vf_available": vf_detected,
        "found": bool(plex_eps) or bool(sonarr_episodes),
        "sonarr_available": sonarr_episodes is not None,
        "first_aired": first_aired,
        "next_episode_at": next_episode_at,
        "poster_url": wrap_local(series_poster_url),
        "seasons": out_seasons,
    }


@router.get("/vff/counts")
async def vff_counts(db: AsyncSession = Depends(get_db_async)):
    """Compteurs VFF sur la bibliothèque."""
    async def count_where(condition) -> int:
        return int((await db.execute(
            select(sqlalchemy.func.count()).select_from(LibraryItem).filter(condition)
        )).scalar() or 0)

    vo_pending = await count_where(LibraryItem.has_vf.is_(False))
    vf_available = await count_where(LibraryItem.has_vf.is_(True))
    unchecked = await count_where(LibraryItem.has_vf.is_(None))
    
    return {"vo_pending": vo_pending, "vf_available": vf_available, "unchecked": unchecked}


@router.post("/vff/scan", dependencies=[Depends(require_admin)])
async def vff_scan_all(force: bool = False, db: AsyncSession = Depends(get_db_async)):
    """Déclenche immédiatement le scan global VFF en arrière-plan.

    `force` : vide le cache par épisode avant de lancer le scan, pour re-vérifier aussi
    les médias déjà marqués VF (sinon `_run_vf_scan` les ignore, voir sa docstring).
    """
    from ..scheduler import trigger_vff_scan_background

    if force:
        await _invalidate_vf_cache(db)
        await db.commit()

    trigger_vff_scan_background(force=force)
    return {"status": "started"}


@router.get("/vff/scan-status")
def get_vff_scan_status():
    """Retourne l'état actuel de l'analyse VFF en arrière-plan."""
    return vff_scan_state


@router.post("/vff/sync-plex", dependencies=[Depends(require_admin)])
async def vff_sync_plex():
    """Déclenche immédiatement la synchronisation de la bibliothèque Plex en arrière-plan."""
    if plex_sync_state["status"] == "running":
        return {"status": "already_running"}

    asyncio.create_task(sync_plex_media())
    return {"status": "started"}


@router.get("/vff/sync-status")
def get_vff_sync_status():
    """Retourne l'état actuel de la synchronisation de la bibliothèque Plex."""
    return plex_sync_state


@router.post("/requests/{request_id}/vff-scan", dependencies=[Depends(require_admin)])
async def vff_scan_single_request(
    request_id: int,
    force: bool = False,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    db: AsyncSession = Depends(get_db_async),
):
    """Déclenche immédiatement une analyse VFF pour une demande spécifique."""
    req = await async_get_or_404(db, MediaRequest, request_id, "Request not found")
    settings = (await db.execute(select(Settings))).scalars().first()
    if not settings:
        raise HTTPException(400, "Settings not initialized")
    if not settings.vff_enabled:
        raise HTTPException(400, "VFF tracking is disabled")
    if not settings.plex_url or not settings.plex_token:
        raise HTTPException(400, "Plex is not configured")

    if force:
        await _invalidate_vf_cache(db, "request", req.id, season_number=season, episode_number=episode)
        await db.commit()

    libs = _parse_vff_libraries(settings)
    if not libs:
        raise HTTPException(400, "No Plex libraries configured for VFF")

    movie_libs = [lib["name"] for lib in libs if lib["kind"] == "movie"]
    show_libs = [(lib["name"], lib["kind"]) for lib in libs if lib["kind"] in ("series", "anime")]
    known_vf = (await _load_known_vf_episodes(db, "request", [req.id])).get(req.id, {})

    def _scan_single_blocking():
        try:
            plex = vff_svc.connect(settings.plex_url, settings.plex_token)
        except Exception as exc:
            return {"found": False, "error": f"Plex connection error: {exc}"}

        try:
            return vff_svc.scan_media_vf(
                plex,
                req.media_type,
                movie_libs,
                show_libs,
                req.title,
                req.year,
                req.tmdb_id,
                req.tvdb_id,
                req.imdb_id,
                plex_guid=req.plex_guid,
                known_vf=known_vf,
            )
        except Exception as exc:
            return {"found": False, "error": str(exc)}

    res = await asyncio.to_thread(_scan_single_blocking)
    if not res.get("found"):
        raise HTTPException(404, res.get("error", "Media not found in Plex libraries"))

    now = now_utc_naive()
    was_tracking = req.has_vf is False
    req.vf_category = res.get("category") or req.vf_category
    req.vf_checked_at = now
    episode_status = res.get("episode_status")
    if episode_status:
        await _persist_episode_status(db, "request", req.id, episode_status, now, res.get("french_default"))

    has_vf_new = res["has_vf"]
    if has_vf_new:
        req.has_vf = True
        req.vf_granularity = "full"
        if was_tracking:
            req.vf_available_at = now
            await db.commit()
            scope = "movie" if req.media_type == "movie" else "series_complete"
            await _queue_milestone(settings, req, db, scope=scope, language="vf")
        else:
            await db.commit()
            await _notify("available", settings, req, db)
    else:
        req.has_vf = False
        req.vf_granularity = vff_svc.compute_vf_granularity(episode_status)
        if not was_tracking:
            if not req.available_mail_sent:
                req.available_mail_sent = True
                await db.commit()
                scope = "movie" if req.media_type == "movie" else "series_complete"
                await _queue_milestone(settings, req, db, scope=scope, language="vo")
            else:
                await db.commit()
            if settings.vff_auto_search:
                await _trigger_vf_search(db, settings, req)
        else:
            await db.commit()

    if req.library_item_id:
        li = (await db.execute(select(LibraryItem).filter(LibraryItem.id == req.library_item_id))).scalars().first()
        if li:
            prev_li_vf = li.has_vf
            li.vf_category = req.vf_category or li.vf_category
            li.vf_checked_at = now
            li.has_vf = req.has_vf
            li.vf_granularity = req.vf_granularity
            if li.has_vf and prev_li_vf is False:
                li.vf_available_at = now
            await db.commit()

    return {
        "status": "ok",
        "has_vf": req.has_vf,
        "vf_category": req.vf_category,
        "vf_checked_at": format_datetime(req.vf_checked_at),
    }


@router.post("/requests/{request_id}/vff-ignore", dependencies=[Depends(require_admin)])
async def vff_ignore_request(request_id: int, db: AsyncSession = Depends(get_db_async)):
    """Arrête manuellement le suivi VFF pour une demande spécifique."""
    req = await async_get_or_404(db, MediaRequest, request_id, "Request not found")
    req.has_vf = True
    await db.commit()
    return {"status": "ok", "has_vf": req.has_vf}


@router.get("/requests/{request_id}/vf-detail")
async def request_vf_detail(request_id: int, db: AsyncSession = Depends(get_db_async)):
    """Détail VF d'une demande."""
    req = await async_get_or_404(db, MediaRequest, request_id, "Request not found")
    return await _vf_detail_payload(db, req)


@router.get("/library/{item_id}/vf-detail")
async def library_vf_detail(item_id: int, db: AsyncSession = Depends(get_db_async)):
    """Détail VF d'un élément de bibliothèque."""
    item = await async_get_or_404(db, LibraryItem, item_id, "Library item not found")
    return await _vf_detail_payload(db, item)


@router.post("/library/{item_id}/vff-scan", dependencies=[Depends(require_admin)])
async def library_vff_scan(
    item_id: int,
    force: bool = False,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    db: AsyncSession = Depends(get_db_async),
):
    """Analyse VFF immédiate d'un élément de bibliothèque (met à jour son état VF)."""
    item = await async_get_or_404(db, LibraryItem, item_id, "Library item not found")
    settings = (await db.execute(select(Settings))).scalars().first()
    if not settings or not settings.vff_enabled:
        raise HTTPException(400, "VFF tracking is disabled")
    if not settings.plex_url or not settings.plex_token:
        raise HTTPException(400, "Plex is not configured")

    if force:
        await _invalidate_vf_cache(db, "library_item", item.id, season_number=season, episode_number=episode)
        await db.commit()

    libs = _parse_vff_libraries(settings)
    if not libs:
        raise HTTPException(400, "No Plex libraries configured for VFF")
    movie_libs = [lib["name"] for lib in libs if lib["kind"] == "movie"]
    show_libs = [(lib["name"], lib["kind"]) for lib in libs if lib["kind"] in ("series", "anime")]
    known_vf = (await _load_known_vf_episodes(db, "library_item", [item.id])).get(item.id, {})

    def _blocking():
        try:
            plex = vff_svc.connect(settings.plex_url, settings.plex_token)
        except Exception as exc:
            return {"found": False, "error": f"Plex connection error: {exc}"}
        try:
            return vff_svc.scan_media_vf(
                plex,
                item.media_type,
                movie_libs,
                show_libs,
                item.title,
                item.year,
                item.tmdb_id,
                item.tvdb_id,
                item.imdb_id,
                plex_guid=item.plex_guid,
                known_vf=known_vf,
            )
        except Exception as exc:
            return {"found": False, "error": str(exc)}

    res = await asyncio.to_thread(_blocking)
    if not res.get("found"):
        raise HTTPException(404, res.get("error", "Media not found in Plex libraries"))

    now = now_utc_naive()
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
        await _persist_episode_status(db, "library_item", item.id, episode_status, now, res.get("french_default"))
    await db.commit()
    return {"status": "ok", "has_vf": item.has_vf, "vf_category": item.vf_category}


@router.post("/library/{item_id}/vff-ignore", dependencies=[Depends(require_admin)])
async def library_vff_ignore(item_id: int, db: AsyncSession = Depends(get_db_async)):
    """Arrête le suivi VFF d'un élément de bibliothèque (force has_vf = True)."""
    item = await async_get_or_404(db, LibraryItem, item_id, "Library item not found")
    item.has_vf = True
    item.updated_at = now_utc_naive()
    await db.commit()
    return {"status": "ok", "has_vf": item.has_vf}
