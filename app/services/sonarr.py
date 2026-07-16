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
import re
from datetime import datetime, timezone

import httpx
from .arr_http_client import ArrClient

logger = logging.getLogger(__name__)


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
    headers = {"X-Api-Key": api_key}
    base = url.rstrip("/")

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
        existing = await client.get(f"/api/v3/series")
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
        resp = await client.post(f"/api/v3/series", json=payload)
        resp.raise_for_status()
        data = resp.json()
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


def _norm_external_id(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _same_external_id(candidate, expected) -> bool:
    candidate = _norm_external_id(candidate)
    expected = _norm_external_id(expected)
    return bool(candidate and expected and candidate == expected)


def _norm_title(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


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
            f"/api/v3/series/lookup",
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


async def get_all_series(url: str, api_key: str) -> list[dict]:
    """Retourne la liste complète des séries connues de Sonarr (pour le scan de fallback)."""
    base = url.rstrip("/")
    client = ArrClient(url, api_key, timeout=15)
    resp = await client.get(f"/api/v3/series")
    resp.raise_for_status()
    return resp.json()


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
    base = url.rstrip("/")
    headers = {"X-Api-Key": api_key}
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
                resp = await client.get(f"/api/v3/series")
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
    stats = data.get("statistics", {})
    return {
        "arr_id": data.get("id"),
        "title_slug": data.get("titleSlug"),
        "episode_file_count": stats.get("episodeFileCount", 0),
        "episode_count": stats.get("episodeCount", 0),
        "total_episode_count": stats.get("totalEpisodeCount", 0),
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


async def series_exists(url: str, api_key: str, arr_id: int) -> bool:
    """Vérifie par GET direct si une série existe encore dans Sonarr.

    Contrairement à `lookup_series`, ne catch PAS les erreurs réseau/HTTP : elles
    remontent à l'appelant pour ne jamais être confondues avec un 404 confirmé
    (Sonarr injoignable != série supprimée).
    """
    base = url.rstrip("/")
    client = ArrClient(url, api_key, timeout=15)
    resp = await client.get(f"/api/v3/series/{arr_id}")
    if resp.status_code == 404:
        return False
    resp.raise_for_status()
    return True


async def delete_series(url: str, api_key: str, arr_id: int, delete_files: bool = False) -> tuple[bool, str]:
    """Supprime une série de Sonarr (et ses fichiers si demandé).

    Un 404 est traité comme un succès (déjà absente). Toute autre erreur (réseau,
    timeout, 5xx) lève une exception — l'appelant ne doit jamais supprimer la
    demande locale correspondante si cet appel échoue.
    """
    base = url.rstrip("/")
    client = ArrClient(url, api_key, timeout=20)
    resp = await client.delete(
        f"/api/v3/series/{arr_id}",
        params={"deleteFiles": "true" if delete_files else "false", "addImportListExclusion": "false"},
    )
    if resp.status_code == 404:
        return True, "Déjà absente de Sonarr"
    resp.raise_for_status()
    return True, "Supprimée de Sonarr"


async def search_series(url: str, api_key: str, series_id: int) -> bool:
    """Lance une recherche de fichiers pour une série Sonarr (commande SeriesSearch).

    Utilisé par l'auto-search VFF : relance une recherche quand une série n'est
    disponible qu'en VO, dans l'espoir de trouver une version française.
    """
    base = url.rstrip("/")
    try:
        client = ArrClient(url, api_key, timeout=15)
        resp = await client.post(
            f"/api/v3/command",
            json={"name": "SeriesSearch", "seriesId": series_id},
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.warning(f"Sonarr SeriesSearch échec (series {series_id}): {e}")
        return False


def _normalize_release(r: dict) -> dict:
    """Réduit une release Sonarr à un format compact pour l'UI (qualité, langues, score CF)."""
    langs = [lang.get("name") for lang in (r.get("languages") or []) if lang.get("name")]
    quality = ((r.get("quality") or {}).get("quality") or {}).get("name")
    return {
        "guid": r.get("guid"),
        "title": r.get("title"),
        "indexer": r.get("indexer"),
        "indexer_id": r.get("indexerId"),
        "size": r.get("size"),
        "seeders": r.get("seeders", 0),
        "leechers": r.get("leechers", 0),
        "protocol": r.get("protocol"),
        "quality": quality,
        "languages": langs,
        "custom_format_score": r.get("customFormatScore", 0),
        "custom_formats": [cf.get("name") for cf in (r.get("customFormats") or []) if cf.get("name")],
        "rejected": r.get("rejected", False),
        "rejections": r.get("rejections") or [],
    }


async def get_releases(url: str, api_key: str, series_id: int = None, episode_id: int = None) -> list[dict]:
    """Recherche interactive Sonarr : releases scorées pour une série ou un épisode."""
    base = url.rstrip("/")
    params = {}
    if episode_id:
        params["episodeId"] = episode_id
    elif series_id:
        params["seriesId"] = series_id
    else:
        return []
    try:
        client = ArrClient(url, api_key, timeout=90)
        resp = await client.get(f"/api/v3/release", params=params)
        resp.raise_for_status()
        return [_normalize_release(r) for r in resp.json()]
    except Exception as e:
        logger.warning(f"Sonarr get_releases échec (series {series_id}, ep {episode_id}): {e}")
        return []


async def grab_release(url: str, api_key: str, guid: str, indexer_id: int) -> tuple[bool, str]:
    """Grab d'une release choisie manuellement : Sonarr télécharge ET importe."""
    base = url.rstrip("/")
    try:
        client = ArrClient(url, api_key, timeout=30)
        resp = await client.post(
            f"/api/v3/release",
            json={"guid": guid, "indexerId": indexer_id},
        )
        resp.raise_for_status()
        return True, "Release envoyée à Sonarr"
    except Exception as e:
        logger.warning(f"Sonarr grab_release échec (guid {guid}): {e}")
        return False, str(e)


async def get_episodes(url: str, api_key: str, series_id: int) -> list[dict]:
    """Retourne tous les épisodes d'une série Sonarr (saison, numéro, titre, présence fichier).

    Utilisé pour le détail VF par saison/épisode : Sonarr donne la liste attendue
    complète (y compris épisodes non encore téléchargés), Plex fournit la VF réelle.
    """
    base = url.rstrip("/")
    client = ArrClient(url, api_key, timeout=20)
    resp = await client.get(
        f"/api/v3/episode",
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
    size = r.get("size") or 0
    sizeleft = r.get("sizeleft") or 0
    progress = round((size - sizeleft) / size * 100, 1) if size else 0
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
        # Métadonnées portées par la file (déjà connues de Sonarr) — utilisées pour
        # pré-remplir l'import manuel quand le lien vers une MediaRequest est absent.
        "series_title": series.get("title"),
        "year": series.get("year"),
        "tvdb_id": series.get("tvdbId"),
        "season_number": episode.get("seasonNumber"),
        "episode_number": episode.get("episodeNumber"),
        "poster_url": next(
            (
                img.get("remoteUrl") or img.get("url")
                for img in series.get("images", [])
                if img.get("coverType") == "poster"
            ),
            None,
        ),
    }


async def get_manual_import_candidates(url: str, api_key: str, download_id: str) -> list[dict]:
    """Fichiers en attente d'import manuel pour un téléchargement (GET /manualimport).

    Utilisé quand Sonarr ne peut pas matcher automatiquement un épisode (ex : épisode
    pas encore officiellement sorti dans ses métadonnées), pour laisser l'utilisateur
    choisir l'épisode à la main, comme dans l'UI native de Sonarr.
    """
    base = url.rstrip("/")
    try:
        client = ArrClient(url, api_key, timeout=20)
        resp = await client.get(
            f"/api/v3/manualimport",
            params={"downloadId": download_id, "filterExistingFiles": "true"},
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"Sonarr get_manual_import_candidates échec: {e}")
        return []


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
    base = url.rstrip("/")
    file_entry = {
        "path": path,
        "folderName": folder_name,
        "seriesId": series_id,
        "episodeIds": [episode_id],
        "downloadId": download_id,
        "quality": quality,
        "languages": languages or [],
        "releaseGroup": release_group,
        "indexerFlags": indexer_flags or 0,
    }
    try:
        client = ArrClient(url, api_key, timeout=20)
        resp = await client.post(
            f"/api/v3/command",
            json={"name": "ManualImport", "files": [file_entry], "importMode": "auto"},
        )
        resp.raise_for_status()
        return True, "Import manuel lancé"
    except httpx.HTTPStatusError as e:
        return False, f"Sonarr a refusé l'import : {e.response.text[:200]}"
    except Exception as e:
        return False, str(e)


async def trigger_import(
    url: str,
    api_key: str,
    *,
    output_path: str | None = None,
    download_id: str | None = None,
) -> tuple[bool, str]:
    """Déclenche le scan d'import Sonarr pour un téléchargement en attente d'import
    (trackedDownloadState == importPending). Utilise la commande DownloadedEpisodesScan
    avec le chemin de sortie ou le downloadId.
    """
    base = url.rstrip("/")
    payload: dict = {"name": "DownloadedEpisodesScan"}
    if output_path:
        payload["path"] = output_path
    if download_id:
        payload["downloadClientId"] = download_id
    try:
        client = ArrClient(url, api_key, timeout=20)
        resp = await client.post(
            f"/api/v3/command",
            json=payload,
        )
        resp.raise_for_status()
        return True, "Import lancé"
    except httpx.HTTPStatusError as e:
        return False, f"Sonarr a refusé l'import : {e.response.text[:200]}"
    except Exception as e:
        return False, str(e)


async def get_queue(url: str, api_key: str) -> list[dict]:
    """File d'attente de téléchargement Sonarr (GET /queue), format compact."""
    base = url.rstrip("/")
    try:
        client = ArrClient(url, api_key, timeout=20)
        resp = await client.get(
            f"/api/v3/queue",
            params={"pageSize": 100, "includeSeries": "true", "includeEpisode": "true"},
        )
        resp.raise_for_status()
        records = resp.json().get("records", [])
    except Exception as e:
        logger.warning(f"Sonarr get_queue échec: {e}")
        return []
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


async def delete_queue_item(
    url: str, api_key: str, queue_id: int, *, blocklist: bool = False, search: bool = True
) -> tuple[bool, str]:
    """Supprime un item de la file d'attente Sonarr, avec blocklist et relance de recherche optionnelles."""
    base = url.rstrip("/")
    try:
        client = ArrClient(url, api_key, timeout=20)
        resp = await client.delete(
            f"/api/v3/queue/{queue_id}",
            params={
                "removeFromClient": "true",
                "blocklist": "true" if blocklist else "false",
                "skipRedownload": "false" if search else "true",
            },
        )
        if resp.status_code in (200, 204):
            return True, "Item supprimé de la file Sonarr"
        resp.raise_for_status()
        return True, "Item supprimé de la file Sonarr"
    except Exception as e:
        logger.warning(f"Sonarr delete_queue_item échec (queue {queue_id}): {e}")
        return False, str(e)


async def get_queue_series_ids(url: str, api_key: str) -> set[int]:
    """IDs des séries ayant au moins un item actif dans la file de téléchargement Sonarr.

    Utilisé pour distinguer une vraie anomalie Plex (fichier importé mais introuvable dans
    Plex) d'une série encore partiellement en cours de téléchargement (ex: d'autres épisodes
    de la même série toujours en file pendant qu'un premier épisode est déjà disponible).
    """
    base = url.rstrip("/")
    try:
        client = ArrClient(url, api_key, timeout=20)
        resp = await client.get(
            f"/api/v3/queue",
            params={"pageSize": 200},
        )
        resp.raise_for_status()
        records = resp.json().get("records", [])
    except Exception as e:
        logger.warning(f"Sonarr get_queue_series_ids échec: {e}")
        return set()
    return {r["seriesId"] for r in records if r.get("seriesId")}


async def check_connection(url: str, api_key: str) -> tuple[bool, str]:
    """Teste la connectivité avec l'instance Sonarr.

    Returns:
        (success, message)
    """
    try:
        client = ArrClient(url, api_key, timeout=10)
        resp = await client.get(
            "/api/v3/system/status",
        )
        resp.raise_for_status()
        data = resp.json()
        return True, f"Sonarr v{data.get('version', '?')} connecté"
    except Exception as e:
        return False, str(e)


async def get_notifications(url: str, api_key: str) -> list[dict]:
    """Retourne les connecteurs de notification configurés dans Sonarr (Settings → Connect)."""
    client = ArrClient(url, api_key, timeout=10)
    resp = await client.get(
        "/api/v3/notification",
    )
    resp.raise_for_status()
    return resp.json()


def find_webhook_notification(notifications: list[dict], webhook_path: str) -> dict | None:
    """Trouve, parmi les connecteurs Sonarr, celui de type Webhook pointant vers notre endpoint."""
    for notif in notifications:
        if notif.get("implementation") != "Webhook":
            continue
        for field in notif.get("fields", []):
            if field.get("name") == "url" and webhook_path in str(field.get("value", "")):
                return notif
    return None


def find_plex_notification(notifications: list[dict]) -> dict | None:
    """Trouve le connecteur natif 'Plex Media Server' de Sonarr, actif sur import/téléchargement.

    S'il existe, Sonarr notifie déjà Plex directement (scan ciblé sur le dossier importé)
    à chaque import — pas la peine de dupliquer avec notre propre refresh de section.
    """
    for notif in notifications:
        if notif.get("implementation") == "PlexServer" and (notif.get("onDownload") or notif.get("onImport")):
            return notif
    return None


async def test_notification(url: str, api_key: str, notification: dict) -> tuple[bool, str]:
    """Déclenche depuis Sonarr un test réel du connecteur Webhook (round-trip vers notre endpoint).

    Réutilise l'endpoint /api/v3/notification/test de Sonarr, qui envoie une notification de
    test avec la configuration fournie sans la re-sauvegarder.
    """
    base = url.rstrip("/")
    try:
        client = ArrClient(url, api_key, timeout=20)
        resp = await client.post(
            f"/api/v3/notification/test",
            json=notification,
        )
        if resp.status_code in (200, 204):
            return True, "Test envoyé et accepté par Sonarr"
        try:
            errors = resp.json()
            msg = (
                "; ".join(e.get("errorMessage", str(e)) for e in errors)
                if isinstance(errors, list)
                else str(errors)
            )
        except Exception:
            msg = resp.text
        return False, msg or f"HTTP {resp.status_code}"
    except Exception as e:
        return False, str(e)


async def get_webhook_schema(url: str, api_key: str) -> dict | None:
    """Retourne le schéma vierge du connecteur 'Webhook' (pour en créer un nouveau)."""
    client = ArrClient(url, api_key, timeout=10)
    resp = await client.get("/api/v3/notification/schema")
    resp.raise_for_status()
    for entry in resp.json():
        if entry.get("implementation") == "Webhook":
            return entry
    return None


def build_webhook_payload(schema: dict, webhook_url: str, flags: dict[str, bool], name: str = "Plexarr") -> dict:
    """Construit le payload de création d'un connecteur Webhook à partir du schéma Sonarr,
    en pré-remplissant l'URL et en n'activant que les événements passés dans `flags`."""
    payload = {k: v for k, v in schema.items() if k != "id"}
    fields = []
    for field in schema.get("fields", []):
        field = dict(field)
        if field.get("name") == "url":
            field["value"] = webhook_url
        elif field.get("name") == "method":
            field["value"] = 1  # POST
        fields.append(field)
    payload["fields"] = fields
    payload["name"] = name
    payload.update(flags)
    return payload


async def create_notification(url: str, api_key: str, payload: dict) -> dict:
    """Crée un nouveau connecteur de notification dans Sonarr (Settings → Connect)."""
    client = ArrClient(url, api_key, timeout=15)
    resp = await client.post("/api/v3/notification", json=payload)
    resp.raise_for_status()
    return resp.json()


async def update_notification(url: str, api_key: str, notification: dict) -> dict:
    """Met à jour un connecteur de notification existant dans Sonarr."""
    client = ArrClient(url, api_key, timeout=15)
    resp = await client.put(f"/api/v3/notification/{notification['id']}", json=notification)
    resp.raise_for_status()
    return resp.json()


async def get_quality_profiles(url: str, api_key: str) -> list[dict]:
    """Retourne les profils de qualité disponibles (pour le formulaire de config)."""
    client = ArrClient(url, api_key, timeout=10)
    resp = await client.get(
        "/api/v3/qualityprofile",
    )
    resp.raise_for_status()
    return [{"id": p["id"], "name": p["name"]} for p in resp.json()]


async def get_root_folders(url: str, api_key: str) -> list[dict]:
    """Retourne les dossiers racine configurés dans Sonarr (pour le formulaire de config)."""
    client = ArrClient(url, api_key, timeout=10)
    resp = await client.get(
        "/api/v3/rootfolder",
    )
    resp.raise_for_status()
    return [
        {
            "path": f["path"],
            "free_bytes": f.get("freeSpace"),
            "total_bytes": f.get("totalSpace"),
        }
        for f in resp.json()
    ]


async def get_tags(url: str, api_key: str) -> list[dict]:
    """Retourne les tags configurés dans Sonarr (id + label)."""
    client = ArrClient(url, api_key, timeout=10)
    resp = await client.get(
        "/api/v3/tag",
    )
    resp.raise_for_status()
    return [{"id": t["id"], "label": t["label"]} for t in resp.json()]


async def get_disk_space(url: str, api_key: str) -> list[dict]:
    """Retourne l'espace disque des volumes connus de Sonarr.

    Returns:
        Liste de {path, free_bytes, total_bytes}.
    """
    client = ArrClient(url, api_key, timeout=10)
    resp = await client.get(
        "/api/v3/diskspace",
    )
    resp.raise_for_status()
    return [{"path": d["path"], "free_bytes": d["freeSpace"], "total_bytes": d["totalSpace"]} for d in resp.json()]


async def get_calendar(url: str, api_key: str, start: str, end: str) -> list[dict]:
    """Épisodes attendus/diffusés entre deux dates (GET /api/v3/calendar).

    `start`/`end` : dates ISO 8601. Chaque entrée inclut la série (includeSeries=true)
    pour le titre, les identifiants externes et l'affiche.
    """
    try:
        client = ArrClient(url, api_key, timeout=20)
        resp = await client.get(
            "/api/v3/calendar",
            params={"start": start, "end": end, "includeSeries": "true"},
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Sonarr get_calendar failed: {e}")
        return []
