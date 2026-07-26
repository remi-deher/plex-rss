"""
Client pour l'API Sonarr v3 (séries TV).

Fonctions principales :
- add_series             : ajoute une série et lance la recherche de fichiers
- is_series_available     : vérifie si au moins un fichier épisode existe (episodeFileCount > 0)
- get_series_episode_stats: compteurs d'épisodes (fichiers / diffusés / total) pour la
  disponibilité partielle des séries en cours de diffusion
- lookup_series           : recherche une série par arr_id ou tvdb_id
- test_connection         : vérifie la connectivité avec l'instance Sonarr
- get_quality_profiles / get_root_folders : données de configuration UI
"""

import logging
from datetime import datetime, timezone
from functools import partial

import httpx

from . import arr_common
from .arr_common import normalize_title as _norm_title
from .arr_http_client import ArrClient

logger = logging.getLogger(__name__)

PRODUCT = "Sonarr"

# Appels partagés avec Radarr (même API v3), pré-liés au nom du produit pour que les
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
# Sonarr a besoin de `includeSeries` pour le titre, les identifiants externes et l'affiche.
get_calendar = partial(
    arr_common.get_calendar, product=PRODUCT, extra_params={"includeSeries": "true"}
)
get_all_series = partial(arr_common.get_all_media, resource="series")
series_exists = partial(arr_common.media_exists, resource="series")
grab_release = partial(arr_common.grab_release, product=PRODUCT)
get_manual_import_candidates = partial(arr_common.get_manual_import_candidates, product=PRODUCT)
trigger_import = partial(
    arr_common.trigger_import, command="DownloadedEpisodesScan", product=PRODUCT
)
delete_queue_item = partial(arr_common.delete_queue_item, product=PRODUCT)
get_queue_series_ids = partial(
    arr_common.get_queue_media_ids,
    id_key="seriesId",
    product=PRODUCT,
    log_name="get_queue_series_ids",
)
delete_series = partial(
    arr_common.delete_media,
    resource="series",
    exclusion_param="addImportListExclusion",
    absent_message="Déjà absente de Sonarr",
    deleted_message="Supprimée de Sonarr",
)
_normalize_release = arr_common.normalize_release


async def add_series(
    url: str,
    api_key: str,
    quality_profile_id: int,
    root_folder: str,
    item: dict,
    tag_ids: list[int] | None = None,
) -> tuple[int | None, bool, str | None]:
    """Ajoute une série à Sonarr, ou retourne son ID si elle existe déjà.

    Returns:
        (sonarr_id, already_existed, titleSlug)
        - already_existed=True signifie que la série était déjà dans Sonarr
          (la notification de demande ne doit pas être renvoyée).
    """
    url.rstrip("/")

    tvdb_id = item.get("tvdb_id")
    if not tvdb_id:
        # TVDB ID absent du flux RSS/API : résolution via Sonarr, en privilégiant
        # les IDs externes. Un lookup au titre seul peut matcher un homonyme.
        tvdb_id = await _search_tvdb_id(url, api_key, item)
    if not tvdb_id:
        logger.warning(f"Cannot find TVDB ID for '{item['title']}'")
        return None, False, None

    if not quality_profile_id:
        profiles = await get_quality_profiles(url, api_key)
        if profiles:
            quality_profile_id = profiles[0]["id"]
            
    if not root_folder:
        folders = await get_root_folders(url, api_key)
        if folders:
            root_folder = folders[0]["path"]

    # Vérification d'existence avant ajout pour retourner already_existed=True
    try:
        client = ArrClient(url, api_key, timeout=15)
        existing = await client.get("/api/v3/series")
        existing.raise_for_status()
        for s in existing.json():
            if str(s.get("tvdbId")) == str(tvdb_id):
                logger.info(f"'{item['title']}' already in Sonarr (id={s['id']})")
                return s["id"], True, s.get("titleSlug")
    except httpx.HTTPError:
        pass

    selected_seasons = item.get("seasons")
    seasons_payload = []
    if selected_seasons:
        seasons_payload = [
            {"seasonNumber": int(season_number), "monitored": True}
            for season_number in selected_seasons
            if int(season_number) >= 0
        ]

    payload = {
        "title": item["title"],
        "tvdbId": int(tvdb_id),
        "qualityProfileId": quality_profile_id,
        "rootFolderPath": root_folder,
        "monitored": True,
        "addOptions": {"searchForMissingEpisodes": True},
        "seasons": seasons_payload,
        "tags": tag_ids or [],
    }

    try:
        client = ArrClient(url, api_key, timeout=30)
        resp = await client.post("/api/v3/series", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not selected_seasons:
            data = await _disable_specials_by_default(client, data)
        return data.get("id"), False, data.get("titleSlug")
    except httpx.HTTPStatusError as e:
        body = e.response.text if hasattr(e, 'response') else ''
        b_lower = body.lower()
        if e.response.status_code == 400 and ("seriesexistsvalidator" in b_lower or "already been added" in b_lower or "already configured" in b_lower or "déjà été ajouté" in b_lower or "déjà configuré" in b_lower or "deja ete ajoute" in b_lower or "deja configure" in b_lower):
            logger.info(f"'{item['title']}' already in Sonarr (caught 400 Exists/PathConfigured)")
            return None, True, None
        logger.error(f"Sonarr error adding '{item['title']}': {e} — response: {body}")
        raise
    except httpx.HTTPError as e:
        logger.error(f"Sonarr error adding '{item['title']}': {e}")
        raise


async def _disable_specials_by_default(client: ArrClient, series: dict) -> dict:
    """Désactive la saison 0 pour un ajout sans sélection explicite."""
    if not isinstance(series, dict) or not series.get("id"):
        return series
    original = series

    seasons = series.get("seasons")
    if not isinstance(seasons, list):
        try:
            resp = await client.get(f"/api/v3/series/{series['id']}")
            resp.raise_for_status()
            series = resp.json()
            if not isinstance(series, dict):
                return original
            seasons = series.get("seasons")
        except (httpx.HTTPError, StopAsyncIteration):
            logger.warning("Unable to read seasons after adding series id=%s", series.get("id"))
            return original

    if not isinstance(seasons, list):
        return series

    changed = False
    for season in seasons:
        if season.get("seasonNumber") == 0 and season.get("monitored") is not False:
            season["monitored"] = False
            changed = True
    if not changed:
        return series

    update = await client.put(f"/api/v3/series/{series['id']}", json=series)
    update.raise_for_status()
    return update.json()


def _norm_external_id(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _same_external_id(candidate, expected) -> bool:
    candidate = _norm_external_id(candidate)
    expected = _norm_external_id(expected)
    return bool(candidate and expected and candidate == expected)


def _candidate_matches_item(candidate: dict, item: dict, *, strict_ids: bool = False) -> bool:
    """Valide qu'un résultat Sonarr correspond bien à l'item Plex demandé."""
    if _same_external_id(candidate.get("tvdbId"), item.get("tvdb_id")):
        return True
    if _same_external_id(candidate.get("tmdbId"), item.get("tmdb_id")):
        return True
    if _same_external_id(candidate.get("imdbId"), item.get("imdb_id")):
        return True

    if strict_ids and (item.get("tvdb_id") or item.get("tmdb_id") or item.get("imdb_id")):
        return False

    expected_title = _norm_title(item.get("title"))
    candidate_title = _norm_title(candidate.get("title"))
    if expected_title and candidate_title and expected_title == candidate_title:
        item_year = item.get("year")
        candidate_year = candidate.get("year")
        return not item_year or not candidate_year or str(item_year) == str(candidate_year)
    return False


async def _lookup_series_candidates(url: str, api_key: str, term: str) -> list[dict]:
    try:
        client = ArrClient(url, api_key, timeout=15)
        resp = await client.get(
            "/api/v3/series/lookup",
            params={"term": term},
            )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"Sonarr lookup failed for '{term}': {e}")
    return []


async def _search_tvdb_id(url: str, api_key: str, item: dict) -> str | None:
    """Cherche un TVDB ID via le lookup Sonarr (fallback quand absent du flux/API)."""
    for key, prefix in (("imdb_id", "imdb"), ("tmdb_id", "tmdb")):
        value = _norm_external_id(item.get(key))
        if not value:
            continue
        for candidate in await _lookup_series_candidates(url, api_key, f"{prefix}:{value}"):
            if _candidate_matches_item(candidate, item, strict_ids=True) and candidate.get("tvdbId"):
                return str(candidate["tvdbId"])

    title = item.get("title")
    if not title:
        return None
    terms = [f"{title} {item['year']}"] if item.get("year") else []
    terms.append(title)

    seen_terms = set()
    for term in terms:
        if term in seen_terms:
            continue
        seen_terms.add(term)
        for candidate in await _lookup_series_candidates(url, api_key, term):
            if _candidate_matches_item(candidate, item, strict_ids=True) and candidate.get("tvdbId"):
                return str(candidate["tvdbId"])

    if item.get("tmdb_id") or item.get("imdb_id"):
        logger.warning(
            "Sonarr lookup for '%s' returned no result matching external IDs "
            "(tmdb=%s, imdb=%s); refusing ambiguous title match",
            item.get("title"),
            item.get("tmdb_id"),
            item.get("imdb_id"),
        )
        return None

    # Dernier filet pour les vieux flux sans identifiants : titre exact + année.
    try:
        for candidate in await _lookup_series_candidates(url, api_key, terms[0]):
            if _candidate_matches_item(candidate, item) and candidate.get("tvdbId"):
                return str(candidate["tvdbId"])
    except Exception as e:
        logger.warning(f"Sonarr title fallback failed for '{title}': {e}")
    return None


async def lookup_series(
    url: str,
    api_key: str,
    arr_id: int = None,
    tvdb_id: str = None,
    tmdb_id: str = None,
    imdb_id: str = None,
    series_list: list[dict] | None = None,
) -> dict | None:
    """Recherche une série par arr_id (GET direct) ou par tvdb_id (scan de la liste).

    Le lookup par arr_id est O(1) ; le fallback tvdb_id est O(n) sur la liste complète.
    `series_list` permet de réutiliser une liste déjà récupérée (évite un GET complet
    par appel quand plusieurs lookups par tvdb_id sont faits dans la même opération).

    Returns:
        Dictionnaire Sonarr brut ou None si introuvable.
    """
    url.rstrip("/")
    try:
        client = ArrClient(url, api_key, timeout=15)
        if arr_id:
            resp = await client.get(f"/api/v3/series/{arr_id}")
            if resp.status_code == 200:
                data = resp.json()
                expected = {"tvdb_id": tvdb_id, "tmdb_id": tmdb_id, "imdb_id": imdb_id}
                if not any(expected.values()) or _candidate_matches_item(data, expected, strict_ids=True):
                    return data
                logger.warning(
                    "Sonarr arr_id %s points to '%s' but expected IDs are tvdb=%s, tmdb=%s, imdb=%s",
                    arr_id,
                    data.get("title"),
                    tvdb_id,
                    tmdb_id,
                    imdb_id,
                )
        if tvdb_id or tmdb_id or imdb_id:
            series = series_list
            if series is None:
                resp = await client.get("/api/v3/series")
                resp.raise_for_status()
                series = resp.json()
            for s in series:
                if tvdb_id and str(s.get("tvdbId")) == str(tvdb_id):
                    return s
                if tmdb_id and str(s.get("tmdbId")) == str(tmdb_id):
                    return s
                if imdb_id and s.get("imdbId") == imdb_id:
                    return s
    except Exception as e:
        logger.warning(f"Sonarr lookup failed: {e}")
    return None


async def get_series_episode_stats(
    url: str,
    api_key: str,
    arr_id: int = None,
    tvdb_id: str = None,
    tmdb_id: str = None,
    imdb_id: str = None,
    series_list: list[dict] | None = None,
) -> dict | None:
    """Statistiques d'épisodes d'une série Sonarr, pour distinguer une disponibilité
    partielle (série en cours de diffusion) d'une disponibilité complète.

    - episode_file_count : épisodes avec un fichier sur disque
    - episode_count       : épisodes déjà diffusés à ce jour (Sonarr statistics.episodeCount)
    - total_episode_count : total de la série, diffusés + à venir (statistics.totalEpisodeCount)
    - seasons             : même détail, par saison (mêmes clés statistics.* que Sonarr
      expose déjà pour la série entière — aucun appel réseau supplémentaire, seulement
      jeté jusqu'ici). Seules les saisons surveillées par Sonarr sont retenues, y compris
      la saison 0 lorsqu'elle est surveillée.

    Retourne None si la série n'est pas trouvée dans Sonarr.
    """
    data = await lookup_series(
        url,
        api_key,
        arr_id=arr_id,
        tvdb_id=tvdb_id,
        tmdb_id=tmdb_id,
        imdb_id=imdb_id,
        series_list=series_list,
    )
    if not data:
        return None
    return {"arr_id": data.get("id"), "title_slug": data.get("titleSlug"), **aggregate_monitored_episode_stats(data)}


def aggregate_monitored_episode_stats(data: dict) -> dict:
    """Agrège les statistiques d'épisodes d'une série Sonarr sur ses seules saisons
    surveillées (exclut les spéciaux/saisons désactivées côté Sonarr).

    Fonctionne aussi bien sur le dict brut d'un `GET /api/v3/series/{id}` que sur un
    élément de la liste `GET /api/v3/series` (les deux exposent le même détail par
    saison) — aucun appel réseau supplémentaire n'est nécessaire pour l'utiliser sur
    des séries déjà chargées en liste (voir `get_all_series`).

    - episode_file_count : épisodes avec un fichier sur disque
    - episode_count       : épisodes déjà diffusés à ce jour (Sonarr statistics.episodeCount)
    - total_episode_count : total de la série, diffusés + à venir (statistics.totalEpisodeCount)
    """
    stats = data.get("statistics", {}) or {}
    season_details = data.get("seasons", []) or []
    seasons = []
    monitored_totals = {"episodeFileCount": 0, "episodeCount": 0, "totalEpisodeCount": 0}
    for season in season_details:
        season_number = season.get("seasonNumber")
        # La saison 0 est valide si elle est explicitement surveillée.
        if season.get("monitored") is not True:
            continue
        season_stats = season.get("statistics", {}) or {}
        for key in monitored_totals:
            monitored_totals[key] += season_stats.get(key, 0) or 0
        seasons.append({
            "season_number": season_number,
            "episode_file_count": season_stats.get("episodeFileCount", 0),
            "episode_count": season_stats.get("episodeCount", 0),
            "total_episode_count": season_stats.get("totalEpisodeCount", 0),
        })
    aggregate = monitored_totals if season_details else stats
    return {
        "episode_file_count": aggregate.get("episodeFileCount", 0),
        "episode_count": aggregate.get("episodeCount", 0),
        "total_episode_count": aggregate.get("totalEpisodeCount", 0),
        "seasons": seasons,
    }


async def is_series_available(
    url: str,
    api_key: str,
    arr_id: int = None,
    tvdb_id: str = None,
    tmdb_id: str = None,
    imdb_id: str = None,
    series_list: list[dict] | None = None,
) -> tuple[bool, int | None, str | None]:
    """Vérifie si une série a au moins un fichier épisode dans Sonarr.

    Returns:
        (is_available, arr_id, title_slug)
    """
    stats = await get_series_episode_stats(
        url,
        api_key,
        arr_id=arr_id,
        tvdb_id=tvdb_id,
        tmdb_id=tmdb_id,
        imdb_id=imdb_id,
        series_list=series_list,
    )
    if not stats:
        return False, None, None
    return stats["episode_file_count"] > 0, stats["arr_id"], stats["title_slug"]


async def search_series(url: str, api_key: str, series_id: int) -> bool:
    """Lance une recherche de fichiers pour une série Sonarr (commande SeriesSearch)."""
    return await arr_common.run_search_command(
        url,
        api_key,
        product=PRODUCT,
        command="SeriesSearch",
        payload={"seriesId": series_id},
        log_context=f"series {series_id}",
    )


async def get_releases(url: str, api_key: str, series_id: int = None, episode_id: int = None) -> list[dict]:
    """Recherche interactive Sonarr : releases scorées pour une série ou un épisode."""
    if episode_id:
        params = {"episodeId": episode_id}
    elif series_id:
        params = {"seriesId": series_id}
    else:
        return []
    return await arr_common.get_releases(
        url,
        api_key,
        params=params,
        product=PRODUCT,
        log_context=f"series {series_id}, ep {episode_id}",
    )


async def get_episodes(url: str, api_key: str, series_id: int) -> list[dict]:
    """Retourne tous les épisodes d'une série Sonarr (saison, numéro, titre, présence fichier).

    Utilisé pour le détail VF par saison/épisode : Sonarr donne la liste attendue
    complète (y compris épisodes non encore téléchargés), Plex fournit la VF réelle.
    """
    url.rstrip("/")
    client = ArrClient(url, api_key, timeout=20)
    resp = await client.get(
        "/api/v3/episode",
        params={"seriesId": series_id},
    )
    resp.raise_for_status()
    return resp.json()


async def get_season_aired_episode_counts(url: str, api_key: str, series_id: int) -> dict[int, int]:
    """Nombre d'épisodes surveillés déjà diffusés, par saison (saison 0/spéciales exclue).

    Sert à distinguer une vraie "saison complète" (tous les épisodes déjà diffusés sont
    présents) d'un simple "tous les épisodes *connus jusqu'ici*" — un scan Plex/VFF ne
    remonte que les épisodes déjà importés, donc un début de saison (1 seul épisode
    sorti) matcherait à tort "tous correspondent" sans ce compteur de référence.
    """
    episodes = await get_episodes(url, api_key, series_id)
    now = datetime.now(timezone.utc)
    counts: dict[int, int] = {}
    for ep in episodes:
        if not ep.get("monitored", True):
            continue
        season = ep.get("seasonNumber")
        if not season:  # None ou 0 (spéciales)
            continue
        air_date = ep.get("airDateUtc")
        if not air_date:
            continue
        try:
            aired_at = datetime.fromisoformat(air_date.replace("Z", "+00:00"))
        except ValueError:
            continue
        if aired_at > now:
            continue
        counts[season] = counts.get(season, 0) + 1
    return counts


def _normalize_queue_record(r: dict, title: str, *, series: dict | None = None, episode: dict | None = None) -> dict:
    """Réduit un enregistrement de file d'attente Sonarr à un format compact pour l'UI."""
    size, sizeleft, progress = arr_common.queue_progress(r)
    series = series or {}
    episode = episode or {}
    return {
        "queue_id": r.get("id"),
        "arr_media_id": r.get("seriesId"),
        "download_id": r.get("downloadId"),
        "output_path": r.get("outputPath"),
        "title": title,
        "status": r.get("status"),
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
        "status_messages": r.get("statusMessages") or [],
        "series_seasons": [
            {
                "season_number": season.get("seasonNumber"),
                "monitored": bool(season.get("monitored")),
            }
            for season in (series.get("seasons") or [])
            if season.get("seasonNumber") is not None
        ],
        # Métadonnées portées par la file (déjà connues de Sonarr) — utilisées pour
        # pré-remplir l'import manuel quand le lien vers une MediaRequest est absent.
        "series_title": series.get("title"),
        "year": series.get("year"),
        "tvdb_id": series.get("tvdbId"),
        "season_number": episode.get("seasonNumber"),
        "episode_number": episode.get("episodeNumber"),
        "poster_url": arr_common.poster_from_images(series.get("images")),
    }


async def manual_import_episode(
    url: str,
    api_key: str,
    *,
    path: str,
    folder_name: str | None,
    series_id: int,
    episode_id: int,
    download_id: str | None,
    quality: dict | None,
    languages: list | None,
    release_group: str | None,
    indexer_flags: int | None,
) -> tuple[bool, str]:
    """Force l'import d'un fichier téléchargé sur un épisode choisi manuellement."""
    return await arr_common.manual_import(
        url,
        api_key,
        product=PRODUCT,
        file_entry={
            "path": path,
            "folderName": folder_name,
            "seriesId": series_id,
            "episodeIds": [episode_id],
            "downloadId": download_id,
            "quality": quality,
            "languages": languages or [],
            "releaseGroup": release_group,
            "indexerFlags": indexer_flags or 0,
        },
    )


async def get_queue(url: str, api_key: str, *, raise_on_error: bool = False) -> list[dict]:
    """File d'attente de téléchargement Sonarr (GET /queue), format compact."""
    records = await arr_common.fetch_queue_records(
        url,
        api_key,
        params={"pageSize": 100, "includeSeries": "true", "includeEpisode": "true"},
        product=PRODUCT,
        raise_on_error=raise_on_error,
    )
    out = []
    for r in records:
        series_obj = r.get("series") or {}
        series = series_obj.get("title")
        ep = r.get("episode") or {}
        sn, en = ep.get("seasonNumber"), ep.get("episodeNumber")
        if series and sn is not None and en is not None:
            title = f"{series} — S{sn:02d}E{en:02d}"
        else:
            title = series or r.get("title") or "?"
        out.append(_normalize_queue_record(r, title, series=series_obj, episode=ep))
    return out
