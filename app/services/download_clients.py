import logging
from typing import Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


async def qbittorrent_login(
    client: httpx.AsyncClient, url: str, username: Optional[str], password: Optional[str]
) -> Optional[str]:
    """Se connecte à qBittorrent et retourne le cookie SID."""
    login_url = f"{url.rstrip('/')}/api/v2/auth/login"
    data = {"username": username or "", "password": password or ""}
    try:
        r = await client.post(login_url, data=data, timeout=10)
        r.raise_for_status()
        if "Ok" in r.text and "SID" in r.cookies:
            return r.cookies["SID"]
        logger.warning(f"qBittorrent login failed: {r.text}")
        return None
    except Exception as e:
        logger.error(f"qBittorrent login error: {e}")
        return None


async def check_qbittorrent(url: str, username: Optional[str], password: Optional[str]) -> Tuple[bool, str]:
    """Vérifie la connexion avec qBittorrent."""
    async with httpx.AsyncClient() as client:
        sid = await qbittorrent_login(client, url, username, password)
        if not sid:
            return False, "Échec d'authentification ou connexion impossible"

        # Test de l'API
        version_url = f"{url.rstrip('/')}/api/v2/app/version"
        try:
            r = await client.get(version_url, cookies={"SID": sid}, timeout=10)
            r.raise_for_status()
            return True, f"Connecté à qBittorrent v{r.text}"
        except Exception as e:
            return False, f"Erreur API: {str(e)}"


async def add_qbittorrent_torrent(
    url: str,
    username: Optional[str],
    password: Optional[str],
    torrent_url_or_magnet: str,
    category: Optional[str] = None,
    tags: Optional[str] = None,
) -> Tuple[bool, str]:
    """Ajoute un torrent à qBittorrent."""
    async with httpx.AsyncClient() as client:
        sid = await qbittorrent_login(client, url, username, password)
        if not sid:
            return False, "Échec de connexion/authentification"

        add_url = f"{url.rstrip('/')}/api/v2/torrents/add"
        data = {
            "urls": torrent_url_or_magnet,
        }
        if category:
            data["category"] = category
        if tags:
            data["tags"] = tags

        try:
            r = await client.post(add_url, data=data, cookies={"SID": sid}, timeout=15)
            r.raise_for_status()
            if "Ok" in r.text or r.status_code == 200:
                return True, "Torrent ajouté avec succès à qBittorrent"
            return False, f"Réponse qBittorrent: {r.text}"
        except Exception as e:
            return False, f"Erreur d'ajout qBittorrent: {str(e)}"


async def transmission_rpc(
    client: httpx.AsyncClient,
    url: str,
    username: Optional[str],
    password: Optional[str],
    method: str,
    arguments: Optional[dict] = None,
) -> dict:
    """Effectue un appel RPC vers Transmission en gérant le token X-Transmission-Session-Id."""
    rpc_url = f"{url.rstrip('/')}/transmission/rpc"
    headers = {}
    auth = None
    if username and password:
        auth = (username, password)

    # Premier essai
    try:
        r = await client.post(
            rpc_url, json={"method": method, "arguments": arguments or {}}, auth=auth, headers=headers, timeout=10
        )
        if r.status_code == 409:
            # Récupération du session ID et deuxième essai
            session_id = r.headers.get("X-Transmission-Session-Id")
            if session_id:
                headers["X-Transmission-Session-Id"] = session_id
                r = await client.post(
                    rpc_url,
                    json={"method": method, "arguments": arguments or {}},
                    auth=auth,
                    headers=headers,
                    timeout=10,
                )

        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Transmission RPC error: {e}")
        raise e


async def check_transmission(url: str, username: Optional[str], password: Optional[str]) -> Tuple[bool, str]:
    """Vérifie la connexion avec Transmission."""
    async with httpx.AsyncClient() as client:
        try:
            res = await transmission_rpc(client, url, username, password, "session-get")
            if res.get("result") == "success":
                version = res.get("arguments", {}).get("version", "?")
                return True, f"Connecté à Transmission v{version}"
            return False, f"Erreur de réponse RPC: {res.get('result')}"
        except Exception as e:
            return False, f"Erreur de connexion RPC: {str(e)}"


async def add_transmission_torrent(
    url: str, username: Optional[str], password: Optional[str], torrent_url_or_magnet: str, tags: Optional[str] = None
) -> Tuple[bool, str]:
    """Ajoute un torrent à Transmission."""
    async with httpx.AsyncClient() as client:
        try:
            args = {"filename": torrent_url_or_magnet}
            if tags:
                # Transmission utilise des labels (tableau de chaînes)
                args["labels"] = [t.strip() for t in tags.split(",") if t.strip()]

            res = await transmission_rpc(client, url, username, password, "torrent-add", args)
            if res.get("result") == "success":
                return True, "Torrent ajouté avec succès à Transmission"
            return False, f"Erreur de réponse RPC: {res.get('result')}"
        except Exception as e:
            return False, f"Erreur d'ajout RPC: {str(e)}"


async def check_client_connection(
    client_type: str, url: str, username: Optional[str], password: Optional[str]
) -> Tuple[bool, str]:
    """Point d'entrée générique pour tester la connexion."""
    if client_type == "qbittorrent":
        return await check_qbittorrent(url, username, password)
    elif client_type == "transmission":
        return await check_transmission(url, username, password)
    return False, f"Type de client inconnu: {client_type}"


async def add_torrent_to_client(
    client_type: str,
    url: str,
    username: Optional[str],
    password: Optional[str],
    torrent_url_or_magnet: str,
    category: Optional[str] = None,
    tags: Optional[str] = None,
) -> Tuple[bool, str]:
    """Point d'entrée générique pour ajouter un torrent."""
    if client_type == "qbittorrent":
        return await add_qbittorrent_torrent(url, username, password, torrent_url_or_magnet, category, tags)
    elif client_type == "transmission":
        # Transmission ne supporte pas natively les catégories de la même manière, on passe les tags comme labels
        return await add_transmission_torrent(url, username, password, torrent_url_or_magnet, tags)
    return False, f"Type de client inconnu: {client_type}"
