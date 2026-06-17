"""
Client pour l'API Prowlarr (indexeurs).

Fonctions principales :
- check_connection : vérifie la connectivité
- search           : recherche un média via Prowlarr
- get_indexers     : récupère les indexeurs configurés
"""

import logging
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)


async def check_connection(url: str, api_key: str) -> bool:
    """Vérifie la connectivité avec Prowlarr."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{url.rstrip('/')}/api/v1/system/status",
                headers={"X-Api-Key": api_key},
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
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{url.rstrip('/')}/api/v1/search",
                headers={"X-Api-Key": api_key},
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
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{url.rstrip('/')}/api/v1/indexer",
                headers={"X-Api-Key": api_key},
            )
            resp.raise_for_status()
            # On retourne la liste des indexeurs configurés (seulement ceux activés/configurés)
            return resp.json()
    except Exception as e:
        logger.error(f"Prowlarr get_indexers failed: {e}")
        return []
