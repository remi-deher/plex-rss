"""
Client pour l'API Radarr v3 (films).

Fonctions principales :
- add_movie          : ajoute un film et lance la recherche
- is_movie_available : vérifie si le fichier film est présent (hasFile=true)
- lookup_movie       : recherche un film par arr_id, tmdb_id ou imdb_id
- test_connection    : vérifie la connectivité avec l'instance Radarr
- get_quality_profiles / get_root_folders : données de configuration UI
"""

import logging
from functools import partial

import httpx

from . import arr_common
from .arr_common import normalize_title as _norm_title
from .arr_http_client import ArrClient

logger = logging.getLogger(__name__)

PRODUCT = "Radarr"

# Appels partagés avec Sonarr (même API v3), pré-liés au nom du produit pour que les
# messages et les logs restent identiques — voir services/arr_common.py.
check_connection = partial(arr_common.check_connection, product=PRODUCT)
get_notifications = arr_common.get_notifications
find_webhook_notification = arr_common.find_webhook_notification
find_plex_notification = arr_common.find_plex_notification
test_notification = partial(arr_common.test_notification, product=PRODUCT)
get_webhook_schema = arr_common.get_webhook_schema
build_webhook_payload = arr_common.build_webhook_payload
create_notification = arr_common.create_notification
update_notification = arr_common.update_notification
get_quality_profiles = arr_common.get_quality_profiles
get_root_folders = arr_common.get_root_folders
get_tags = arr_common.get_tags
get_disk_space = arr_common.get_disk_space
get_calendar = partial(arr_common.get_calendar, product=PRODUCT)
get_all_movies = partial(arr_common.get_all_media, resource="movie")
movie_exists = partial(arr_common.media_exists, resource="movie")
grab_release = partial(arr_common.grab_release, product=PRODUCT)
get_manual_import_candidates = partial(arr_common.get_manual_import_candidates, product=PRODUCT)
trigger_import = partial(arr_common.trigger_import, command="DownloadedMoviesScan", product=PRODUCT)
delete_queue_item = partial(arr_common.delete_queue_item, product=PRODUCT)
get_queue_movie_ids = partial(
    arr_common.get_queue_media_ids,
    id_key="movieId",
    product=PRODUCT,
    log_name="get_queue_movie_ids",
)
delete_movie = partial(
    arr_common.delete_media,
    resource="movie",
    exclusion_param="addImportExclusion",
    absent_message="Déjà absent de Radarr",
    deleted_message="Supprimé de Radarr",
)
_normalize_release = arr_common.normalize_release


def _candidate_matches_title(candidate: dict, title: str | None, year: int | None) -> bool:
    """Valide qu'un résultat de recherche Radarr correspond bien au titre/année demandés.

    Sans cette vérification, le premier résultat du lookup textuel Radarr est utilisé
    aveuglément (contrairement à Sonarr) : un remake ou un homonyme placé en tête de
    liste ferait ajouter le mauvais film silencieusement.
    """
    expected_title = _norm_title(title)
    candidate_title = _norm_title(candidate.get("title"))
    if not (expected_title and candidate_title and expected_title == candidate_title):
        return False
    candidate_year = candidate.get("year")
    return not year or not candidate_year or str(year) == str(candidate_year)


async def add_movie(
    url: str,
    api_key: str,
    quality_profile_id: int,
    root_folder: str,
    item: dict,
    minimum_availability: str = "released",
    tag_ids: list[int] | None = None,
) -> tuple[int | None, bool, str | None]:
    """Ajoute un film à Radarr, ou retourne son ID s'il existe déjà.

    Returns:
        (radarr_id, already_existed, titleSlug)
        - already_existed=True signifie que le film était déjà dans Radarr.
    """
    url.rstrip("/")

    tmdb_id = item.get("tmdb_id")
    if not tmdb_id and item.get("imdb_id"):
        # TMDB ID absent : tentative de résolution via IMDB ID
        tmdb_id = await resolve_tmdb_id(url, api_key, item["imdb_id"])
    if not tmdb_id:
        # Toujours absent : recherche par texte via le lookup Radarr (inclut l'année)
        tmdb_id = await _search_tmdb_id(url, api_key, item["title"], item.get("year"))
    if not tmdb_id:
        logger.warning(f"Cannot find TMDB ID for '{item['title']}'")
        return None, False, None

    if not quality_profile_id:
        profiles = await get_quality_profiles(url, api_key)
        if profiles:
            quality_profile_id = profiles[0]["id"]
            
    if not root_folder:
        folders = await get_root_folders(url, api_key)
        if folders:
            root_folder = folders[0]["path"]

    # Vérification d'existence avant ajout
    try:
        client = ArrClient(url, api_key, timeout=15)
        existing = await client.get("/api/v3/movie")
        existing.raise_for_status()
        for m in existing.json():
            if str(m.get("tmdbId")) == str(tmdb_id):
                logger.info(f"'{item['title']}' already in Radarr (id={m['id']})")
                return m["id"], True, m.get("titleSlug")
    except httpx.HTTPError:
        pass

    payload = {
        "title": item["title"],
        "tmdbId": int(tmdb_id),
        "qualityProfileId": quality_profile_id,
        "rootFolderPath": root_folder,
        "minimumAvailability": minimum_availability,
        "monitored": True,
        "addOptions": {"searchForMovie": True},
        "tags": tag_ids or [],
    }

    try:
        client = ArrClient(url, api_key, timeout=30)
        resp = await client.post("/api/v3/movie", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("id"), False, data.get("titleSlug")
    except httpx.HTTPStatusError as e:
        body = e.response.text if hasattr(e, 'response') else ''
        b_lower = body.lower()
        if e.response.status_code == 400 and ("movieexistsvalidator" in b_lower or "already been added" in b_lower or "already configured" in b_lower or "déjà été ajouté" in b_lower or "déjà configuré" in b_lower or "deja ete ajoute" in b_lower or "deja configure" in b_lower):
            logger.info(f"'{item['title']}' already in Radarr (caught 400 Exists/PathConfigured)")
            return None, True, None
        logger.error(f"Radarr error adding '{item['title']}': {e} — response: {body}")
        raise
    except httpx.HTTPError as e:
        logger.error(f"Radarr error adding '{item['title']}': {e}")
        raise


async def resolve_tmdb_id(url: str, api_key: str, imdb_id: str) -> str | None:
    """Résout un TMDB ID à partir d'un IMDB ID via le lookup Radarr.

    Sert à normaliser sur TMDB les demandes RSS (qui n'apportent qu'un IMDB ID),
    afin qu'elles dédupliquent correctement avec les demandes Seer (clés sur TMDB).
    Radarr s'appuie sur la table de correspondance externe de TMDB : la résolution
    est donc cohérente avec ce que produit Seer pour le même film.
    """
    if not imdb_id:
        return None
    url.rstrip("/")
    try:
        client = ArrClient(url, api_key, timeout=15)
        resp = await client.get(
            "/api/v3/movie/lookup",
            params={"term": f"imdb:{imdb_id}"},
        )
        resp.raise_for_status()
        results = resp.json()
        if results and results[0].get("tmdbId"):
            return str(results[0]["tmdbId"])
    except Exception as e:
        logger.warning(f"Radarr imdb→tmdb resolution failed for '{imdb_id}': {e}")
    return None


async def _search_tmdb_id(url: str, api_key: str, title: str, year: int | None) -> str | None:
    """Cherche un TMDB ID via le lookup Radarr.

    L'année est ajoutée au terme de recherche pour lever les ambiguïtés entre remakes
    et homonymes, mais Radarr peut quand même renvoyer un premier résultat différent
    (tri par pertinence/popularité) : on valide donc titre+année sur les résultats
    avant de retenir un candidat, plutôt que de prendre le premier aveuglément.
    """
    try:
        client = ArrClient(url, api_key, timeout=15)
        for term in ([f"{title} {year}", title] if year else [title]):
            resp = await client.get(
                "/api/v3/movie/lookup",
                params={"term": term},
                )
            resp.raise_for_status()
            results = resp.json()
            for candidate in results:
                if _candidate_matches_title(candidate, title, year) and candidate.get("tmdbId"):
                    return str(candidate["tmdbId"])
        if results:
            logger.warning(
                "Radarr lookup for '%s' (%s) returned no result matching title/year; "
                "refusing ambiguous match",
                title,
                year,
            )
    except Exception as e:
        logger.warning(f"Radarr lookup failed for '{title}': {e}")
    return None


async def lookup_movie(
    url: str,
    api_key: str,
    arr_id: int = None,
    tmdb_id: str = None,
    imdb_id: str = None,
    movies_list: list[dict] | None = None,
) -> dict | None:
    """Recherche un film par arr_id (GET direct), tmdb_id ou imdb_id (scan de la liste).

    L'ordre de priorité est : arr_id → tmdb_id → imdb_id.
    Le scan de la liste est O(n) ; arr_id est O(1). `movies_list` permet de réutiliser
    une liste déjà récupérée (évite un GET complet par appel pour plusieurs lookups).

    Returns:
        Dictionnaire Radarr brut ou None si introuvable.
    """
    url.rstrip("/")
    try:
        client = ArrClient(url, api_key, timeout=15)
        if arr_id:
            resp = await client.get(f"/api/v3/movie/{arr_id}")
            if resp.status_code == 200:
                return resp.json()
        if tmdb_id or imdb_id:
            movies = movies_list
            if movies is None:
                resp = await client.get("/api/v3/movie")
                resp.raise_for_status()
                movies = resp.json()
            for m in movies:
                if tmdb_id and str(m.get("tmdbId")) == str(tmdb_id):
                    return m
                if imdb_id and m.get("imdbId") == imdb_id:
                    return m
    except Exception as e:
        logger.warning(f"Radarr lookup failed: {e}")
    return None


async def is_movie_available(
    url: str,
    api_key: str,
    arr_id: int = None,
    tmdb_id: str = None,
    imdb_id: str = None,
    movies_list: list[dict] | None = None,
) -> tuple[bool, int | None, str | None]:
    """Vérifie si le fichier film est présent dans Radarr (hasFile=true).

    Returns:
        (is_available, arr_id, title_slug)
    """
    data = await lookup_movie(
        url, api_key, arr_id=arr_id, tmdb_id=tmdb_id, imdb_id=imdb_id, movies_list=movies_list
    )
    if not data:
        return False, None, None
    return data.get("hasFile", False), data.get("id"), data.get("titleSlug")


async def search_movie(url: str, api_key: str, movie_id: int) -> bool:
    """Lance une recherche de fichier pour un film Radarr (commande MoviesSearch)."""
    return await arr_common.run_search_command(
        url,
        api_key,
        product=PRODUCT,
        command="MoviesSearch",
        payload={"movieIds": [movie_id]},
        log_context=f"movie {movie_id}",
    )


async def get_releases(url: str, api_key: str, movie_id: int) -> list[dict]:
    """Recherche interactive Radarr : releases scorées pour un film (GET /release)."""
    return await arr_common.get_releases(
        url,
        api_key,
        params={"movieId": movie_id},
        product=PRODUCT,
        log_context=f"movie {movie_id}",
    )


async def manual_import_movie(
    url: str,
    api_key: str,
    *,
    path: str,
    folder_name: str | None,
    movie_id: int,
    download_id: str | None,
    quality: dict | None,
    languages: list | None,
    release_group: str | None,
    indexer_flags: int | None,
) -> tuple[bool, str]:
    """Force l'import d'un fichier téléchargé sur un film (commande ManualImport)."""
    return await arr_common.manual_import(
        url,
        api_key,
        product=PRODUCT,
        file_entry={
            "path": path,
            "folderName": folder_name,
            "movieId": movie_id,
            "downloadId": download_id,
            "quality": quality,
            "languages": languages or [],
            "releaseGroup": release_group,
            "indexerFlags": indexer_flags or 0,
        },
    )


def _normalize_queue_record(r: dict, title: str, *, movie: dict | None = None) -> dict:
    """Réduit un enregistrement de file d'attente *arr à un format compact pour l'UI."""
    size, sizeleft, progress = arr_common.queue_progress(r)
    movie = movie or {}
    return {
        "queue_id": r.get("id"),
        "arr_media_id": r.get("movieId"),
        "title": title,
        "status": r.get("status"),  # queued / downloading / completed / paused / failed / warning
        "tracked_state": r.get("trackedDownloadState"),
        "tracked_status": r.get("trackedDownloadStatus"),
        "size": size,
        "sizeleft": sizeleft,
        "progress": progress,
        "timeleft": r.get("timeleft"),
        "download_client": r.get("downloadClient"),
        "indexer": r.get("indexer"),
        "protocol": r.get("protocol"),
        "error": r.get("errorMessage"),
        # Métadonnées portées par la file (déjà connues de Radarr) — utilisées pour
        # pré-remplir l'import manuel quand le lien vers une MediaRequest est absent.
        "year": movie.get("year"),
        "tmdb_id": movie.get("tmdbId"),
        "poster_url": arr_common.poster_from_images(movie.get("images")),
    }


async def get_queue(url: str, api_key: str, *, raise_on_error: bool = False) -> list[dict]:
    """File d'attente de téléchargement Radarr (GET /queue), format compact."""
    records = await arr_common.fetch_queue_records(
        url,
        api_key,
        params={"pageSize": 100, "includeMovie": "true"},
        product=PRODUCT,
        raise_on_error=raise_on_error,
    )
    out = []
    for r in records:
        movie = r.get("movie") or {}
        title = movie.get("title") or r.get("title") or "?"
        out.append(_normalize_queue_record(r, title, movie=movie))
    return out
