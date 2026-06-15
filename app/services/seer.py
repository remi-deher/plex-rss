"""
Client pour l'API Seer (Overseerr / Jellyseerr).

Mode de fonctionnement :
Quand seer_enabled=True dans les paramètres, les demandes sont envoyées à
Seer au lieu de Sonarr/Radarr directement. Seer gère lui-même le
routage vers Sonarr/Radarr selon sa configuration interne.

API Seer utilisée :
- POST /api/v1/request  : créer une demande (film ou série)
- GET  /api/v1/request/{id} : vérifier le statut d'une demande
- GET  /api/v1/auth/me  : tester la connectivité
- GET  /api/v1/search   : rechercher un tmdb_id par titre

Statuts Seer :
- 1 = PENDING
- 2 = APPROVED
- 3 = DECLINED
- 4 = FAILED (ne pas confondre avec notre status failed)
- 5 = PROCESSING (disponible côté media)

Media statuts (media.status) :
- 1 = UNKNOWN
- 2 = PENDING
- 3 = PROCESSING
- 4 = PARTIALLY_AVAILABLE
- 5 = AVAILABLE
"""

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

MEDIA_STATUS_AVAILABLE = 5
MEDIA_STATUS_PARTIALLY = 4


def _headers(api_key: str) -> dict:
    return {"X-Api-Key": api_key, "Content-Type": "application/json"}


async def request_media(
    seer_url: str,
    api_key: str,
    item: dict,
) -> tuple[int | None, bool, str | None]:
    """Envoie une demande à Seer (film ou série).

    Seer utilise TMDB pour les deux types de médias.
    Pour les séries, si seul tvdb_id est disponible, une recherche préalable est faite.

    Returns:
        (seer_request_id, already_existed, None)
        - already_existed=True si la demande existait déjà (statut non-PENDING)
    """
    base = seer_url.rstrip("/")
    headers = _headers(api_key)
    media_type = "movie" if item["media_type"] == "movie" else "tv"

    tmdb_id = await _resolve_tmdb_id(base, headers, item)
    if not tmdb_id:
        logger.warning(f"Seer: impossible de résoudre TMDB ID pour '{item['title']}'")
        raise ValueError(f"TMDB ID introuvable pour '{item['title']}'")

    payload = {
        "mediaType": media_type,
        "mediaId": int(tmdb_id),
    }
    if media_type == "tv":
        payload["seasons"] = "all"

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(f"{base}/api/v1/request", json=payload, headers=headers)
            if resp.status_code == 409:
                logger.info(f"Seer: '{item['title']}' déjà demandé")
                return None, True, None
            resp.raise_for_status()
            data = resp.json()
            req_id = data.get("id")
            logger.info(f"Seer: demande créée #{req_id} pour '{item['title']}'")
            return req_id, False, None
    except httpx.HTTPStatusError as e:
        logger.error(f"Seer erreur HTTP pour '{item['title']}': {e.response.status_code} {e.response.text[:200]}")
        raise
    except Exception as e:
        logger.error(f"Seer erreur pour '{item['title']}': {e}")
        raise


async def is_request_available(
    seer_url: str,
    api_key: str,
    seer_request_id: int,
    item: dict | None = None,
) -> tuple[bool, int | None, str | None]:
    """Vérifie si une demande Seer est disponible (media.status == 5).

    Returns:
        (is_available, seer_request_id, None)
    """
    base = seer_url.rstrip("/")
    headers = _headers(api_key)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{base}/api/v1/request/{seer_request_id}", headers=headers)
            if resp.status_code == 404:
                return False, None, None
            resp.raise_for_status()
            data = resp.json()
            media = data.get("media", {})
            media_status = media.get("status", 1)
            available = media_status in (MEDIA_STATUS_AVAILABLE, MEDIA_STATUS_PARTIALLY)
            return available, seer_request_id, None
    except Exception as e:
        logger.warning(f"Seer status check échoué pour request#{seer_request_id}: {e}")
        return False, None, None


async def _resolve_tmdb_id(base: str, headers: dict, item: dict) -> str | None:
    """Résout un TMDB ID à partir des données de l'item.

    Ordre de priorité : tmdb_id direct → recherche par titre+année.
    """
    if item.get("tmdb_id"):
        return str(item["tmdb_id"])

    term = item["title"]
    media_type = "movie" if item["media_type"] == "movie" else "tv"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{base}/api/v1/search",
                params={"query": term, "page": 1, "language": "fr"},
                headers=headers,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            for r in results:
                if r.get("mediaType") == media_type:
                    return str(r.get("id"))
    except Exception as e:
        logger.warning(f"Seer search échoué pour '{term}': {e}")
    return None


async def get_users(seer_url: str, api_key: str) -> dict[str, dict]:
    """Retourne {email_lowercase: {...}} pour tous les utilisateurs Seer.

    Champs retournés par utilisateur :
      id, request_count, display_name, plex_username, plex_id, user_type
    - user_type : 1=local, 2=plex, 3=jellyfin
    - plex_id   : ID numérique Plex (entier), disponible si user_type=2
    - plex_username : nom d'utilisateur Plex
    """
    base = seer_url.rstrip("/")
    headers = _headers(api_key)
    result: dict[str, dict] = {}
    skip = 0
    take = 100

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            while True:
                resp = await client.get(
                    f"{base}/api/v1/user",
                    params={"take": take, "skip": skip},
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                users = data.get("results", [])
                for u in users:
                    email = (u.get("email") or "").lower().strip()
                    if email:
                        result[email] = {
                            "id": u.get("id"),
                            "request_count": u.get("requestCount", 0),
                            "display_name": u.get("displayName") or u.get("username") or "",
                            "plex_username": u.get("plexUsername") or "",
                            "plex_id": u.get("plexId"),
                            "user_type": u.get("userType", 1),
                        }
                if len(users) < take:
                    break
                skip += take
    except Exception as e:
        logger.warning(f"Seer: impossible de récupérer les utilisateurs: {e}")

    return result


async def get_user_requests(seer_url: str, api_key: str, seer_user_id: int) -> list[dict]:
    """Retourne toutes les demandes d'un utilisateur Seer (paginé).

    Chaque entrée contient : seer_request_id, media_type, tmdb_id, tvdb_id, imdb_id,
    title, overview, poster_url, status (notre RequestStatus).

    L'endpoint user/requests retourne un objet media minimaliste (sans titre).
    Une seconde vague de requêtes parallèles récupère les détails via /movie/{id}
    ou /tv/{id} pour chaque tmdbId unique.
    """
    base = seer_url.rstrip("/")
    headers = _headers(api_key)
    raw: list[dict] = []
    skip = 0
    take = 100

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # 1. Pagination : collecte des demandes brutes
            while True:
                resp = await client.get(
                    f"{base}/api/v1/user/{seer_user_id}/requests",
                    params={"take": take, "skip": skip},
                    headers=headers,
                )
                if resp.status_code == 404:
                    break
                resp.raise_for_status()
                items = resp.json().get("results", [])
                raw.extend(items)
                if len(items) < take:
                    break
                skip += take

            # 2. Récupération parallèle des détails pour chaque (type, tmdbId) unique
            unique: set[tuple[str, int]] = set()
            for req in raw:
                media = req.get("media") or {}
                tmdb_id = media.get("tmdbId")
                media_type = "movie" if media.get("mediaType") == "movie" else "tv"
                if tmdb_id:
                    unique.add((media_type, int(tmdb_id)))

            async def _fetch_details(media_type: str, tmdb_id: int) -> tuple[tuple, dict]:
                try:
                    r = await client.get(f"{base}/api/v1/{media_type}/{tmdb_id}", headers=headers)
                    if r.status_code == 200:
                        d = r.json()
                        return (media_type, tmdb_id), {
                            "title": (
                                d.get("title") or d.get("name")
                                or d.get("originalTitle") or d.get("originalName")
                            ),
                            "poster_url": (
                                f"https://image.tmdb.org/t/p/w200{d['posterPath']}"
                                if d.get("posterPath") else None
                            ),
                            "overview": d.get("overview"),
                        }
                except Exception:
                    pass
                return (media_type, tmdb_id), {}

            detail_results = await asyncio.gather(*[_fetch_details(mt, tid) for mt, tid in unique])
            details: dict[tuple, dict] = dict(detail_results)

    except Exception as e:
        logger.warning(f"Seer: impossible de récupérer les demandes de l'utilisateur {seer_user_id}: {e}")
        return []

    # 3. Construction de la liste finale
    results = []
    for req in raw:
        media = req.get("media") or {}
        media_type_raw = media.get("mediaType", "")
        media_type = "movie" if media_type_raw == "movie" else "show"
        seer_type = "movie" if media_type == "movie" else "tv"
        tmdb_id = media.get("tmdbId")
        key = (seer_type, int(tmdb_id)) if tmdb_id else None
        info = details.get(key, {}) if key else {}

        media_status = media.get("status", 1)
        status = "available" if media_status in (4, 5) else "sent_to_arr"

        title = info.get("title") or f"[Seer #{req.get('id')}]"
        if not req.get("createdAt"):
            logger.warning(f"Seer request #{req.get('id')} ({title}): createdAt absent — champs = {list(req.keys())}")
        results.append({
            "seer_request_id": req.get("id"),
            "media_type": media_type,
            "tmdb_id": str(tmdb_id) if tmdb_id else None,
            "tvdb_id": str(media.get("tvdbId")) if media.get("tvdbId") else None,
            "imdb_id": media.get("imdbId"),
            "title": title,
            "overview": info.get("overview"),
            "status": status,
            "poster_url": info.get("poster_url"),
            "requested_at": req.get("createdAt"),
            "updated_at": req.get("updatedAt"),
        })

    return results


async def check_connection(seer_url: str, api_key: str) -> tuple[bool, str]:
    """Teste la connectivité avec l'instance Seer.

    Returns:
        (success, message)
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{seer_url.rstrip('/')}/api/v1/auth/me",
                headers=_headers(api_key),
            )
            resp.raise_for_status()
            data = resp.json()
            name = data.get("displayName") or data.get("email") or "?"
            return True, f"Seer connecté en tant que {name}"
    except Exception as e:
        return False, str(e)
