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
DISCOVER_BASE = "https://discover.provider.plex.tv"
CLIENT_IDENTIFIER = "plex-rss-monitor-sso-id"


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
        "X-Plex-Client-Identifier": CLIENT_IDENTIFIER,
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

    Utilise le endpoint discover.provider.plex.tv (le seul à exposer la liste
    de watchlist ; metadata.provider.plex.tv est réservé aux métadonnées d'un
    item précis et renvoie 404 sur /library/sections/watchlist/all) avec
    includeGuids=1 pour obtenir les identifiants TMDB/TVDB/IMDB nécessaires à
    Sonarr/Radarr.
    """
    headers = {
        "X-Plex-Token": token,
        "Accept": "application/json",
        "X-Plex-Client-Identifier": CLIENT_IDENTIFIER,
    }
    items = []
    try:
        resp = await client.get(
            f"{DISCOVER_BASE}/library/sections/watchlist/all",
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


async def check_connection(plex_url: str, plex_token: str, verify_ssl: bool = True) -> tuple[bool, str]:
    """Vérifie que le serveur Plex local (plex_url) est joignable et que le token est valide.

    Interroge directement plex_url (pas plex.tv) : valider uniquement le token contre
    plex.tv donnait un faux positif si plex_url était mal configuré/injoignable (ex:
    mauvaise IP) alors que le token restait valide par ailleurs — l'app ne peut
    pourtant rien faire (bibliothèques, VF...) sans accès réel au serveur local.

    Returns:
        (success, message)
    """
    if not plex_url:
        return False, "URL Plex non configurée"
    try:
        async with httpx.AsyncClient(timeout=10, verify=verify_ssl) as client:
            resp = await client.get(
                f"{plex_url.rstrip('/')}/identity",
                headers={"X-Plex-Token": plex_token, "Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        machine_id = (data.get("MediaContainer") or {}).get("machineIdentifier")
        return True, "Serveur Plex joignable" + (f" ({machine_id})" if machine_id else "")
    except Exception as e:
        return False, f"Connexion au serveur Plex impossible : {e}"


async def get_auth_pin(forward_url: str = "") -> dict:
    """Demande un code PIN d'authentification à Plex pour initier le SSO.

    Returns:
        Un dictionnaire contenant id, code, et l'URL d'authentification.
    """
    headers = {
        "Accept": "application/json",
        "X-Plex-Product": "Plexarr",
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
