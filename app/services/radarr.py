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

import httpx

logger = logging.getLogger(__name__)


async def add_movie(
    radarr_url: str,
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
        "minimumAvailability": minimum_availability,
        "monitored": True,
        "addOptions": {"searchForMovie": True},
        "tags": tag_ids or [],
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


async def resolve_tmdb_id(radarr_url: str, api_key: str, imdb_id: str) -> str | None:
    """Résout un TMDB ID à partir d'un IMDB ID via le lookup Radarr.

    Sert à normaliser sur TMDB les demandes RSS (qui n'apportent qu'un IMDB ID),
    afin qu'elles dédupliquent correctement avec les demandes Seer (clés sur TMDB).
    Radarr s'appuie sur la table de correspondance externe de TMDB : la résolution
    est donc cohérente avec ce que produit Seer pour le même film.
    """
    if not imdb_id:
        return None
    base = radarr_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{base}/api/v3/movie/lookup",
                params={"term": f"imdb:{imdb_id}"},
                headers={"X-Api-Key": api_key},
            )
            resp.raise_for_status()
            results = resp.json()
            if results and results[0].get("tmdbId"):
                return str(results[0]["tmdbId"])
    except Exception as e:
        logger.warning(f"Radarr imdb→tmdb resolution failed for '{imdb_id}': {e}")
    return None


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


async def get_all_movies(radarr_url: str, api_key: str) -> list[dict]:
    """Retourne la liste complète des films connus de Radarr (pour le scan de fallback)."""
    base = radarr_url.rstrip("/")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{base}/api/v3/movie", headers={"X-Api-Key": api_key})
        resp.raise_for_status()
        return resp.json()


async def lookup_movie(
    radarr_url: str,
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
    base = radarr_url.rstrip("/")
    headers = {"X-Api-Key": api_key}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if arr_id:
                resp = await client.get(f"{base}/api/v3/movie/{arr_id}", headers=headers)
                if resp.status_code == 200:
                    return resp.json()
            if tmdb_id or imdb_id:
                movies = movies_list
                if movies is None:
                    resp = await client.get(f"{base}/api/v3/movie", headers=headers)
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
    radarr_url: str,
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
        radarr_url, api_key, arr_id=arr_id, tmdb_id=tmdb_id, imdb_id=imdb_id, movies_list=movies_list
    )
    if not data:
        return False, None, None
    return data.get("hasFile", False), data.get("id"), data.get("titleSlug")


async def movie_exists(radarr_url: str, api_key: str, arr_id: int) -> bool:
    """Vérifie par GET direct si un film existe encore dans Radarr.

    Contrairement à `lookup_movie`, ne catch PAS les erreurs réseau/HTTP : elles
    remontent à l'appelant pour ne jamais être confondues avec un 404 confirmé
    (Radarr injoignable != film supprimé).
    """
    base = radarr_url.rstrip("/")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{base}/api/v3/movie/{arr_id}", headers={"X-Api-Key": api_key})
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True


async def delete_movie(radarr_url: str, api_key: str, arr_id: int, delete_files: bool = False) -> tuple[bool, str]:
    """Supprime un film de Radarr (et ses fichiers si demandé).

    Un 404 est traité comme un succès (déjà absent). Toute autre erreur (réseau,
    timeout, 5xx) lève une exception — l'appelant ne doit jamais supprimer la
    demande locale correspondante si cet appel échoue.
    """
    base = radarr_url.rstrip("/")
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.delete(
            f"{base}/api/v3/movie/{arr_id}",
            params={"deleteFiles": "true" if delete_files else "false", "addImportExclusion": "false"},
            headers={"X-Api-Key": api_key},
        )
        if resp.status_code == 404:
            return True, "Déjà absent de Radarr"
        resp.raise_for_status()
        return True, "Supprimé de Radarr"


async def search_movie(radarr_url: str, api_key: str, movie_id: int) -> bool:
    """Lance une recherche de fichier pour un film Radarr (commande MoviesSearch).

    Utilisé par l'auto-search VFF : relance une recherche quand un film n'est
    disponible qu'en VO, dans l'espoir de trouver une version française.
    """
    base = radarr_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{base}/api/v3/command",
                json={"name": "MoviesSearch", "movieIds": [movie_id]},
                headers={"X-Api-Key": api_key},
            )
            resp.raise_for_status()
            return True
    except Exception as e:
        logger.warning(f"Radarr MoviesSearch échec (movie {movie_id}): {e}")
        return False


def _normalize_release(r: dict) -> dict:
    """Réduit une release Radarr/Sonarr à un format compact pour l'UI.

    Conserve les infos clés pour la sélection (qualité, langues, score custom
    format) — les langues permettent de repérer les versions françaises (VF).
    """
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


async def get_releases(radarr_url: str, api_key: str, movie_id: int) -> list[dict]:
    """Recherche interactive Radarr : releases scorées pour un film (GET /release)."""
    base = radarr_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.get(
                f"{base}/api/v3/release",
                params={"movieId": movie_id},
                headers={"X-Api-Key": api_key},
            )
            resp.raise_for_status()
            return [_normalize_release(r) for r in resp.json()]
    except Exception as e:
        logger.warning(f"Radarr get_releases échec (movie {movie_id}): {e}")
        return []


async def grab_release(radarr_url: str, api_key: str, guid: str, indexer_id: int) -> tuple[bool, str]:
    """Grab d'une release choisie manuellement : Radarr télécharge ET importe.

    Returns (ok, message).
    """
    base = radarr_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{base}/api/v3/release",
                json={"guid": guid, "indexerId": indexer_id},
                headers={"X-Api-Key": api_key},
            )
            resp.raise_for_status()
            return True, "Release envoyée à Radarr"
    except Exception as e:
        logger.warning(f"Radarr grab_release échec (guid {guid}): {e}")
        return False, str(e)


def _normalize_queue_record(r: dict, title: str) -> dict:
    """Réduit un enregistrement de file d'attente *arr à un format compact pour l'UI."""
    size = r.get("size") or 0
    sizeleft = r.get("sizeleft") or 0
    progress = round((size - sizeleft) / size * 100, 1) if size else 0
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
    }


async def get_queue(radarr_url: str, api_key: str) -> list[dict]:
    """File d'attente de téléchargement Radarr (GET /queue), format compact."""
    base = radarr_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{base}/api/v3/queue",
                params={"pageSize": 100, "includeMovie": "true"},
                headers={"X-Api-Key": api_key},
            )
            resp.raise_for_status()
            records = resp.json().get("records", [])
    except Exception as e:
        logger.warning(f"Radarr get_queue échec: {e}")
        return []
    out = []
    for r in records:
        title = (r.get("movie") or {}).get("title") or r.get("title") or "?"
        out.append(_normalize_queue_record(r, title))
    return out


async def delete_queue_item(
    radarr_url: str, api_key: str, queue_id: int, *, blocklist: bool = False, search: bool = True
) -> tuple[bool, str]:
    """Supprime un item de la file d'attente Radarr, avec blocklist et relance de recherche optionnelles."""
    base = radarr_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.delete(
                f"{base}/api/v3/queue/{queue_id}",
                params={
                    "removeFromClient": "true",
                    "blocklist": "true" if blocklist else "false",
                    "skipRedownload": "false" if search else "true",
                },
                headers={"X-Api-Key": api_key},
            )
            if resp.status_code in (200, 204):
                return True, "Item supprimé de la file Radarr"
            resp.raise_for_status()
            return True, "Item supprimé de la file Radarr"
    except Exception as e:
        logger.warning(f"Radarr delete_queue_item échec (queue {queue_id}): {e}")
        return False, str(e)


async def get_queue_movie_ids(radarr_url: str, api_key: str) -> set[int]:
    """IDs des films ayant au moins un item actif dans la file de téléchargement Radarr.

    Utilisé pour distinguer une vraie anomalie Plex (fichier importé mais introuvable dans
    Plex) d'un film encore en cours de téléchargement (ex: upgrade de qualité en file alors
    qu'un fichier de moindre qualité est déjà présent sur disque).
    """
    base = radarr_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{base}/api/v3/queue",
                params={"pageSize": 200},
                headers={"X-Api-Key": api_key},
            )
            resp.raise_for_status()
            records = resp.json().get("records", [])
    except Exception as e:
        logger.warning(f"Radarr get_queue_movie_ids échec: {e}")
        return set()
    return {r["movieId"] for r in records if r.get("movieId")}


async def check_connection(radarr_url: str, api_key: str) -> tuple[bool, str]:
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


async def get_notifications(radarr_url: str, api_key: str) -> list[dict]:
    """Retourne les connecteurs de notification configurés dans Radarr (Settings → Connect)."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{radarr_url.rstrip('/')}/api/v3/notification",
            headers={"X-Api-Key": api_key},
        )
        resp.raise_for_status()
        return resp.json()


def find_webhook_notification(notifications: list[dict], webhook_path: str) -> dict | None:
    """Trouve, parmi les connecteurs Radarr, celui de type Webhook pointant vers notre endpoint."""
    for notif in notifications:
        if notif.get("implementation") != "Webhook":
            continue
        for field in notif.get("fields", []):
            if field.get("name") == "url" and webhook_path in str(field.get("value", "")):
                return notif
    return None


async def test_notification(radarr_url: str, api_key: str, notification: dict) -> tuple[bool, str]:
    """Déclenche depuis Radarr un test réel du connecteur Webhook (round-trip vers notre endpoint).

    Réutilise l'endpoint /api/v3/notification/test de Radarr, qui envoie une notification de
    test avec la configuration fournie sans la re-sauvegarder.
    """
    base = radarr_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{base}/api/v3/notification/test",
                json=notification,
                headers={"X-Api-Key": api_key},
            )
            if resp.status_code in (200, 204):
                return True, "Test envoyé et accepté par Radarr"
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


async def get_quality_profiles(radarr_url: str, api_key: str) -> list[dict]:
    """Retourne les profils de qualité disponibles (pour le formulaire de config)."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{radarr_url.rstrip('/')}/api/v3/qualityprofile",
            headers={"X-Api-Key": api_key},
        )
        resp.raise_for_status()
        return [{"id": p["id"], "name": p["name"]} for p in resp.json()]


async def get_root_folders(radarr_url: str, api_key: str) -> list[dict]:
    """Retourne les dossiers racine configurés dans Radarr (pour le formulaire de config)."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{radarr_url.rstrip('/')}/api/v3/rootfolder",
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


async def get_tags(radarr_url: str, api_key: str) -> list[dict]:
    """Retourne les tags configurés dans Radarr (id + label)."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{radarr_url.rstrip('/')}/api/v3/tag",
            headers={"X-Api-Key": api_key},
        )
        resp.raise_for_status()
        return [{"id": t["id"], "label": t["label"]} for t in resp.json()]


async def get_disk_space(radarr_url: str, api_key: str) -> list[dict]:
    """Retourne l'espace disque des volumes connus de Radarr.

    Returns:
        Liste de {path, free_bytes, total_bytes}.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{radarr_url.rstrip('/')}/api/v3/diskspace",
            headers={"X-Api-Key": api_key},
        )
        resp.raise_for_status()
        return [{"path": d["path"], "free_bytes": d["freeSpace"], "total_bytes": d["totalSpace"]} for d in resp.json()]


async def get_calendar(radarr_url: str, api_key: str, start: str, end: str) -> list[dict]:
    """Films dont une date de sortie tombe entre deux dates (GET /api/v3/calendar).

    `start`/`end` : dates ISO 8601. Chaque film inclut inCinemas/physicalRelease/
    digitalRelease — Radarr renvoie un film dès qu'UNE de ces dates est dans la plage.
    """
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{radarr_url.rstrip('/')}/api/v3/calendar",
                params={"start": start, "end": end},
                headers={"X-Api-Key": api_key},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"Radarr get_calendar failed: {e}")
        return []
