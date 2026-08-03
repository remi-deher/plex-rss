"""Etat des scans VFF / synchronisation Plex, partage entre les process.

La progression vit dans des dicts de module (`vff_scan_state`, `plex_sync_state`), donc
dans la memoire d'un seul process. Or la production en fait tourner deux (voir
docker-compose.yml) : le conteneur web et le worker ARQ. Un scan declenche par le cron
ARQ tourne cote worker, et `GET /api/vff/scan-status`, servi par le conteneur web,
repondait « inactif » pendant toute sa duree.

Les dicts locaux restent la voie d'ecriture -- ils sont mutes depuis des dizaines
d'endroits, dont des threads `asyncio.to_thread` ou l'on ne peut pas `await`. Ce module
en publie un miroir dans Redis, ecrit par la tache de diffusion (`vff_progress`) du
process qui scanne, et lu par les autres.

Une section par cle Redis, et non un seul document : deux process peuvent avoir des
travaux differents en cours, et l'ecriture de l'un ne doit pas ecraser l'etat de l'autre.
"""

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_KEY_PREFIX = "plexarr:scan-state:v1"

# TTL court pendant l'execution, rafraichi a chaque cycle de la tache de diffusion : si le
# process qui scanne meurt, l'entree expire d'elle-meme et la lecture retombe sur l'etat
# local (au repos), au lieu de rester bloquee sur "running" indefiniment.
_RUNNING_TTL_SECONDS = 120
# Une fois termine, plus personne ne rafraichit : on conserve plus longtemps pour que le
# tableau de bord puisse afficher « termine il y a X ».
_FINISHED_TTL_SECONDS = 3600


def _key(section: str) -> str:
    return f"{_KEY_PREFIX}:{section}"


async def _client():
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    try:
        from redis.asyncio import Redis

        return Redis.from_url(url, encoding="utf-8", decode_responses=True)
    except Exception as exc:
        logger.warning("Etat de scan partage : Redis indisponible (%s)", exc)
        return None


async def write_section(section: str, state: dict[str, Any], *, running: bool) -> None:
    client = await _client()
    if client is None:
        return
    try:
        ttl = _RUNNING_TTL_SECONDS if running else _FINISHED_TTL_SECONDS
        await client.set(_key(section), json.dumps(state), ex=ttl)
    except Exception as exc:
        logger.warning("Etat de scan partage : ecriture de '%s' impossible (%s)", section, exc)
    finally:
        try:
            await client.aclose()
        except Exception:
            pass


async def read_section(section: str) -> dict[str, Any] | None:
    client = await _client()
    if client is None:
        return None
    try:
        raw = await client.get(_key(section))
    except Exception as exc:
        logger.warning("Etat de scan partage : lecture de '%s' impossible (%s)", section, exc)
        return None
    finally:
        try:
            await client.aclose()
        except Exception:
            pass
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


async def resolve(section: str, local: dict[str, Any]) -> dict[str, Any]:
    """Etat le plus fiable pour `section`, vu depuis ce process.

    Un scan en cours *ici* fait autorite : son dict local est mis a jour en continu, la
    copie Redis a au plus quelques secondes de retard. Sinon on prend la copie partagee
    (celle d'un scan tournant dans l'autre process), et a defaut le local.
    """
    if local.get("status") == "running":
        return dict(local)
    shared = await read_section(section)
    return shared if shared is not None else dict(local)


async def is_running(section: str, local: dict[str, Any]) -> bool:
    """Un scan est-il en cours, dans ce process ou dans un autre ?

    Sert de garde « deja en cours » : sans elle, le cron ARQ du worker et un declenchement
    manuel depuis l'interface web scannaient la meme bibliotheque en parallele.
    """
    if local.get("status") == "running":
        return True
    shared = await read_section(section)
    return bool(shared and shared.get("status") == "running")


async def clear_section(section: str) -> None:
    """Utilitaire de test : oublie la copie partagee."""
    client = await _client()
    if client is None:
        return
    try:
        await client.delete(_key(section))
    except Exception:
        pass
    finally:
        try:
            await client.aclose()
        except Exception:
            pass
