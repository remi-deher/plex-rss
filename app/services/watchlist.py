"""
Agrégateur de watchlists Plex.

Abstrait le choix entre les deux sources de données :
- API Plex (plex_api.py) : données riches, nécessite un token admin
- Flux RSS  (plex_rss.py) : données légères, accessible avec une URL publique

La priorité et le fallback sont configurables dans Settings.
"""

import logging

from sqlalchemy.orm import Session

from ..models import Settings
from .plex_api import get_friends_watchlist
from .plex_rss import fetch_watchlist_rss

logger = logging.getLogger(__name__)


async def fetch_watchlist(settings: Settings) -> list[dict]:
    """Retourne les éléments de watchlist en fusionnant la source primaire et secondaire.

    L'API Plex (`/api/v2/friends`) et le flux RSS peuvent chacun "réussir" (pas
    d'exception) tout en omettant silencieusement certains amis — l'API n'expose un
    authToken que pour certaines relations (cf. get_friends_watchlist), le RSS peut
    lui aussi ne pas couvrir un compte selon sa config. Un simple fallback-sur-échec
    ne rattrape donc pas ce cas : les deux sources sont toujours fusionnées (dédupliquées)
    quand le fallback est activé, pas seulement quand la source primaire lève une exception.
    """
    priority = settings.watchlist_source_priority or "api"
    fallback_enabled = settings.watchlist_fallback_enabled

    primary_fn, secondary_fn = _get_sources(priority, settings)
    secondary_name = "rss" if priority == "api" else "api"

    primary_items: list[dict] = []
    primary_ok = True
    try:
        primary_items = await primary_fn()
        logger.info(f"Watchlist fetched via {priority} ({len(primary_items)} items)")
    except Exception as e:
        primary_ok = False
        logger.warning(f"Primary source ({priority}) failed: {e}")

    if not fallback_enabled or not secondary_fn:
        return primary_items

    try:
        secondary_items = await secondary_fn()
    except Exception as e:
        if not primary_ok:
            logger.error(f"Both sources failed ({priority} and {secondary_name}): {e}")
        else:
            logger.warning(f"Secondary source ({secondary_name}) failed: {e}")
        return primary_items

    seen = {_item_key(item) for item in primary_items}
    merged = list(primary_items)
    added = 0
    for item in secondary_items:
        key = _item_key(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
        added += 1
    if added:
        logger.info(f"Watchlist merged with {secondary_name}: +{added} item(s) not seen via {priority}")
    elif not primary_ok:
        logger.info(f"Watchlist fetched via fallback {secondary_name} ({len(secondary_items)} items)")
    return merged


def _item_key(item: dict) -> tuple:
    return (
        item.get("plex_user_id") or item.get("plex_user") or "unknown",
        item.get("media_type"),
        item.get("tmdb_id") or "",
        item.get("tvdb_id") or "",
        item.get("imdb_id") or "",
        item.get("plex_guid") or "",
        (item.get("title") or "").lower(),
        item.get("year") or "",
    )


def _get_sources(priority: str, settings: Settings):
    """Retourne (primary_fn, fallback_fn) selon la priorité configurée."""

    async def api_source():
        if not settings.plex_token:
            raise ValueError("Plex token non configuré")
        return await get_friends_watchlist(settings.plex_url or "", settings.plex_token)

    async def rss_source():
        if not settings.plex_rss_url:
            raise ValueError("URL RSS Plex non configurée")
        return await fetch_watchlist_rss(settings.plex_rss_url)

    if priority == "api":
        return api_source, rss_source
    else:
        return rss_source, api_source
