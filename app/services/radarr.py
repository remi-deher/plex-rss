"""
Client pour l'API Radarr v3 (films).

Fonctions principales :
- add_movie          : ajoute un film et lance la recherche
- is_movie_available : vérifie si le fichier film est présent (hasFile=true)
- lookup_movie       : recherche un film par arr_id, tmdb_id ou imdb_id
- test_connection    : vérifie la connectivité avec l'instance Radarr
- get_quality_profiles / get_root_folders : données de configuration UI
"""

import httpx
import logging

logger = logging.getLogger(__name__)


async def add_movie(
    radarr_url: str,
    api_key: str,
    quality_profile_id: int,
    root_folder: str,
    item: dict,
) -> tuple[int | None, bool, str | None]:
    """Ajoute un film à Radarr, ou retourne son ID s'il existe déjà.

    Returns:
        (radarr_id, already_existed, titleSlug)
        - already_existed=True signifie que le film était déjà dans Radarr.
    """
    headers = {"X-Api-Key": api_key}
    base = radarr_url.rstrip("/")

    tmdb_id = item.get("tmdb_id")
    if not tmdb_id:
        # TMDB ID absent : recherche via le lookup Radarr (inclut l'année pour la précision)
        tmdb_id = await _search_tmdb_id(base, headers, item["title"], item.get("year"))
    if not tmdb_id:
        logger.warning(f"Cannot find TMDB ID for '{item['title']}'")
        return None, False, None

    # Vérification d'existence avant ajout
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            existing = await client.get(f"{base}/api/v3/movie", headers=headers)
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
        "monitored": True,
        "addOptions": {"searchForMovie": True},
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{base}/api/v3/movie", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data.get("id"), False, data.get("titleSlug")
    except httpx.HTTPError as e:
        logger.error(f"Radarr error adding '{item['title']}': {e}")
        raise


async def _search_tmdb_id(base: str, headers: dict, title: str, year: int | None) -> str | None:
    """Cherche un TMDB ID via le lookup Radarr.

    L'année est ajoutée au terme de recherche pour lever les ambiguïtés
    entre remakes et homonymes.
    """
    term = f"{title} {year}" if year else title
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{base}/api/v3/movie/lookup",
                params={"term": term},
                headers=headers,
            )
            resp.raise_for_status()
            results = resp.json()
            if results:
                return str(results[0].get("tmdbId"))
    except Exception as e:
        logger.warning(f"Radarr lookup failed for '{title}': {e}")
    return None


async def lookup_movie(
    radarr_url: str,
    api_key: str,
    arr_id: int = None,
    tmdb_id: str = None,
    imdb_id: str = None,
) -> dict | None:
    """Recherche un film par arr_id (GET direct), tmdb_id ou imdb_id (scan de la liste).

    L'ordre de priorité est : arr_id → tmdb_id → imdb_id.
    Le scan de la liste est O(n) ; arr_id est O(1).

    Returns:
        Dictionnaire Radarr brut ou None si introuvable.
    """
    base = radarr_url.rstrip("/")
    headers = {"X-Api-Key": api_key}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if arr_id:
                resp = await client.get(f"{base}/api/v3/movie/{arr_id}", headers=headers)
                if resp.status_code == 200:
                    return resp.json()
            if tmdb_id or imdb_id:
                resp = await client.get(f"{base}/api/v3/movie", headers=headers)
                resp.raise_for_status()
                for m in resp.json():
                    if tmdb_id and str(m.get("tmdbId")) == str(tmdb_id):
                        return m
                    if imdb_id and m.get("imdbId") == imdb_id:
                        return m
    except Exception as e:
        logger.warning(f"Radarr lookup failed: {e}")
    return None


async def is_movie_available(
    radarr_url: str,
    api_key: str,
    arr_id: int = None,
    tmdb_id: str = None,
    imdb_id: str = None,
) -> tuple[bool, int | None, str | None]:
    """Vérifie si le fichier film est présent dans Radarr (hasFile=true).

    Returns:
        (is_available, arr_id, title_slug)
    """
    data = await lookup_movie(radarr_url, api_key, arr_id=arr_id, tmdb_id=tmdb_id, imdb_id=imdb_id)
    if not data:
        return False, None, None
    return data.get("hasFile", False), data.get("id"), data.get("titleSlug")


async def test_connection(radarr_url: str, api_key: str) -> tuple[bool, str]:
    """Teste la connectivité avec l'instance Radarr.

    Returns:
        (success, message)
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{radarr_url.rstrip('/')}/api/v3/system/status",
                headers={"X-Api-Key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            return True, f"Radarr v{data.get('version', '?')} connecté"
    except Exception as e:
        return False, str(e)


async def get_quality_profiles(radarr_url: str, api_key: str) -> list[dict]:
    """Retourne les profils de qualité disponibles (pour le formulaire de config)."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{radarr_url.rstrip('/')}/api/v3/qualityprofile",
            headers={"X-Api-Key": api_key},
        )
        resp.raise_for_status()
        return [{"id": p["id"], "name": p["name"]} for p in resp.json()]


async def get_root_folders(radarr_url: str, api_key: str) -> list[str]:
    """Retourne les dossiers racine configurés dans Radarr (pour le formulaire de config)."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{radarr_url.rstrip('/')}/api/v3/rootfolder",
            headers={"X-Api-Key": api_key},
        )
        resp.raise_for_status()
        return [f["path"] for f in resp.json()]
