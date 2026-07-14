"""Client HTTP partagé pour les API Arr (Sonarr, Radarr, Prowlarr) et Seer.

Encapsule la gestion des timeouts, de la clé API, et la journalisation des erreurs.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ArrClient:
    """Client HTTP pour interagir avec les API de type Arr."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 15):
        self.base = base_url.rstrip("/")
        self.headers = {"X-Api-Key": api_key}
        self.timeout = timeout

    async def get(self, path: str, params: dict | None = None, **kwargs) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.get(
                f"{self.base}{path}", headers=self.headers, params=params, **kwargs
            )

    async def post(self, path: str, json: Any = None, data: Any = None, **kwargs) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.post(
                f"{self.base}{path}", headers=self.headers, json=json, data=data, **kwargs
            )

    async def put(self, path: str, json: Any = None, **kwargs) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.put(f"{self.base}{path}", headers=self.headers, json=json, **kwargs)

    async def delete(self, path: str, params: dict | None = None, **kwargs) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.delete(
                f"{self.base}{path}", headers=self.headers, params=params, **kwargs
            )
