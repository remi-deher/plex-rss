"""Diffusion SSE de la progression des scans VFF et de la synchronisation Plex.

Le tableau de bord interrogeait `/api/vff/scan-status`, `/api/vff/sync-status` et
`/api/vff/counts` toutes les 5 secondes, soit 36 requetes par minute en permanence, y
compris quand rien ne tourne. La progression est desormais poussee sur le flux SSE
existant.

Plutot que d'instrumenter la trentaine de points ou les dicts d'etat sont mutes -- dont
certains tournent dans un thread `asyncio.to_thread`, ou l'on ne peut pas `await` --, une
tache de fond unique observe ces dicts et emet un evenement quand ils changent. Elle
s'arrete d'elle-meme des que plus rien n'est en cours : aucun cout au repos.
"""

import asyncio
import logging
from typing import Any

from ..realtime import publish
from . import scan_state

logger = logging.getLogger(__name__)

# Cadence d'observation : assez fine pour une barre de progression fluide, et sans commune
# mesure avec le cout d'une requete HTTP puisqu'il s'agit d'une comparaison de dicts.
_POLL_INTERVAL_SECONDS = 2.0

_watcher: asyncio.Task | None = None


def _snapshot() -> dict[str, Any]:
    # Import differe : plex_sync et vff_scanner importent tous deux des modules qui
    # remontent jusqu'ici, un import au chargement creerait un cycle.
    from .plex_sync import plex_sync_state
    from .vff_scanner import vff_scan_state

    return {"scan": dict(vff_scan_state), "sync": dict(plex_sync_state)}


def _is_running(snapshot: dict[str, Any]) -> bool:
    return any(section.get("status") == "running" for section in snapshot.values())


async def _library_counts() -> dict[str, int] | None:
    """Compteurs VF/VO/non verifies — recalcules seulement en fin de scan, ce sont les
    seuls moments ou ils bougent reellement."""
    from sqlalchemy import func
    from sqlalchemy.future import select

    from ..database import AsyncSessionLocal
    from ..models import LibraryItem

    try:
        async with AsyncSessionLocal() as db:

            async def count_where(condition) -> int:
                return int(
                    (
                        await db.execute(
                            select(func.count()).select_from(LibraryItem).filter(condition)
                        )
                    ).scalar()
                    or 0
                )

            return {
                "vo_pending": await count_where(LibraryItem.has_vf.is_(False)),
                "vf_available": await count_where(LibraryItem.has_vf.is_(True)),
                "unchecked": await count_where(LibraryItem.has_vf.is_(None)),
            }
    except Exception as exc:
        logger.warning("VFF : calcul des compteurs impossible : %s", exc)
        return None


async def _mirror_to_shared_state(snapshot: dict[str, Any], touched: set[str]) -> None:
    """Publie dans Redis les sections dont ce process s'occupe, pour que l'autre les voie.

    Seules les sections vues « running » depuis le demarrage de cette tache sont ecrites :
    le worker, dont le dict `sync` local est reste aux valeurs par defaut, effacerait sinon
    l'etat d'une synchronisation menee par le conteneur web.
    """
    for name, section in snapshot.items():
        if section.get("status") == "running":
            touched.add(name)
        if name in touched:
            await scan_state.write_section(name, section, running=section.get("status") == "running")


async def _watch() -> None:
    global _watcher
    previous: dict[str, Any] | None = None
    touched: set[str] = set()
    try:
        while True:
            snapshot = _snapshot()
            # A chaque cycle, meme sans changement : l'ecriture rafraichit le TTL de la
            # copie partagee, dont l'expiration est justement le filet de securite si ce
            # process meurt en plein scan.
            await _mirror_to_shared_state(snapshot, touched)
            if snapshot != previous:
                payload = dict(snapshot)
                # `previous is None` = tout premier tour, donc le demarrage : les compteurs
                # n'ont pas encore bouge, inutile de payer trois COUNT.
                if previous is not None and not _is_running(snapshot):
                    counts = await _library_counts()
                    if counts:
                        payload["counts"] = counts
                await publish("vff.updated", payload, admin_only=True)
                previous = snapshot
            if not _is_running(snapshot):
                return
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("VFF : diffusion de la progression interrompue : %s", exc)
    finally:
        _watcher = None


def notify_vff_progress() -> None:
    """Demarre la diffusion si elle ne tourne pas deja.

    A appeler *apres* le passage du statut a "running" : la tache s'arrete des qu'elle
    observe un etat au repos, et sortirait immediatement si elle demarrait trop tot.
    """
    global _watcher
    if _watcher is not None and not _watcher.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Appel hors boucle asyncio (script, test synchrone) : rien a diffuser.
        return
    _watcher = loop.create_task(_watch())
