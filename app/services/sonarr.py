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

import httpx

logger = logging.getLogger(__name__)


async def add_series(
    sonarr_url: str,
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
    base = sonarr_url.rstrip("/")

    tvdb_id = item.get("tvdb_id")
    if not tvdb_id:
        # TVDB ID absent du flux RSS/API : résolution via Sonarr, en privilégiant
        # les IDs externes. Un lookup au titre seul peut matcher un homonyme.
        tvdb_id = await _search_tvdb_id(base, headers, item)
    if not tvdb_id:
        logger.warning(f"Cannot find TVDB ID for '{item['title']}'")
        return None, False, None

    # Vérification d'existence avant ajout pour retourner already_existed=True
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            existing = await client.get(f"{base}/api/v3/series", headers=headers)
            existing.raise_for_status()
            for s in existing.json():
                if str(s.get("tvdbId")) == str(tvdb_id):
                    logger.info(f"'{item['title']}' already in Sonarr (id={s['id']})")
                    return s["id"], True, s.get("titleSlug")
    except httpx.HTTPError:
        pass

    payload = {
        "title": item["title"],
        "tvdbId": int(tvdb_id),
        "qualityProfileId": quality_profile_id,
        "rootFolderPath": root_folder,
        "monitored": True,
        "addOptions": {"searchForMissingEpisodes": True},
        "seasons": [],
        "tags": tag_ids or [],
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{base}/api/v3/series", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data.get("id"), False, data.get("titleSlug")
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


async def _lookup_series_candidates(base: str, headers: dict, term: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{base}/api/v3/series/lookup",
                params={"term": term},
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.warning(f"Sonarr lookup failed for '{term}': {e}")
    return []


async def _search_tvdb_id(base: str, headers: dict, item: dict) -> str | None:
    """Cherche un TVDB ID via le lookup Sonarr (fallback quand absent du flux/API)."""
    for key, prefix in (("imdb_id", "imdb"), ("tmdb_id", "tmdb")):
        value = _norm_external_id(item.get(key))
        if not value:
            continue
        for candidate in await _lookup_series_candidates(base, headers, f"{prefix}:{value}"):
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
        for candidate in await _lookup_series_candidates(base, headers, term):
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
        for candidate in await _lookup_series_candidates(base, headers, terms[0]):
            if _candidate_matches_item(candidate, item) and candidate.get("tvdbId"):
                return str(candidate["tvdbId"])
    except Exception as e:
        logger.warning(f"Sonarr title fallback failed for '{title}': {e}")
    return None


async def get_all_series(sonarr_url: str, api_key: str) -> list[dict]:
    """Retourne la liste complète des séries connues de Sonarr (pour le scan de fallback)."""
    base = sonarr_url.rstrip("/")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{base}/api/v3/series", headers={"X-Api-Key": api_key})
        resp.raise_for_status()
        return resp.json()


async def lookup_series(
    sonarr_url: str,
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
    base = sonarr_url.rstrip("/")
    headers = {"X-Api-Key": api_key}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if arr_id:
                resp = await client.get(f"{base}/api/v3/series/{arr_id}", headers=headers)
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
                    resp = await client.get(f"{base}/api/v3/series", headers=headers)
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
    sonarr_url: str,
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
        sonarr_url,
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
    sonarr_url: str,
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
        sonarr_url,
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


async def series_exists(sonarr_url: str, api_key: str, arr_id: int) -> bool:
    """Vérifie par GET direct si une série existe encore dans Sonarr.

    Contrairement à `lookup_series`, ne catch PAS les erreurs réseau/HTTP : elles
    remontent à l'appelant pour ne jamais être confondues avec un 404 confirmé
    (Sonarr injoignable != série supprimée).
    """
    base = sonarr_url.rstrip("/")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{base}/api/v3/series/{arr_id}", headers={"X-Api-Key": api_key})
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True


async def delete_series(sonarr_url: str, api_key: str, arr_id: int, delete_files: bool = False) -> tuple[bool, str]:
    """Supprime une série de Sonarr (et ses fichiers si demandé).

    Un 404 est traité comme un succès (déjà absente). Toute autre erreur (réseau,
    timeout, 5xx) lève une exception — l'appelant ne doit jamais supprimer la
    demande locale correspondante si cet appel échoue.
    """
    base = sonarr_url.rstrip("/")
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.delete(
            f"{base}/api/v3/series/{arr_id}",
            params={"deleteFiles": "true" if delete_files else "false", "addImportListExclusion": "false"},
            headers={"X-Api-Key": api_key},
        )
        if resp.status_code == 404:
            return True, "Déjà absente de Sonarr"
        resp.raise_for_status()
        return True, "Supprimée de Sonarr"


async def search_series(sonarr_url: str, api_key: str, series_id: int) -> bool:
    """Lance une recherche de fichiers pour une série Sonarr (commande SeriesSearch).

    Utilisé par l'auto-search VFF : relance une recherche quand une série n'est
    disponible qu'en VO, dans l'espoir de trouver une version française.
    """
    base = sonarr_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{base}/api/v3/command",
                json={"name": "SeriesSearch", "seriesId": series_id},
                headers={"X-Api-Key": api_key},
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


async def get_releases(
    sonarr_url: str, api_key: str, series_id: int = None, episode_id: int = None
) -> list[dict]:
    """Recherche interactive Sonarr : releases scorées pour une série ou un épisode."""
    base = sonarr_url.rstrip("/")
    params = {}
    if episode_id:
        params["episodeId"] = episode_id
    elif series_id:
        params["seriesId"] = series_id
    else:
        return []
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.get(
                f"{base}/api/v3/release", params=params, headers={"X-Api-Key": api_key}
            )
            resp.raise_for_status()
            return [_normalize_release(r) for r in resp.json()]
    except Exception as e:
        logger.warning(f"Sonarr get_releases échec (series {series_id}, ep {episode_id}): {e}")
        return []


async def grab_release(sonarr_url: str, api_key: str, guid: str, indexer_id: int) -> tuple[bool, str]:
    """Grab d'une release choisie manuellement : Sonarr télécharge ET importe."""
    base = sonarr_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{base}/api/v3/release",
                json={"guid": guid, "indexerId": indexer_id},
                headers={"X-Api-Key": api_key},
            )
            resp.raise_for_status()
            return True, "Release envoyée à Sonarr"
    except Exception as e:
        logger.warning(f"Sonarr grab_release échec (guid {guid}): {e}")
        return False, str(e)


async def get_episodes(sonarr_url: str, api_key: str, series_id: int) -> list[dict]:
    """Retourne tous les épisodes d'une série Sonarr (saison, numéro, titre, présence fichier).

    Utilisé pour le détail VF par saison/épisode : Sonarr donne la liste attendue
    complète (y compris épisodes non encore téléchargés), Plex fournit la VF réelle.
    """
    base = sonarr_url.rstrip("/")
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{base}/api/v3/episode",
            params={"seriesId": series_id},
            headers={"X-Api-Key": api_key},
        )
        resp.raise_for_status()
        return resp.json()


def _normalize_queue_record(r: dict, title: str) -> dict:
    """Réduit un enregistrement de file d'attente Sonarr à un format compact pour l'UI."""
    size = r.get("size") or 0
    sizeleft = r.get("sizeleft") or 0
    progress = round((size - sizeleft) / size * 100, 1) if size else 0
    return {
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
    }


async def get_queue(sonarr_url: str, api_key: str) -> list[dict]:
    """File d'attente de téléchargement Sonarr (GET /queue), format compact."""
    base = sonarr_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{base}/api/v3/queue",
                params={"pageSize": 100, "includeSeries": "true", "includeEpisode": "true"},
                headers={"X-Api-Key": api_key},
            )
            resp.raise_for_status()
            records = resp.json().get("records", [])
    except Exception as e:
        logger.warning(f"Sonarr get_queue échec: {e}")
        return []
    out = []
    for r in records:
        series = (r.get("series") or {}).get("title")
        ep = r.get("episode") or {}
        sn, en = ep.get("seasonNumber"), ep.get("episodeNumber")
        if series and sn is not None and en is not None:
            title = f"{series} — S{sn:02d}E{en:02d}"
        else:
            title = series or r.get("title") or "?"
        out.append(_normalize_queue_record(r, title))
    return out


async def check_connection(sonarr_url: str, api_key: str) -> tuple[bool, str]:
    """Teste la connectivité avec l'instance Sonarr.

    Returns:
        (success, message)
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{sonarr_url.rstrip('/')}/api/v3/system/status",
                headers={"X-Api-Key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            return True, f"Sonarr v{data.get('version', '?')} connecté"
    except Exception as e:
        return False, str(e)


async def get_quality_profiles(sonarr_url: str, api_key: str) -> list[dict]:
    """Retourne les profils de qualité disponibles (pour le formulaire de config)."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{sonarr_url.rstrip('/')}/api/v3/qualityprofile",
            headers={"X-Api-Key": api_key},
        )
        resp.raise_for_status()
        return [{"id": p["id"], "name": p["name"]} for p in resp.json()]


async def get_root_folders(sonarr_url: str, api_key: str) -> list[dict]:
    """Retourne les dossiers racine configurés dans Sonarr (pour le formulaire de config)."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{sonarr_url.rstrip('/')}/api/v3/rootfolder",
            headers={"X-Api-Key": api_key},
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


async def get_tags(sonarr_url: str, api_key: str) -> list[dict]:
    """Retourne les tags configurés dans Sonarr (id + label)."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{sonarr_url.rstrip('/')}/api/v3/tag",
            headers={"X-Api-Key": api_key},
        )
        resp.raise_for_status()
        return [{"id": t["id"], "label": t["label"]} for t in resp.json()]


async def get_disk_space(sonarr_url: str, api_key: str) -> list[dict]:
    """Retourne l'espace disque des volumes connus de Sonarr.

    Returns:
        Liste de {path, free_bytes, total_bytes}.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{sonarr_url.rstrip('/')}/api/v3/diskspace",
            headers={"X-Api-Key": api_key},
        )
        resp.raise_for_status()
        return [{"path": d["path"], "free_bytes": d["freeSpace"], "total_bytes": d["totalSpace"]} for d in resp.json()]


async def get_calendar(sonarr_url: str, api_key: str, start: str, end: str) -> list[dict]:
    """Épisodes attendus/diffusés entre deux dates (GET /api/v3/calendar).

    `start`/`end` : dates ISO 8601. Chaque entrée inclut la série (includeSeries=true)
    pour le titre, les identifiants externes et l'affiche.
    """
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{sonarr_url.rstrip('/')}/api/v3/calendar",
                params={"start": start, "end": end, "includeSeries": "true"},
                headers={"X-Api-Key": api_key},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"Sonarr get_calendar failed: {e}")
        return []
