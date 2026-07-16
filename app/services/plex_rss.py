"""
Parseur du flux RSS Plex watchlist.

Le flux RSS Plex admin contient les watchlists de tous les amis du compte.
Chaque entrée expose :
  <author>     → ID hexadécimal interne Plex (ex. "eead4af03aaec372"), PAS le nom d'utilisateur
  <category>   → "movie" ou "show"
  <guid>       → URI de type "imdb://tt0187078", "tvdb://79501" ou "tmdb://12345"
  <media:thumbnail> → URL de l'affiche
  <media:keywords>  → genres (séparés par des virgules)
"""

import logging
import re

import feedparser
import httpx

logger = logging.getLogger(__name__)


async def fetch_watchlist_rss(rss_url: str) -> list[dict]:
    """Récupère et parse le flux RSS Plex watchlist.

    Returns:
        Liste de dicts normalisés compatibles avec le modèle MediaRequest.
    """
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(rss_url)
            resp.raise_for_status()
            content = resp.text
    except httpx.HTTPError as e:
        logger.error(f"RSS fetch error: {e}")
        raise

    feed = feedparser.parse(content)
    items = []

    for entry in feed.entries:
        item = _parse_rss_entry(entry)
        if item:
            items.append(item)

    logger.info(f"RSS: parsed {len(items)} items from feed")
    return items


def _parse_rss_entry(entry) -> dict | None:
    """Convertit une entrée feedparser en dict normalisé.

    Returns None si l'entrée est invalide (titre vide).
    """
    title = entry.get("title", "").strip()
    if not title:
        return None

    # <author> contient l'ID hex Plex, pas le nom d'affichage
    plex_user_id = entry.get("author", "unknown").strip()

    import calendar
    from datetime import datetime, timezone

    # <pubDate> est bien la date d'ajout à la watchlist (vérifié empiriquement : les entrées
    # du flux sont triées par pubDate décroissant, sans corrélation avec l'année de sortie des
    # films/séries — ex. un film de 2019 en tête et un film de 1975 loin derrière). L'ancien
    # commentaire ici affirmait l'inverse (date de sortie) sans l'avoir vérifié.
    requested_at = None
    published_parsed = entry.get("published_parsed")
    if published_parsed:
        requested_at = datetime.fromtimestamp(calendar.timegm(published_parsed), tz=timezone.utc).replace(tzinfo=None)

    # <category> = "movie" ou "show" — valeur déjà normalisée par Plex
    categories = [t.get("term", "").lower() for t in entry.get("tags", [])]
    media_type = "show" if "show" in categories else "movie"

    # feedparser mappe <guid> sur entry.id
    guid_value = entry.get("id", "")
    tmdb_id, tvdb_id, imdb_id = _parse_guid(guid_value)

    # Plex inclut l'année dans le titre : "Gone in 60 Seconds (2000)"
    year = None
    year_match = re.search(r"\((\d{4})\)\s*$", title)
    if year_match:
        year = int(year_match.group(1))
        title = title[: year_match.start()].strip()

    # Affiche : d'abord <media:thumbnail>, sinon <media:content>
    poster_url = None
    media_thumbnail = entry.get("media_thumbnail", [])
    if media_thumbnail:
        poster_url = media_thumbnail[0].get("url")
    if not poster_url:
        media_content = entry.get("media_content", [])
        if media_content:
            poster_url = media_content[0].get("url")

    plex_link = entry.get("link", "")
    genres = entry.get("media_keywords", "")

    return {
        "title": title,
        "year": year,
        "media_type": media_type,
        "plex_user_id": plex_user_id,
        "plex_guid": plex_link,
        "tmdb_id": tmdb_id,
        "tvdb_id": tvdb_id,
        "imdb_id": imdb_id,
        "poster_url": poster_url,
        "genres": genres,
        "source": "rss",
        "requested_at": requested_at,
    }


def _parse_guid(guid: str) -> tuple[str | None, str | None, str | None]:
    """Extrait (tmdb_id, tvdb_id, imdb_id) depuis une URI de type 'imdb://tt0187078'."""
    tmdb_id = tvdb_id = imdb_id = None
    if guid.startswith("imdb://"):
        imdb_id = guid[len("imdb://") :]
    elif guid.startswith("tvdb://"):
        tvdb_id = guid[len("tvdb://") :]
    elif guid.startswith("tmdb://"):
        tmdb_id = guid[len("tmdb://") :]
    return tmdb_id, tvdb_id, imdb_id


async def discover_users_from_rss(rss_url: str) -> list[dict]:
    """Retourne la liste dédupliquée des plex_user_id présents dans le flux."""
    items = await fetch_watchlist_rss(rss_url)
    seen = {}
    for item in items:
        uid = item["plex_user_id"]
        if uid not in seen:
            seen[uid] = {"plex_user_id": uid, "item_count": 0}
        seen[uid]["item_count"] += 1
    return list(seen.values())


async def test_rss(rss_url: str) -> tuple[bool, str]:
    """Teste la connectivité et le parsing du flux RSS.

    Returns:
        (success, message)
    """
    try:
        items = await fetch_watchlist_rss(rss_url)
        user_ids = {i["plex_user_id"] for i in items}
        return True, f"{len(items)} éléments, {len(user_ids)} utilisateur(s) trouvés dans le flux RSS"
    except Exception as e:
        return False, str(e)
