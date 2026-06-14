"""
Client pour l'API Plex officielle (plex.tv).

Permet de récupérer les watchlists de tous les amis du compte admin,
en utilisant leur authToken individuel (fourni par /api/v2/friends).
C'est la source de données la plus riche (synopsis, GUIDs complets)
mais elle nécessite un token Plex valide.
"""

import logging
import urllib.parse
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

PLEX_TV_BASE = "https://plex.tv"
METADATA_BASE = "https://metadata.provider.plex.tv"


async def get_friends_watchlist(plex_url: str, plex_token: str) -> list[dict]:
    """Récupère les watchlists de tous les amis + du compte admin.

    La liste des amis est obtenue via /api/v2/friends, puis chaque ami
    est interrogé avec son propre authToken pour accéder à sa watchlist privée.
    Le compte admin (plex_token) est toujours inclus.

    Returns:
        Liste de dicts normalisés compatibles avec MediaRequest.
    """
    headers = {
        "X-Plex-Token": plex_token,
        "Accept": "application/json",
    }
    items = []

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{PLEX_TV_BASE}/api/v2/friends", headers=headers)
            resp.raise_for_status()
            friends = resp.json()

            for friend in friends:
                username = friend.get("username") or friend.get("title", "unknown")
                friend_token = friend.get("authToken")
                if not friend_token:
                    continue
                friend_items = await _get_user_watchlist(client, friend_token, username)
                items.extend(friend_items)

            # Inclure aussi la watchlist du compte admin lui-même
            admin_items = await _get_user_watchlist(client, plex_token, "admin")
            items.extend(admin_items)

    except httpx.HTTPError as e:
        logger.error(f"Plex API error fetching friends watchlist: {e}")
        raise

    return items


async def _get_user_watchlist(client: httpx.AsyncClient, token: str, username: str) -> list[dict]:
    """Récupère la watchlist d'un utilisateur via son token personnel.

    Utilise le endpoint metadata.provider.plex.tv (CDN Plex) avec includeGuids=1
    pour obtenir les identifiants TMDB/TVDB/IMDB nécessaires à Sonarr/Radarr.
    """
    headers = {
        "X-Plex-Token": token,
        "Accept": "application/json",
    }
    items = []
    try:
        resp = await client.get(
            f"{METADATA_BASE}/library/sections/watchlist/all",
            headers=headers,
            params={"includeGuids": 1},
        )
        resp.raise_for_status()
        data = resp.json()
        media_container = data.get("MediaContainer", {})
        for item in media_container.get("Metadata", []):
            items.append(_parse_api_item(item, username))
    except httpx.HTTPError as e:
        logger.warning(f"Could not fetch watchlist for user {username}: {e}")
    return items


def _parse_api_item(item: dict, username: str) -> dict:
    """Convertit un objet Metadata Plex API en dict normalisé.

    Les GUIDs sont sous la forme [{"id": "tmdb://12345"}, {"id": "imdb://tt..."}].
    On les transforme en dict {scheme: value} pour un accès direct.
    """
    guids = {g["id"].split("://")[0]: g["id"].split("://")[1] for g in item.get("Guid", []) if "://" in g.get("id", "")}
    return {
        "title": item.get("title", ""),
        "year": item.get("year"),
        "media_type": "show" if item.get("type") == "show" else "movie",
        "plex_guid": item.get("guid", ""),
        "tmdb_id": guids.get("tmdb"),
        "tvdb_id": guids.get("tvdb"),
        "imdb_id": guids.get("imdb"),
        # Les thumbs Plex sont des chemins relatifs — on les préfixe avec le CDN TMDB
        "poster_url": (
            f"https://image.tmdb.org/t/p/w300{item.get('thumb', '')}"
            if item.get("thumb", "").startswith("/")
            else item.get("thumb")
        ),
        "overview": item.get("summary", ""),
        "plex_user": username,
        "source": "api",
    }


async def test_connection(plex_url: str, plex_token: str) -> tuple[bool, str]:
    """Vérifie la validité du token Plex en interrogeant le profil utilisateur.

    Returns:
        (success, message)
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{PLEX_TV_BASE}/api/v2/user",
                headers={"X-Plex-Token": plex_token, "Accept": "application/json"},
            )
            resp.raise_for_status()
            user = resp.json()
            return True, f"Connecté en tant que {user.get('username', 'inconnu')}"
    except Exception as e:
        return False, str(e)


async def get_auth_pin(forward_url: str = "") -> dict:
    """Demande un code PIN d'authentification à Plex pour initier le SSO.

    Returns:
        Un dictionnaire contenant id, code, et l'URL d'authentification.
    """
    headers = {
        "Accept": "application/json",
        "X-Plex-Product": "Plex RSS Monitor",
        "X-Plex-Client-Identifier": "plex-rss-monitor-sso-id",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{PLEX_TV_BASE}/api/v2/pins", headers=headers)
        resp.raise_for_status()
        data = resp.json()
        pin_id = data.get("id")
        code = data.get("code")

        encoded_forward = urllib.parse.quote(forward_url, safe="")
        auth_url = (
            f"https://app.plex.tv/auth/#!?clientID=plex-rss-monitor-sso-id"
            f"&code={code}"
            f"&context%5Bdevice%5D%5Bproduct%5D=Plex%20RSS%20Monitor"
            f"&forwardUrl={encoded_forward}"
        )
        return {"id": pin_id, "code": code, "auth_url": auth_url}


async def check_auth_pin(pin_id: int) -> Optional[str]:
    """Vérifie si le code PIN a été validé par l'utilisateur sur Plex.

    Returns:
        Le Plex Token s'il est disponible, None sinon.
    """
    headers = {"Accept": "application/json", "X-Plex-Client-Identifier": "plex-rss-monitor-sso-id"}
    async with httpx.AsyncClient(timeout=10) as client:
        # Utilisation de l'API v2 officielle de Plex pour vérifier les PINs
        resp = await client.get(f"{PLEX_TV_BASE}/api/v2/pins/{pin_id}", headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data.get("authToken")
