"""Verrou distribué Redis (SET NX EX) pour les jobs planifiés déclenchables depuis
plusieurs process (conteneur API + worker ARQ + endpoints HTTP manuels).

Un `asyncio.Lock()` local ne protège que dans un seul process Python. Plusieurs jobs
de ce projet (poll_watchlists, check_arr_statuses...) sont déclenchés à la fois par
le cron ARQ (conteneur worker) et par des endpoints HTTP (conteneur API) : sans verrou
partagé, deux process peuvent traiter le même cycle en même temps (doublons, notifs
en double). Voir l'incident documenté sur poll_watchlists (deux MediaRequest créées
à 369 ms d'écart) qui a motivé ce verrou.
"""

import logging
import os
import uuid

logger = logging.getLogger(__name__)

_DEFAULT_TTL = 300  # secondes ; filet de sécurité si le holder crash sans relâcher


async def acquire_distributed_lock(key: str, ttl: int = _DEFAULT_TTL) -> str | None:
    """Tente d'acquérir le verrou Redis `key`.

    Returns:
        Un token si acquis (à repasser à `release_distributed_lock`), None si un
        autre process le détient déjà. Renvoie un token sentinelle sans toucher
        Redis si `REDIS_URL` n'est pas configuré (mode legacy mono-process).
    """
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return "no-redis"
    try:
        from redis.asyncio import Redis

        token = uuid.uuid4().hex
        redis = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
        try:
            acquired = await redis.set(key, token, nx=True, ex=ttl)
            return token if acquired else None
        finally:
            await redis.aclose()
    except Exception as e:
        # Redis injoignable : on ne bloque pas le job pour autant (mieux vaut un risque
        # de doublon résiduel qu'un job qui ne tourne plus jamais), mais on le signale.
        logger.warning(f"Verrou Redis '{key}' indisponible, repli sur le verrou local seul: {e}")
        return "redis-error"


async def release_distributed_lock(key: str, token: str | None) -> None:
    if not token or token in ("no-redis", "redis-error"):
        return
    try:
        from redis.asyncio import Redis

        redis = Redis.from_url(os.environ["REDIS_URL"], encoding="utf-8", decode_responses=True)
        try:
            # Ne supprime que si on détient toujours le verrou (évite de relâcher celui
            # d'un autre holder après expiration de notre propre TTL).
            script = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
            await redis.eval(script, 1, key, token)
        finally:
            await redis.aclose()
    except Exception as e:
        logger.warning(f"Impossible de relâcher le verrou Redis '{key}': {e}")
