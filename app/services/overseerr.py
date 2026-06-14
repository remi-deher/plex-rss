"""
Client pour l'API Overseerr / Jellyseerr.

Mode de fonctionnement :
Quand overseerr_enabled=True dans les paramètres, les demandes sont envoyées à
Overseerr au lieu de Sonarr/Radarr directement. Overseerr gère lui-même le
routage vers Sonarr/Radarr selon sa configuration interne.

API Overseerr utilisée :
- POST /api/v1/request  : créer une demande (film ou série)
- GET  /api/v1/request/{id} : vérifier le statut d'une demande
- GET  /api/v1/auth/me  : tester la connectivité
- GET  /api/v1/search   : rechercher un tmdb_id par titre

Statuts Overseerr :
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

import logging

import httpx

logger = logging.getLogger(__name__)

MEDIA_STATUS_AVAILABLE = 5
MEDIA_STATUS_PARTIALLY = 4


def _headers(api_key: str) -> dict:
    return {"X-Api-Key": api_key, "Content-Type": "application/json"}


async def request_media(
    overseerr_url: str,
    api_key: str,
    item: dict,
) -> tuple[int | None, bool, str | None]:
    """Envoie une demande à Overseerr (film ou série).

    Overseerr utilise TMDB pour les deux types de médias.
    Pour les séries, si seul tvdb_id est disponible, une recherche préalable est faite.

    Returns:
        (overseerr_request_id, already_existed, None)
        - already_existed=True si la demande existait déjà (statut non-PENDING)
    """
    base = overseerr_url.rstrip("/")
    headers = _headers(api_key)
    media_type = "movie" if item["media_type"] == "movie" else "tv"

    tmdb_id = await _resolve_tmdb_id(base, headers, item)
    if not tmdb_id:
        logger.warning(f"Overseerr: impossible de résoudre TMDB ID pour '{item['title']}'")
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
                # Conflit = déjà demandé
                logger.info(f"Overseerr: '{item['title']}' déjà demandé")
                return None, True, None
            resp.raise_for_status()
            data = resp.json()
            req_id = data.get("id")
            logger.info(f"Overseerr: demande créée #{req_id} pour '{item['title']}'")
            return req_id, False, None
    except httpx.HTTPStatusError as e:
        logger.error(f"Overseerr erreur HTTP pour '{item['title']}': {e.response.status_code} {e.response.text[:200]}")
        raise
    except Exception as e:
        logger.error(f"Overseerr erreur pour '{item['title']}': {e}")
        raise


async def is_request_available(
    overseerr_url: str,
    api_key: str,
    overseerr_request_id: int,
    item: dict | None = None,
) -> tuple[bool, int | None, str | None]:
    """Vérifie si une demande Overseerr est disponible (media.status == 5).

    Returns:
        (is_available, overseerr_request_id, None)
    """
    base = overseerr_url.rstrip("/")
    headers = _headers(api_key)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{base}/api/v1/request/{overseerr_request_id}", headers=headers)
            if resp.status_code == 404:
                return False, None, None
            resp.raise_for_status()
            data = resp.json()
            media = data.get("media", {})
            media_status = media.get("status", 1)
            available = media_status in (MEDIA_STATUS_AVAILABLE, MEDIA_STATUS_PARTIALLY)
            return available, overseerr_request_id, None
    except Exception as e:
        logger.warning(f"Overseerr status check échoué pour request#{overseerr_request_id}: {e}")
        return False, None, None


async def _resolve_tmdb_id(base: str, headers: dict, item: dict) -> str | None:
    """Résout un TMDB ID à partir des données de l'item.

    Ordre de priorité : tmdb_id direct → recherche par titre+année.
    """
    if item.get("tmdb_id"):
        return str(item["tmdb_id"])

    # Recherche via l'API Overseerr
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
        logger.warning(f"Overseerr search échoué pour '{term}': {e}")
    return None


async def check_connection(overseerr_url: str, api_key: str) -> tuple[bool, str]:
    """Teste la connectivité avec l'instance Overseerr.

    Returns:
        (success, message)
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{overseerr_url.rstrip('/')}/api/v1/auth/me",
                headers=_headers(api_key),
            )
            resp.raise_for_status()
            data = resp.json()
            name = data.get("displayName") or data.get("email") or "?"
            return True, f"Overseerr connecté en tant que {name}"
    except Exception as e:
        return False, str(e)
