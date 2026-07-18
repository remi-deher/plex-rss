"""Médias surveillés par Sonarr/Radarr mais jamais passés par une demande Plexarr
(ajoutés directement dans l'un des deux, sans MediaRequest associée).

Regroupe la logique déjà utilisée pour le compteur dashboard (voir
app/routers/metrics_api.py) et la liste affichée sur la page Demandes, pour ne pas
dupliquer la définition de "non complet" ni le matching par identifiant stable
(tvdb_id/tmdb_id/imdb_id, voir _find_orphan_shows/_find_orphan_movies) entre les deux.
"""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..cache import cache
from ..models import ArrInstance, LibraryItem, MediaRequest
from ..utils import now_utc_naive
from . import radarr, sonarr
from .plex_sync import _find_library_item_by_ids

# find_orphan_shows/find_orphan_movies interrogent Sonarr/Radarr en direct pour TOUT
# leur catalogue (aucun endpoint paginé côté *arr pour "juste les non-suivis") --
# sans cache, chaque chargement de la page Bibliothèque (et chaque calcul de compteur
# dashboard, voir metrics_api.py) retapait les deux à chaque fois, dominant largement
# le temps de réponse. Un TTL court suffit : le statut "non suivi" ne change pas à la
# seconde près, et _invalidate_orphans_cache() force un rafraîchissement immédiat après
# une suppression (voir requests_api.delete_orphan_request) plutôt que d'attendre le TTL.
_ORPHAN_SHOWS_CACHE_KEY = "plexarr:orphans:shows"
_ORPHAN_MOVIES_CACHE_KEY = "plexarr:orphans:movies"
_ORPHAN_CACHE_TTL = 90


async def _invalidate_orphans_cache() -> None:
    await cache.delete(_ORPHAN_SHOWS_CACHE_KEY)
    await cache.delete(_ORPHAN_MOVIES_CACHE_KEY)


def is_show_genuinely_incomplete(file_count: int, aired_count: int, total_count: int) -> bool:
    """Une série est "non complète" si des épisodes déjà diffusés manquent au
    téléchargement. Ne PAS comparer à total_count (diffusés + à venir) : une série
    encore en diffusion mais à jour sur tout ce qui est déjà sorti aurait alors presque
    toujours un total supérieur au nombre de fichiers, la faisant compter à tort comme
    "non complète" tant qu'elle continue simplement d'être diffusée. Une série "à venir"
    (aired_count == 0, rien diffusé pour l'instant) n'est pas non plus comptée ici —
    catégorie distincte, voir la page Demandes / discussions produit associées.
    """
    return bool(aired_count) and file_count < aired_count


def _poster_url(images: list[dict] | None) -> str | None:
    for img in images or []:
        if img.get("coverType") == "poster":
            return img.get("remoteUrl") or img.get("url")
    return None


async def find_orphan_shows(db: AsyncSession) -> list[dict]:
    """Séries surveillées par Sonarr, non complètes, sans MediaRequest associée."""
    cached = await cache.get_json(_ORPHAN_SHOWS_CACHE_KEY)
    if cached is not None:
        return cached["items"]

    instances = (await db.execute(
        select(ArrInstance).filter(ArrInstance.enabled, ArrInstance.arr_type == "sonarr")
    )).scalars().all()
    if not instances:
        return []

    known_rows = (await db.execute(
        select(MediaRequest.arr_id, MediaRequest.tvdb_id).filter(MediaRequest.media_type == "show")
    )).all()
    known_arr_ids = {r.arr_id for r in known_rows if r.arr_id is not None}
    known_tvdb_ids = {str(r.tvdb_id) for r in known_rows if r.tvdb_id}

    results = []
    for inst in instances:
        try:
            series_list = await sonarr.get_all_series(inst.url, inst.api_key)
        except Exception:
            continue
        for series in series_list:
            if (
                series.get("id") in known_arr_ids
                or str(series.get("tvdbId")) in known_tvdb_ids
                or not series.get("monitored", True)
            ):
                continue
            stats = sonarr.aggregate_monitored_episode_stats(series)
            if not is_show_genuinely_incomplete(
                stats["episode_file_count"], stats["episode_count"], stats["total_episode_count"]
            ):
                continue
            results.append({
                "id": f"orphan-show-{inst.id}-{series.get('id')}",
                "title": series.get("title"),
                "year": series.get("year"),
                "media_type": "show",
                "poster_url": _poster_url(series.get("images")),
                "status": "sent_to_arr",
                "orphan": True,
                "orphan_source": "sonarr",
                "arr_instance_id": inst.id,
                "arr_id": series.get("id"),
                "episodes_available_count": stats["episode_file_count"],
                "episodes_aired_count": stats["episode_count"],
                "episodes_total_count": stats["total_episode_count"],
            })
    await cache.set_json(_ORPHAN_SHOWS_CACHE_KEY, {"items": results}, ttl_seconds=_ORPHAN_CACHE_TTL)
    return results


async def find_orphan_movies(db: AsyncSession) -> list[dict]:
    """Films surveillés par Radarr, sans fichier, sans MediaRequest associée."""
    cached = await cache.get_json(_ORPHAN_MOVIES_CACHE_KEY)
    if cached is not None:
        return cached["items"]

    instances = (await db.execute(
        select(ArrInstance).filter(ArrInstance.enabled, ArrInstance.arr_type == "radarr")
    )).scalars().all()
    if not instances:
        return []

    known_rows = (await db.execute(
        select(MediaRequest.arr_id, MediaRequest.tmdb_id, MediaRequest.imdb_id).filter(MediaRequest.media_type == "movie")
    )).all()
    known_arr_ids = {r.arr_id for r in known_rows if r.arr_id is not None}
    known_tmdb_ids = {str(r.tmdb_id) for r in known_rows if r.tmdb_id}
    known_imdb_ids = {r.imdb_id for r in known_rows if r.imdb_id}

    results = []
    for inst in instances:
        try:
            movies_list = await radarr.get_all_movies(inst.url, inst.api_key)
        except Exception:
            continue
        for movie in movies_list:
            if (
                movie.get("id") in known_arr_ids
                or str(movie.get("tmdbId")) in known_tmdb_ids
                or movie.get("imdbId") in known_imdb_ids
                or not movie.get("monitored", True)
            ):
                continue
            if movie.get("hasFile", False):
                continue
            results.append({
                "id": f"orphan-movie-{inst.id}-{movie.get('id')}",
                "title": movie.get("title"),
                "year": movie.get("year"),
                "media_type": "movie",
                "poster_url": _poster_url(movie.get("images")),
                "status": "sent_to_arr",
                "orphan": True,
                "orphan_source": "radarr",
                "arr_instance_id": inst.id,
                "arr_id": movie.get("id"),
            })
    await cache.set_json(_ORPHAN_MOVIES_CACHE_KEY, {"items": results}, ttl_seconds=_ORPHAN_CACHE_TTL)
    return results


async def materialize_orphan_library_item(
    db: AsyncSession, inst: ArrInstance, arr_type: str, arr_id: int
) -> LibraryItem:
    """Cree ou retrouve le LibraryItem d'un item "Suivi Sonarr/Radarr" (jamais passe
    par une demande Plexarr), pour lui ouvrir une fiche detaillee -- reutilise telle
    quelle l'infrastructure existante (page de detail, suivi VF, saisons/episodes)
    prevue pour les LibraryItem issus de la synchronisation Plex.

    plex_guid reste vide tant que Plex n'a pas confirme le media : la prochaine
    synchronisation Plex complete la meme ligne par identite (voir
    `_find_library_item_by_ids`), exactement comme pour une MediaRequest pas encore liee.
    """
    if arr_type == "sonarr":
        item = await sonarr.lookup_series(inst.url, inst.api_key, arr_id=arr_id)
        media_type = "show"
        tvdb_id, tmdb_id, imdb_id = (item or {}).get("tvdbId"), (item or {}).get("tmdbId"), (item or {}).get("imdbId")
    else:
        item = await radarr.lookup_movie(inst.url, inst.api_key, arr_id=arr_id)
        media_type = "movie"
        tvdb_id, tmdb_id, imdb_id = None, (item or {}).get("tmdbId"), (item or {}).get("imdbId")
    if not item:
        raise HTTPException(404, "Media introuvable cote Sonarr/Radarr")

    title, year = item.get("title") or "?", item.get("year")
    tmdb_id = str(tmdb_id) if tmdb_id else None
    tvdb_id = str(tvdb_id) if tvdb_id else None
    slug = item.get("titleSlug") or item.get("folderName")

    li = await _find_library_item_by_ids(db, None, tmdb_id, tvdb_id, imdb_id, title, year, media_type)
    if li:
        if not li.arr_instance_id:
            li.arr_instance_id, li.arr_id, li.arr_slug = inst.id, arr_id, slug
        if not li.poster_url:
            li.poster_url = _poster_url(item.get("images"))
        if not li.overview:
            li.overview = item.get("overview")
        return li

    now = now_utc_naive()
    li = LibraryItem(
        title=title, year=year, media_type=media_type,
        tmdb_id=tmdb_id, tvdb_id=tvdb_id, imdb_id=imdb_id, plex_guid=None,
        poster_url=_poster_url(item.get("images")), overview=item.get("overview"),
        arr_instance_id=inst.id, arr_id=arr_id, arr_slug=slug,
        has_vf=None, created_at=now, updated_at=now,
    )
    db.add(li)
    await db.flush()
    return li
