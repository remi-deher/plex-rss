"""Médias surveillés par Sonarr/Radarr mais jamais passés par une demande Plexarr
(ajoutés directement dans l'un des deux, sans MediaRequest associée).

Regroupe la logique déjà utilisée pour le compteur dashboard (voir
app/routers/metrics_api.py) et la liste affichée sur la page Demandes, pour ne pas
dupliquer la définition de "non complet" ni le matching par identifiant stable
(tvdb_id/tmdb_id/imdb_id, voir _find_orphan_shows/_find_orphan_movies) entre les deux.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..models import ArrInstance, MediaRequest
from . import radarr, sonarr


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
    return results


async def find_orphan_movies(db: AsyncSession) -> list[dict]:
    """Films surveillés par Radarr, sans fichier, sans MediaRequest associée."""
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
    return results
