import hashlib
import logging
import os
import re
import uuid
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_QB_STATE_MAP: dict[str, str] = {
    "downloading": "downloading",
    "checkingdl": "downloading",
    "stalleddl": "downloading",
    "metadl": "downloading",
    "forceddl": "downloading",
    "uploading": "seeding",
    "stalledup": "seeding",
    "forcedup": "seeding",
    "checkingup": "seeding",
    "pauseddl": "paused",
    "pausedup": "paused",
}

_WATCH_FOLDER_STATUS = {
    "name": "Watch Folder",
    "progress": 100.0,
    "status": "completed",
    "ratio": 0.0,
    "seeding_time": 0,
    "download_speed": 0,
    "upload_speed": 0,
    "eta": 0,
    "content_path": None,
}


def extract_hash_from_magnet(magnet: str) -> Optional[str]:
    """Extrait le hash info d'un lien magnet (format hexadecimal 40 caractères)."""
    m = re.search(r"urn:btih:([a-zA-Z0-9]+)", magnet)
    if m:
        h = m.group(1).lower()
        # Si c'est encodé en base32 (32 caractères), on le garde, mais qBittorrent et Transmission supportent l'hex.
        # En général c'est du sha1 hex (40 char).
        return h
    return None


async def qbittorrent_login(
    client: httpx.AsyncClient, url: str, username: Optional[str], password: Optional[str]
) -> str | None:
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


async def check_qbittorrent(url: str, username: Optional[str], password: Optional[str]) -> tuple[bool, str]:
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
) -> tuple[bool, str, str | None]:
    """Ajoute un torrent à qBittorrent et retourne (success, message, hash)."""
    async with httpx.AsyncClient() as client:
        sid = await qbittorrent_login(client, url, username, password)
        if not sid:
            return False, "Échec de connexion/authentification", None

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
                # Récupérer le hash du torrent
                info_hash = extract_hash_from_magnet(torrent_url_or_magnet)
                if not info_hash:
                    # Si c'était un lien HTTP, interroger les torrents récents pour trouver le hash
                    try:
                        info_url = f"{url.rstrip('/')}/api/v2/torrents/info"
                        r_info = await client.get(
                            info_url,
                            params={"sort": "added_on", "reverse": "true", "limit": 1},
                            cookies={"SID": sid},
                            timeout=5,
                        )
                        if r_info.status_code == 200:
                            torrents = r_info.json()
                            if torrents:
                                info_hash = torrents[0].get("hash")
                    except Exception as e:
                        logger.warning(f"Impossible de récupérer le hash du torrent récemment ajouté : {e}")
                return True, "Torrent ajouté avec succès à qBittorrent", info_hash
            return False, f"Réponse qBittorrent: {r.text}", None
        except Exception as e:
            return False, f"Erreur d'ajout qBittorrent: {str(e)}", None


async def get_qbittorrent_status(
    url: str, username: Optional[str], password: Optional[str], torrent_hash: str
) -> dict | None:
    """Récupère l'avancement d'un torrent spécifique dans qBittorrent."""
    async with httpx.AsyncClient() as client:
        sid = await qbittorrent_login(client, url, username, password)
        if not sid:
            return None
        info_url = f"{url.rstrip('/')}/api/v2/torrents/info"
        try:
            r = await client.get(info_url, params={"hashes": torrent_hash}, cookies={"SID": sid}, timeout=10)
            r.raise_for_status()
            torrents = r.json()
            if not torrents:
                return None
            t = torrents[0]
            state = t.get("state", "").lower()
            if "error" in state or "missing" in state:
                status = "error"
            else:
                status = _QB_STATE_MAP.get(state, "completed")

            return {
                "name": t.get("name", ""),
                "content_path": t.get("content_path") or (
                    os.path.join(t.get("save_path"), t.get("name", "")) if t.get("save_path") else None
                ),
                "progress": t.get("progress", 0.0) * 100.0,
                "status": status,
                "ratio": t.get("ratio", 0.0),
                "seeding_time": t.get("seeding_time", 0),
                "download_speed": t.get("dlspeed", 0),
                "upload_speed": t.get("upspeed", 0),
                "eta": t.get("eta", 0),
            }
        except Exception as e:
            logger.error(f"Error getting qBittorrent status: {e}")
            return None


async def delete_qbittorrent_torrent(
    url: str, username: Optional[str], password: Optional[str], torrent_hash: str, delete_files: bool
) -> bool:  # noqa: FBT001
    """Supprime un torrent dans qBittorrent."""
    async with httpx.AsyncClient() as client:
        sid = await qbittorrent_login(client, url, username, password)
        if not sid:
            return False
        delete_url = f"{url.rstrip('/')}/api/v2/torrents/delete"
        data = {"hashes": torrent_hash, "deleteFiles": "true" if delete_files else "false"}
        try:
            r = await client.post(delete_url, data=data, cookies={"SID": sid}, timeout=10)
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Error deleting qBittorrent torrent: {e}")
            return False


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
    headers: dict[str, str] = {}
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


async def check_transmission(url: str, username: Optional[str], password: Optional[str]) -> tuple[bool, str]:
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
    url: str,
    username: Optional[str],
    password: Optional[str],
    torrent_url_or_magnet: str,
    tags: Optional[str] = None,
) -> tuple[bool, str, str | None]:
    """Ajoute un torrent à Transmission."""
    async with httpx.AsyncClient() as client:
        try:
            args: dict[str, object] = {"filename": torrent_url_or_magnet}
            if tags:
                args["labels"] = [t.strip() for t in tags.split(",") if t.strip()]

            res = await transmission_rpc(client, url, username, password, "torrent-add", args)
            if res.get("result") == "success":
                torrent_info = res.get("arguments", {}).get("torrent-added") or res.get("arguments", {}).get(
                    "torrent-duplicate"
                )
                info_hash = torrent_info.get("hashString") if torrent_info else None
                if not info_hash:
                    info_hash = extract_hash_from_magnet(torrent_url_or_magnet)
                return True, "Torrent ajouté avec succès à Transmission", info_hash
            return False, f"Erreur de réponse RPC: {res.get('result')}", None
        except Exception as e:
            return False, f"Erreur d'ajout RPC: {str(e)}", None


async def get_transmission_status(
    url: str, username: Optional[str], password: Optional[str], torrent_hash: str
) -> dict | None:
    """Récupère l'avancement d'un torrent spécifique dans Transmission."""
    async with httpx.AsyncClient() as client:
        try:
            args = {
                "ids": [torrent_hash],
                "fields": [
                    "id",
                    "name",
                    "percentDone",
                    "status",
                    "uploadRatio",
                    "secondsSeeding",
                    "rateDownload",
                    "rateUpload",
                    "eta",
                    "downloadDir",
                ],
            }
            res = await transmission_rpc(client, url, username, password, "torrent-get", args)
            if res.get("result") != "success":
                return None
            torrents = res.get("arguments", {}).get("torrents", [])
            if not torrents:
                return None
            t = torrents[0]
            raw_status = t.get("status", 0)
            if raw_status == 4:
                status = "downloading"
            elif raw_status == 6:
                status = "seeding"
            elif raw_status == 0:
                status = "paused"
            else:
                status = "downloading" if t.get("percentDone", 0.0) < 1.0 else "seeding"

            return {
                "name": t.get("name", ""),
                "content_path": (
                    os.path.join(t.get("downloadDir"), t.get("name", "")) if t.get("downloadDir") else None
                ),
                "progress": t.get("percentDone", 0.0) * 100.0,
                "status": status,
                "ratio": t.get("uploadRatio", 0.0),
                "seeding_time": t.get("secondsSeeding", 0),
                "download_speed": t.get("rateDownload", 0),
                "upload_speed": t.get("rateUpload", 0),
                "eta": t.get("eta", 0),
            }
        except Exception as e:
            logger.error(f"Error getting Transmission status: {e}")
            return None


async def delete_transmission_torrent(
    url: str, username: Optional[str], password: Optional[str], torrent_hash: str, delete_files: bool
) -> bool:
    """Supprime un torrent dans Transmission."""
    async with httpx.AsyncClient() as client:
        try:
            args = {"ids": [torrent_hash], "delete-local-data": delete_files}
            res = await transmission_rpc(client, url, username, password, "torrent-remove", args)
            return res.get("result") == "success"
        except Exception as e:
            logger.error(f"Error deleting Transmission torrent: {e}")
            return False


async def check_watch_folder(path: str) -> tuple[bool, str]:
    """Vérifie l'accessibilité du Watch Folder."""
    if not os.path.isdir(path):
        return False, f"Le dossier n'existe pas ou n'est pas un répertoire : {path}"
    try:
        # Test de création/suppression de fichier temporaire
        test_file = os.path.join(path, f".test_{uuid.uuid4().hex}")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        return True, "Dossier surveillé accessible en écriture"
    except Exception as e:
        return False, f"Erreur d'accès en écriture : {str(e)}"


async def add_watch_folder_torrent(path: str, torrent_url_or_magnet: str) -> tuple[bool, str, str | None]:
    """Télécharge le fichier torrent depuis Prowlarr et l'écrit dans le dossier surveillé."""
    if torrent_url_or_magnet.startswith("magnet:"):
        return False, "Le mode dossier surveillé ne supporte pas les liens magnet", None

    if not os.path.isdir(path):
        return False, f"Le dossier surveillé n'existe pas : {path}", None

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(torrent_url_or_magnet, follow_redirects=True, timeout=30)
            r.raise_for_status()

            filename = f"torrent_{uuid.uuid4().hex}.torrent"
            cd = r.headers.get("content-disposition", "")
            if "filename=" in cd:
                for part in cd.split(";"):
                    if "filename=" in part:
                        fn = part.split("=")[1].strip("\"'")
                        if fn.endswith(".torrent"):
                            filename = fn
                            break

            filepath = os.path.join(path, filename)
            with open(filepath, "wb") as f:
                f.write(r.content)

            # Info hash généré par SHA1 déterministe de l'URL pour identification unique
            info_hash = hashlib.sha1(torrent_url_or_magnet.encode("utf-8")).hexdigest()
            return True, f"Fichier torrent écrit avec succès : {filename}", info_hash
    except Exception as e:
        return False, f"Erreur lors de l'écriture dans le dossier surveillé : {str(e)}", None


async def check_client_connection(
    client_type: str, url: str, username: Optional[str], password: Optional[str]
) -> tuple[bool, str]:
    """Point d'entrée générique pour tester la connexion."""
    if client_type == "qbittorrent":
        return await check_qbittorrent(url, username, password)
    elif client_type == "transmission":
        return await check_transmission(url, username, password)
    elif client_type == "watch_folder":
        return await check_watch_folder(url)
    return False, f"Type de client inconnu: {client_type}"


async def add_torrent_to_client(
    client_type: str,
    url: str,
    username: Optional[str],
    password: Optional[str],
    torrent_url_or_magnet: str,
    category: Optional[str] = None,
    tags: Optional[str] = None,
) -> tuple[bool, str, str | None]:
    """Point d'entrée générique pour ajouter un torrent. Retourne (success, message, hash)."""
    if client_type == "qbittorrent":
        return await add_qbittorrent_torrent(url, username, password, torrent_url_or_magnet, category, tags)
    elif client_type == "transmission":
        return await add_transmission_torrent(url, username, password, torrent_url_or_magnet, tags)
    elif client_type == "watch_folder":
        return await add_watch_folder_torrent(url, torrent_url_or_magnet)
    return False, f"Type de client inconnu: {client_type}", None


async def add_torrent_file_to_client(
    client_type: str,
    url: str,
    username: Optional[str],
    password: Optional[str],
    torrent_bytes: bytes,
    filename: str = "upload.torrent",
    category: Optional[str] = None,
    tags: Optional[str] = None,
) -> tuple[bool, str, str | None]:
    """Envoie un fichier .torrent (bytes) directement à un client. Retourne (success, message, hash)."""
    import base64

    def _parse_info_hash(data: bytes) -> str | None:
        """Extrait le SHA1 info-hash d'un fichier .torrent via bencode minimal."""
        try:
            import hashlib

            pos = data.find(b"4:info")
            if pos == -1:
                return None
            pos += 6
            # find end of dict
            depth = 1
            i = pos
            while i < len(data) and depth > 0:
                if data[i : i + 1] == b"d":
                    depth += 1
                    i += 1
                elif data[i : i + 1] == b"e":
                    depth -= 1
                    i += 1
                elif data[i : i + 1] == b"l":
                    depth += 1
                    i += 1
                elif data[i : i + 1] in (b"i",):
                    end = data.index(b"e", i + 1)
                    i = end + 1
                elif data[i : i + 1].isdigit():
                    colon = data.index(b":", i)
                    length = int(data[i:colon])
                    i = colon + 1 + length
                else:
                    i += 1
            info_dict = data[pos:i]
            return hashlib.sha1(info_dict).hexdigest()
        except Exception:
            return None

    if client_type == "qbittorrent":
        async with httpx.AsyncClient() as client_http:
            sid = await qbittorrent_login(client_http, url, username, password)
            if not sid:
                return False, "Échec de connexion qBittorrent", None
            add_url = f"{url.rstrip('/')}/api/v2/torrents/add"
            form_data = {}
            if category:
                form_data["category"] = category
            if tags:
                form_data["tags"] = tags
            try:
                r = await client_http.post(
                    add_url,
                    data=form_data,
                    files={"torrents": (filename, torrent_bytes, "application/x-bittorrent")},
                    cookies={"SID": sid},
                    timeout=20,
                )
                r.raise_for_status()
                info_hash = _parse_info_hash(torrent_bytes)
                return True, "Fichier .torrent ajouté à qBittorrent", info_hash
            except Exception as e:
                return False, f"Erreur qBittorrent : {e}", None

    elif client_type == "transmission":
        async with httpx.AsyncClient() as client_http:
            try:
                metainfo = base64.b64encode(torrent_bytes).decode()
                args: dict = {"metainfo": metainfo}
                if tags:
                    args["labels"] = [t.strip() for t in tags.split(",") if t.strip()]
                res = await transmission_rpc(client_http, url, username, password, "torrent-add", args)
                if res.get("result") == "success":
                    torrent_info = res.get("arguments", {}).get("torrent-added") or res.get("arguments", {}).get(
                        "torrent-duplicate"
                    )
                    info_hash = torrent_info.get("hashString") if torrent_info else _parse_info_hash(torrent_bytes)
                    return True, "Fichier .torrent ajouté à Transmission", info_hash
                return False, f"Erreur RPC: {res.get('result')}", None
            except Exception as e:
                return False, f"Erreur Transmission : {e}", None

    elif client_type == "watch_folder":
        try:
            dest = os.path.join(url, filename)
            with open(dest, "wb") as f:
                f.write(torrent_bytes)
            return True, f"Fichier copié dans {dest}", None
        except Exception as e:
            return False, f"Erreur watch folder : {e}", None

    return False, f"Type de client inconnu : {client_type}", None


async def get_torrent_status(
    client_type: str, url: str, username: Optional[str], password: Optional[str], torrent_hash: str
) -> dict | None:
    """Point d'entrée générique pour obtenir l'avancement d'un torrent."""
    if client_type == "qbittorrent":
        return await get_qbittorrent_status(url, username, password, torrent_hash)
    elif client_type == "transmission":
        return await get_transmission_status(url, username, password, torrent_hash)
    elif client_type == "watch_folder":
        return _WATCH_FOLDER_STATUS
    return None


async def delete_torrent(
    client_type: str,
    url: str,
    username: Optional[str],
    password: Optional[str],
    torrent_hash: str,
    delete_files: bool = False,
) -> bool:
    """Point d'entrée générique pour supprimer un torrent."""
    if client_type == "qbittorrent":
        return await delete_qbittorrent_torrent(url, username, password, torrent_hash, delete_files)
    elif client_type == "transmission":
        return await delete_transmission_torrent(url, username, password, torrent_hash, delete_files)
    elif client_type == "watch_folder":
        return True
    return False
