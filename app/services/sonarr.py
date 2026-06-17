"""
Client pour l'API Sonarr v3 (séries TV).

Fonctions principales :
- add_series          : ajoute une série et lance la recherche de fichiers
- is_series_available : vérifie si au moins un fichier épisode existe (episodeFileCount > 0)
- lookup_series       : recherche une série par arr_id ou tvdb_id
- test_connection     : vérifie la connectivité avec l'instance Sonarr
- get_quality_profiles / get_root_folders : données de configuration UI
"""

import logging

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
        # TVDB ID absent du flux RSS (rare) : recherche via le lookup Sonarr
        tvdb_id = await _search_tvdb_id(base, headers, item["title"])
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


async def _search_tvdb_id(base: str, headers: dict, title: str) -> str | None:
    """Cherche un TVDB ID via le lookup Sonarr (fallback quand absent du flux RSS)."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{base}/api/v3/series/lookup",
                params={"term": title},
                headers=headers,
            )
            resp.raise_for_status()
            results = resp.json()
            if results:
                return str(results[0].get("tvdbId"))
    except Exception as e:
        logger.warning(f"Sonarr lookup failed for '{title}': {e}")
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
                    return resp.json()
            if tvdb_id:
                series = series_list
                if series is None:
                    resp = await client.get(f"{base}/api/v3/series", headers=headers)
                    resp.raise_for_status()
                    series = resp.json()
                for s in series:
                    if str(s.get("tvdbId")) == str(tvdb_id):
                        return s
    except Exception as e:
        logger.warning(f"Sonarr lookup failed: {e}")
    return None


async def is_series_available(
    sonarr_url: str,
    api_key: str,
    arr_id: int = None,
    tvdb_id: str = None,
    series_list: list[dict] | None = None,
) -> tuple[bool, int | None, str | None]:
    """Vérifie si une série a au moins un fichier épisode dans Sonarr.

    Returns:
        (is_available, arr_id, title_slug)
    """
    data = await lookup_series(sonarr_url, api_key, arr_id=arr_id, tvdb_id=tvdb_id, series_list=series_list)
    if not data:
        return False, None, None
    stats = data.get("statistics", {})
    available = stats.get("episodeFileCount", 0) > 0
    return available, data.get("id"), data.get("titleSlug")


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


async def get_root_folders(sonarr_url: str, api_key: str) -> list[str]:
    """Retourne les dossiers racine configurés dans Sonarr (pour le formulaire de config)."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{sonarr_url.rstrip('/')}/api/v3/rootfolder",
            headers={"X-Api-Key": api_key},
        )
        resp.raise_for_status()
        return [f["path"] for f in resp.json()]


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
