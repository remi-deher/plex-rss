"""
Agrégateur de watchlists Plex.

Abstrait le choix entre les deux sources de données :
- API Plex (plex_api.py) : données riches, nécessite un token admin
- Flux RSS  (plex_rss.py) : données légères, accessible avec une URL publique

La priorité et le fallback sont configurables dans Settings.
"""

import logging
from sqlalchemy.orm import Session
from .plex_api import get_friends_watchlist
from .plex_rss import fetch_watchlist_rss
from ..models import Settings

logger = logging.getLogger(__name__)


async def fetch_watchlist(settings: Settings) -> list[dict]:
    """Retourne les éléments de watchlist en respectant la stratégie (priorité + fallback).

    - Si la source primaire échoue et que le fallback est activé, tente la source secondaire.
    - Si les deux échouent, retourne une liste vide (pas de crash du scheduler).
    """
    priority = settings.watchlist_source_priority or "api"
    fallback_enabled = settings.watchlist_fallback_enabled

    primary_fn, fallback_fn = _get_sources(priority, settings)

    try:
        items = await primary_fn()
        logger.info(f"Watchlist fetched via {priority} ({len(items)} items)")
        return items
    except Exception as e:
        logger.warning(f"Primary source ({priority}) failed: {e}")

    if fallback_enabled and fallback_fn:
        fallback_name = "rss" if priority == "api" else "api"
        try:
            items = await fallback_fn()
            logger.info(f"Watchlist fetched via fallback {fallback_name} ({len(items)} items)")
            return items
        except Exception as e:
            logger.error(f"Fallback source ({fallback_name}) also failed: {e}")

    return []


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
