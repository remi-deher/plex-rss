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
CLIENT_IDENTIFIER = "1c8e19c3-8824-4f2b-8a8b-3e5f2ea129a6"


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
                friend_items = await _get_user_watchlist(client, friend_token, username, username)
                items.extend(friend_items)

            # Inclure aussi la watchlist du compte admin lui-même
            admin_username = await _get_account_username(client, headers)
            admin_items = await _get_user_watchlist(client, plex_token, admin_username, admin_username)
            items.extend(admin_items)

    except httpx.HTTPError as e:
        logger.error(f"Plex API error fetching friends watchlist: {e}")
        raise

    return items


async def get_admin_watchlist(plex_url: str, plex_token: str) -> list[dict]:
    """Récupère uniquement la watchlist du compte propriétaire du token Plex."""
    headers = {
        "X-Plex-Token": plex_token,
        "Accept": "application/json",
        "X-Plex-Client-Identifier": CLIENT_IDENTIFIER,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        username = await _get_account_username(client, headers)
        return await _get_user_watchlist(client, plex_token, username, username)


async def _get_account_username(client: httpx.AsyncClient, headers: dict) -> str:
    """Retourne le username Plex du compte courant, compatible avec plexUsername Seer."""
    try:
        resp = await client.get(f"{PLEX_TV_BASE}/api/v2/user", headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data.get("username") or data.get("title") or data.get("email") or "admin"
    except httpx.HTTPError as e:
        logger.warning(f"Could not resolve Plex account username, using admin fallback: {e}")
        return "admin"


async def get_plex_account(token: str) -> Optional[dict]:
    """Résout le compte Plex propriétaire d'un token (login SSO par utilisateur).

    Returns un dict {uuid, username, email, thumb} ou None si le token est invalide.
    L'uuid est l'identifiant stable du compte (indépendant du username, qui peut changer).
    """
    logger.info("SSO: get_plex_account called with token %s...", token[:6] + "..." if token else "None")
    headers = {
        "X-Plex-Token": token,
        "Accept": "application/json",
        "X-Plex-Client-Identifier": CLIENT_IDENTIFIER,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{PLEX_TV_BASE}/api/v2/user", headers=headers)
            logger.info("SSO: Plex user API status: %s", resp.status_code)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        logger.warning(f"SSO: Could not resolve Plex account from token: {e}")
        return None
    username = data.get("username") or data.get("title") or data.get("email")
    if not username:
        logger.warning("SSO: No username found in Plex user data")
        return None
    logger.info("SSO: Plex account resolved for username: %s, uuid: %s", username, data.get("uuid"))
    return {
        "uuid": data.get("uuid") or str(data.get("id") or ""),
        "username": username,
        "email": data.get("email"),
        "thumb": data.get("thumb"),
    }


async def check_auth_pin(pin_id: int) -> Optional[str]:
    """Vérifie si le code PIN a été validé par l'utilisateur sur Plex.

    Returns:
        Le Plex Token s'il est disponible, None sinon.
    """
    logger.info("SSO: checking PIN status for pin_id: %s", pin_id)
    headers = {"Accept": "application/json", "X-Plex-Client-Identifier": CLIENT_IDENTIFIER}
    async with httpx.AsyncClient(timeout=10) as client:
        # Utilisation de l'API v2 officielle de Plex pour vérifier les PINs
        resp = await client.get(f"{PLEX_TV_BASE}/api/v2/pins/{pin_id}", headers=headers)
        logger.info("SSO: Plex pins API status: %s", resp.status_code)
        resp.raise_for_status()
        data = resp.json()
        token = data.get("authToken")
        logger.info("SSO: PIN status check result - token found: %s", bool(token))
        return token


async def _get_user_watchlist(
    client: httpx.AsyncClient, token: str, username: str, user_id: str | None = None
) -> list[dict]:
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
            items.append(_parse_api_item(item, username, user_id or username))
    except httpx.HTTPError as e:
        logger.warning(f"Could not fetch watchlist for user {username}: {e}")
    return items


def _parse_api_item(item: dict, username: str, user_id: str) -> dict:
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
        "plex_user_id": user_id,
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
        "X-Plex-Client-Identifier": CLIENT_IDENTIFIER,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{PLEX_TV_BASE}/api/v2/pins?strong=true", headers=headers)
        resp.raise_for_status()
        data = resp.json()
        pin_id = data.get("id")
        code = data.get("code")

        forward = "https://app.plex.tv"
        encoded_forward = urllib.parse.quote(forward, safe="")
        auth_url = (
            f"https://app.plex.tv/auth#?clientID={CLIENT_IDENTIFIER}"
            f"&code={code}"
            f"&context%5Bdevice%5D%5Bproduct%5D=Plexarr"
            f"&forwardUrl={encoded_forward}"
        )
        return {"id": pin_id, "code": code, "auth_url": auth_url}


async def has_server_access(
    admin_token: str, user_username: str, user_email: str | None, user_uuid: str | None
) -> bool:
    """Vérifie si l'utilisateur a accès au serveur (est le propriétaire, un ami, ou membre du Home)."""
    headers = {
        "X-Plex-Token": admin_token,
        "Accept": "application/json",
        "X-Plex-Client-Identifier": CLIENT_IDENTIFIER,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        # 1. Vérifier si c'est le propriétaire
        try:
            resp = await client.get(f"{PLEX_TV_BASE}/api/v2/user", headers=headers)
            if resp.status_code == 200:
                owner = resp.json()
                owner_uuid = owner.get("uuid") or str(owner.get("id") or "")
                owner_username = owner.get("username") or owner.get("title")
                owner_email = owner.get("email")
                if (
                    (user_uuid and owner_uuid == user_uuid)
                    or (user_username and owner_username.lower() == user_username.lower())
                    or (user_email and owner_email and owner_email.lower() == user_email.lower())
                ):
                    return True
        except Exception as e:
            logger.warning(f"Error checking Plex owner account: {e}")

        # 2. Vérifier les amis (friends)
        try:
            resp = await client.get(f"{PLEX_TV_BASE}/api/v2/friends", headers=headers)
            if resp.status_code == 200:
                friends = resp.json()
                for friend in friends:
                    friend_uuid = friend.get("uuid") or str(friend.get("id") or "")
                    friend_username = friend.get("username") or friend.get("title")
                    friend_email = friend.get("email")
                    if (
                        (user_uuid and friend_uuid == user_uuid)
                        or (user_username and friend_username and friend_username.lower() == user_username.lower())
                        or (user_email and friend_email and friend_email.lower() == user_email.lower())
                    ):
                        return True
        except Exception as e:
            logger.warning(f"Error checking Plex friends: {e}")

        # 3. Vérifier les membres du Plex Home (home/users)
        try:
            resp = await client.get(f"{PLEX_TV_BASE}/api/v2/home/users", headers=headers)
            if resp.status_code == 200:
                home_users = resp.json()
                for member in home_users:
                    member_uuid = member.get("uuid") or str(member.get("id") or "")
                    member_username = member.get("username") or member.get("title")
                    member_email = member.get("email")
                    if (
                        (user_uuid and member_uuid == user_uuid)
                        or (user_username and member_username and member_username.lower() == user_username.lower())
                        or (user_email and member_email and member_email.lower() == user_email.lower())
                    ):
                        return True
        except Exception as e:
            logger.warning(f"Error checking Plex Home users: {e}")

    return False
