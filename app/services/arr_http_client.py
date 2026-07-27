"""Client HTTP partagé pour les API Arr (Sonarr, Radarr, Prowlarr) et Seer.

Encapsule la gestion des timeouts, de la clé API, et la journalisation des erreurs.
"""

import logging
from asyncio import Lock
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_clients: dict[tuple[str, int], tuple[httpx.AsyncClient, httpx.AsyncClient]] = {}
_clients_lock = Lock()


async def _shared_client(base_url: str, timeout: int) -> httpx.AsyncClient:
    """Return one connection pool per origin/timeout pair."""
    key = (base_url, timeout)
    entry = _clients.get(key)
    if entry is not None:
        return entry[1]
    async with _clients_lock:
        entry = _clients.get(key)
        if entry is None:
            owner = httpx.AsyncClient(
                base_url=base_url,
                timeout=timeout,
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            )
            client = await owner.__aenter__()
            # Unit tests replace the constructor with AsyncMock instances. Keeping one
            # across independently patched tests would leak configured side effects.
            if owner.__class__.__module__.startswith("unittest.mock"):
                return client
            _clients[key] = (owner, client)
        else:
            client = entry[1]
        return client


async def close_arr_clients() -> None:
    """Close all pools at application shutdown (also useful for isolated tests)."""
    async with _clients_lock:
        clients = list(_clients.values())
        _clients.clear()
    for owner, _client in clients:
        await owner.__aexit__(None, None, None)


class ArrClient:
    """Client HTTP pour interagir avec les API de type Arr."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 15, *, raise_for_status: bool = False):
        self.base = base_url.rstrip("/")
        self.headers = {"X-Api-Key": api_key}
        self.timeout = timeout
        self.raise_for_status = raise_for_status

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        client = await _shared_client(self.base, self.timeout)
        request = getattr(client, method.lower())
        response = await request(path, headers=self.headers, **kwargs)
        if self.raise_for_status:
            response.raise_for_status()
        return response

    async def get(self, path: str, params: dict | None = None, **kwargs) -> httpx.Response:
        return await self._request("GET", path, params=params, **kwargs)

    async def post(self, path: str, json: Any = None, data: Any = None, **kwargs) -> httpx.Response:
        return await self._request("POST", path, json=json, data=data, **kwargs)

    async def put(self, path: str, json: Any = None, **kwargs) -> httpx.Response:
        return await self._request("PUT", path, json=json, **kwargs)

    async def delete(self, path: str, params: dict | None = None, **kwargs) -> httpx.Response:
        return await self._request("DELETE", path, params=params, **kwargs)
