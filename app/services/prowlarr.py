"""
Client pour l'API Prowlarr (indexeurs).

Fonctions principales :
- check_connection    : vérifie la connectivité
- search              : recherche un média via Prowlarr
- get_indexers        : récupère les indexeurs configurés
- get_download_clients: récupère les clients de téléchargement configurés dans Prowlarr
- grab                : envoie une release au client de téléchargement configuré dans Prowlarr
"""

import logging
from typing import List, Optional

import httpx
from .arr_http_client import ArrClient

logger = logging.getLogger(__name__)


async def check_connection(url: str, api_key: str) -> bool:
    """Vérifie la connectivité avec Prowlarr."""
    try:
        client = ArrClient(url, api_key, timeout=10)
        resp = await client.get(
            "/api/v1/system/status",
        )
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"Prowlarr connection check failed: {e}")
        return False


async def search(
    url: str,
    api_key: str,
    query: str,
    media_type: str,
    indexer_ids: Optional[List[int]] = None,
) -> list[dict]:
    """Recherche sur Prowlarr via POST /api/v1/search."""
    categories = [5000] if media_type == "movie" else [5070]
    payload = {
        "query": query,
        "categories": categories,
    }
    if indexer_ids is not None:
        payload["indexerIds"] = indexer_ids

    try:
        client = ArrClient(url, api_key, timeout=30)
        resp = await client.post(
            "/api/v1/search",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Prowlarr search failed for '{query}': {e}")
        return []


async def get_indexers(url: str, api_key: str) -> list[dict]:
    """Récupère la liste des indexeurs configurés dans Prowlarr."""
    try:
        client = ArrClient(url, api_key, timeout=15)
        resp = await client.get(
            "/api/v1/indexer",
        )
        resp.raise_for_status()
        # On retourne la liste des indexeurs configurés (seulement ceux activés/configurés)
        return resp.json()
    except Exception as e:
        logger.error(f"Prowlarr get_indexers failed: {e}")
        return []


async def get_download_clients(url: str, api_key: str) -> list[dict]:
    """Récupère les clients de téléchargement configurés dans Prowlarr (GET /api/v1/downloadClient).

    Si Prowlarr a lui-même un client actif, on peut lui déléguer le grab (voir `grab`)
    plutôt que d'exiger un client de téléchargement configuré séparément dans l'app.
    """
    try:
        client = ArrClient(url, api_key, timeout=15)
        resp = await client.get(
            "/api/v1/downloadClient",
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Prowlarr get_download_clients failed: {e}")
        return []


async def grab(url: str, api_key: str, guid: str, indexer_id: int) -> tuple[bool, str]:
    """Envoie une release au client de téléchargement configuré dans Prowlarr.

    Réutilise l'endpoint POST /api/v1/search : un payload {guid, indexerId} (sans
    `query`) déclenche un grab au lieu d'une recherche — Prowlarr route la release
    vers le client de téléchargement actif correspondant au protocole (torrent/usenet).
    """
    try:
        client = ArrClient(url, api_key, timeout=30)
        resp = await client.post(
            "/api/v1/search",
            json={"guid": guid, "indexerId": indexer_id},
        )
        resp.raise_for_status()
        return True, "Envoyé au client de téléchargement configuré dans Prowlarr"
    except Exception as e:
        logger.error(f"Prowlarr grab failed (guid={guid}, indexerId={indexer_id}): {e}")
        return False, str(e)
