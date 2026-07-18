"""Small async cache facade with an in-memory fallback.

Redis is optional for local development.  A transient Redis outage must never
make an API request fail, so callers keep the same behaviour with a process
local cache until the connection is available again.
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# Taches de rafraichissement en arriere-plan (voir Cache.get_or_refresh) : conservees
# ici pour eviter que asyncio ne les libere prematurement (une Task sans reference
# gardee peut etre garbage-collectee avant sa fin, avec un warning "Task was destroyed
# but it is pending").
_background_tasks: set[asyncio.Task] = set()
_refreshing_keys: set[str] = set()


def _spawn_background(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


class Cache:
    def __init__(self) -> None:
        self._memory: dict[str, tuple[str, float]] = {}
        self._redis = None
        self._attempted_connection = False

    async def _client(self):
        if self._attempted_connection:
            return self._redis
        self._attempted_connection = True
        url = os.getenv("REDIS_URL")
        if not url:
            return None
        try:
            from redis.asyncio import Redis

            client = Redis.from_url(url, encoding="utf-8", decode_responses=True)
            await client.ping()
            self._redis = client
            logger.info("Redis cache connected")
        except Exception as exc:
            logger.warning("Redis unavailable; using process-local cache: %s", exc)
        return self._redis

    async def get_json(self, key: str) -> dict[str, Any] | None:
        raw = None
        client = await self._client()
        if client:
            try:
                raw = await client.get(key)
            except Exception as exc:
                logger.warning("Redis read failed: %s", exc)
        if raw is None:
            memory_item = self._memory.get(key)
            if memory_item and memory_item[1] > time.monotonic():
                raw = memory_item[0]
            elif memory_item:
                self._memory.pop(key, None)
        if not raw:
            return None
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None

    async def set_json(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        raw = json.dumps(value)
        self._memory[key] = (raw, time.monotonic() + ttl_seconds)
        client = await self._client()
        if client:
            try:
                await client.set(key, raw, ex=ttl_seconds)
            except Exception as exc:
                logger.warning("Redis write failed: %s", exc)

    async def get_or_refresh(
        self,
        key: str,
        soft_ttl_seconds: int,
        hard_ttl_seconds: int,
        compute_sync: Callable[[], Awaitable[Any]],
        compute_background: Callable[[], Awaitable[Any]] | None = None,
    ) -> Any:
        """Sert immediatement la derniere valeur connue (meme perimee, jusqu'a
        hard_ttl_seconds), et lance un recalcul en arriere-plan des qu'elle depasse
        soft_ttl_seconds -- l'appelant ne paie le cout du recalcul en direct qu'au
        tout premier appel (rien encore en cache). Pensee pour les pages qui doivent
        s'afficher "a peu pres fraiches" sans jamais bloquer sur un appel Sonarr/
        Radarr/Plex en direct (voir arr_orphans.py, calendar_api.py, metrics_api.py).

        `compute_background`, si fourni, doit etre autonome (ouvrir sa propre session
        DB, etc.) : la reponse HTTP d'origine est deja partie quand cette tache tourne,
        les ressources liees a la requete (ex: session DB injectee) peuvent deja etre
        fermees. A defaut, `compute_sync` est reutilise (correct uniquement si l'appelant
        n'utilise aucune ressource liee a la requete).
        """
        entry = await self.get_json(key)
        now = time.time()
        if entry is not None and "cached_at" in entry:
            age = now - entry["cached_at"]
            if age >= soft_ttl_seconds and key not in _refreshing_keys:
                _refreshing_keys.add(key)
                _spawn_background(self._refresh_and_release(key, hard_ttl_seconds, compute_background or compute_sync))
            return entry["value"]

        value = await compute_sync()
        await self.set_json(key, {"value": value, "cached_at": now}, ttl_seconds=hard_ttl_seconds)
        return value

    async def _refresh_and_release(self, key: str, hard_ttl_seconds: int, compute: Callable[[], Awaitable[Any]]) -> None:
        try:
            value = await compute()
            await self.set_json(key, {"value": value, "cached_at": time.time()}, ttl_seconds=hard_ttl_seconds)
        except Exception as exc:
            logger.warning("Rafraichissement en arriere-plan echoue pour %s: %s", key, exc)
        finally:
            _refreshing_keys.discard(key)

    async def delete(self, key: str) -> None:
        self._memory.pop(key, None)
        client = await self._client()
        if client:
            try:
                await client.delete(key)
            except Exception as exc:
                logger.warning("Redis delete failed: %s", exc)

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()


cache = Cache()
