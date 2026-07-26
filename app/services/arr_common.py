"""Appels API v3 communs à Sonarr et Radarr.

Sonarr et Radarr exposent la même API v3 pour tout ce qui ne concerne pas le média
lui-même : connecteurs de notification, schéma de webhook, profils de qualité, dossiers
racine, tags, espace disque, file de téléchargement, commandes d'import. Ces fonctions
étaient auparavant dupliquées à l'identique dans `sonarr.py` et `radarr.py` — au mot près
pour une quinzaine d'entre elles.

Les fonctions dont le message de retour ou de log mentionne le produit prennent un
argument `product` ("Sonarr" / "Radarr") : `sonarr.py` et `radarr.py` en exposent une
version pré-liée via `functools.partial`, pour que les appelants (et les tests qui
patchent `sonarr.<fonction>`) gardent exactement la même signature qu'avant.

Ce qui reste dans `sonarr.py` / `radarr.py` : l'ajout de média, les lookups par
identifiant externe, la disponibilité, la normalisation des enregistrements de file
(les champs diffèrent réellement), et tout ce qui est propre aux saisons/épisodes.
"""

import logging
import re

import httpx

from ..utils import safe_error_message
from .arr_http_client import ArrClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers purs
# ---------------------------------------------------------------------------


def normalize_title(value: str | None) -> str:
    """Réduit un titre à ses caractères alphanumériques minuscules, pour comparaison."""
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def poster_from_images(images: list[dict] | None) -> str | None:
    """URL de l'affiche parmi les images d'un média *arr (coverType == "poster")."""
    return next(
        (
            img.get("remoteUrl") or img.get("url")
            for img in (images or [])
            if img.get("coverType") == "poster"
        ),
        None,
    )


def normalize_release(r: dict) -> dict:
    """Réduit une release Sonarr/Radarr à un format compact pour l'UI.

    Conserve les infos clés pour la sélection (qualité, langues, score custom
    format) — les langues permettent de repérer les versions françaises (VF).
    """
    langs = [lang.get("name") for lang in (r.get("languages") or []) if lang.get("name")]
    quality = ((r.get("quality") or {}).get("quality") or {}).get("name")
    return {
        "guid": r.get("guid"),
        "title": r.get("title"),
        "indexer": r.get("indexer"),
        "indexer_id": r.get("indexerId"),
        "size": r.get("size"),
        "seeders": r.get("seeders", 0),
        "leechers": r.get("leechers", 0),
        "protocol": r.get("protocol"),
        "quality": quality,
        "languages": langs,
        "custom_format_score": r.get("customFormatScore", 0),
        "custom_formats": [cf.get("name") for cf in (r.get("customFormats") or []) if cf.get("name")],
        "rejected": r.get("rejected", False),
        "rejections": r.get("rejections") or [],
    }


def queue_progress(r: dict) -> tuple[int, int, float]:
    """(size, sizeleft, progress %) d'un enregistrement de file *arr."""
    size = r.get("size") or 0
    sizeleft = r.get("sizeleft") or 0
    return size, sizeleft, round((size - sizeleft) / size * 100, 1) if size else 0


# ---------------------------------------------------------------------------
# Média : existence, suppression, recherche
# ---------------------------------------------------------------------------


async def media_exists(url: str, api_key: str, arr_id: int, *, resource: str) -> bool:
    """Vérifie par GET direct si un média existe encore côté *arr.

    Ne catch PAS les erreurs réseau/HTTP : elles remontent à l'appelant pour ne jamais
    être confondues avec un 404 confirmé (*arr injoignable != média supprimé).
    """
    client = ArrClient(url, api_key, timeout=15)
    resp = await client.get(f"/api/v3/{resource}/{arr_id}")
    if resp.status_code == 404:
        return False
    resp.raise_for_status()
    return True


async def delete_media(
    url: str,
    api_key: str,
    arr_id: int,
    delete_files: bool = False,
    *,
    resource: str,
    exclusion_param: str,
    absent_message: str,
    deleted_message: str,
) -> tuple[bool, str]:
    """Supprime un média de *arr (et ses fichiers si demandé).

    Un 404 est traité comme un succès (déjà absent). Toute autre erreur (réseau,
    timeout, 5xx) lève une exception — l'appelant ne doit jamais supprimer la
    demande locale correspondante si cet appel échoue.
    """
    client = ArrClient(url, api_key, timeout=20)
    resp = await client.delete(
        f"/api/v3/{resource}/{arr_id}",
        params={"deleteFiles": "true" if delete_files else "false", exclusion_param: "false"},
    )
    if resp.status_code == 404:
        return True, absent_message
    resp.raise_for_status()
    return True, deleted_message


async def run_search_command(
    url: str, api_key: str, *, product: str, command: str, payload: dict, log_context: str
) -> bool:
    """Lance une commande de recherche de fichiers (*Search) et retourne son acceptation.

    Utilisé par l'auto-search VFF : relance une recherche quand un média n'est
    disponible qu'en VO, dans l'espoir de trouver une version française.
    """
    try:
        client = ArrClient(url, api_key, timeout=15)
        resp = await client.post("/api/v3/command", json={"name": command, **payload})
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.warning(f"{product} {command} échec ({log_context}): {e}")
        return False


async def get_all_media(url: str, api_key: str, *, resource: str) -> list[dict]:
    """Retourne la liste complète des médias connus de *arr (pour le scan de fallback)."""
    client = ArrClient(url, api_key, timeout=15)
    resp = await client.get(f"/api/v3/{resource}")
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Releases et import
# ---------------------------------------------------------------------------


async def grab_release(
    url: str, api_key: str, guid: str, indexer_id: int, *, product: str
) -> tuple[bool, str]:
    """Grab d'une release choisie manuellement : *arr télécharge ET importe.

    Returns (ok, message).
    """
    try:
        client = ArrClient(url, api_key, timeout=30)
        resp = await client.post(
            "/api/v3/release",
            json={"guid": guid, "indexerId": indexer_id},
        )
        resp.raise_for_status()
        return True, f"Release envoyée à {product}"
    except Exception as e:
        logger.warning(f"{product} grab_release échec (guid {guid}): {e}")
        return False, str(e)


async def get_releases(
    url: str, api_key: str, *, params: dict, product: str, log_context: str
) -> list[dict]:
    """Recherche interactive *arr : releases scorées (GET /release)."""
    try:
        client = ArrClient(url, api_key, timeout=90)
        resp = await client.get("/api/v3/release", params=params)
        resp.raise_for_status()
        return [normalize_release(r) for r in resp.json()]
    except Exception as e:
        logger.warning(f"{product} get_releases échec ({log_context}): {e}")
        return []


async def get_manual_import_candidates(
    url: str, api_key: str, download_id: str, *, product: str
) -> list[dict]:
    """Fichiers en attente d'import manuel pour un téléchargement (GET /manualimport).

    Utilisé quand *arr ne peut pas matcher automatiquement le média (ex : épisode pas
    encore officiellement sorti dans ses métadonnées), pour laisser l'utilisateur
    choisir à la main, comme dans l'UI native de Sonarr/Radarr.
    """
    try:
        client = ArrClient(url, api_key, timeout=20)
        resp = await client.get(
            "/api/v3/manualimport",
            params={"downloadId": download_id, "filterExistingFiles": "true"},
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"{product} get_manual_import_candidates échec: {e}")
        return []


async def manual_import(
    url: str, api_key: str, *, file_entry: dict, product: str
) -> tuple[bool, str]:
    """Force l'import d'un fichier téléchargé (commande ManualImport).

    `file_entry` est construit par l'appelant : les clés diffèrent entre séries
    (`seriesId` + `episodeIds`) et films (`movieId`).
    """
    try:
        client = ArrClient(url, api_key, timeout=20)
        resp = await client.post(
            "/api/v3/command",
            json={"name": "ManualImport", "files": [file_entry], "importMode": "auto"},
        )
        resp.raise_for_status()
        return True, "Import manuel lancé"
    except httpx.HTTPStatusError as e:
        return False, f"{product} a refusé l'import : {e.response.text[:200]}"
    except Exception as e:
        return False, str(e)


async def trigger_import(
    url: str,
    api_key: str,
    *,
    command: str,
    product: str,
    output_path: str | None = None,
    download_id: str | None = None,
) -> tuple[bool, str]:
    """Déclenche le scan d'import *arr pour un téléchargement en attente d'import
    (trackedDownloadState == importPending), via le chemin de sortie ou le downloadId.
    """
    payload: dict = {"name": command}
    if output_path:
        payload["path"] = output_path
    if download_id:
        payload["downloadClientId"] = download_id
    try:
        client = ArrClient(url, api_key, timeout=20)
        resp = await client.post("/api/v3/command", json=payload)
        resp.raise_for_status()
        return True, "Import lancé"
    except httpx.HTTPStatusError as e:
        return False, f"{product} a refusé l'import : {e.response.text[:200]}"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# File de téléchargement
# ---------------------------------------------------------------------------


async def fetch_queue_records(
    url: str, api_key: str, *, params: dict, product: str, raise_on_error: bool = False
) -> list[dict]:
    """Enregistrements bruts de la file de téléchargement *arr (GET /queue)."""
    try:
        client = ArrClient(url, api_key, timeout=20)
        resp = await client.get("/api/v3/queue", params=params)
        resp.raise_for_status()
        return resp.json().get("records", [])
    except Exception as e:
        logger.warning(f"{product} get_queue échec: {e}")
        if raise_on_error:
            raise
        return []


async def delete_queue_item(
    url: str,
    api_key: str,
    queue_id: int,
    *,
    blocklist: bool = False,
    search: bool = True,
    product: str,
) -> tuple[bool, str]:
    """Supprime un item de la file *arr, avec blocklist et relance de recherche optionnelles."""
    try:
        client = ArrClient(url, api_key, timeout=20)
        resp = await client.delete(
            f"/api/v3/queue/{queue_id}",
            params={
                "removeFromClient": "true",
                "blocklist": "true" if blocklist else "false",
                "skipRedownload": "false" if search else "true",
            },
        )
        if resp.status_code in (200, 204):
            return True, f"Item supprimé de la file {product}"
        resp.raise_for_status()
        return True, f"Item supprimé de la file {product}"
    except Exception as e:
        logger.warning(f"{product} delete_queue_item échec (queue {queue_id}): {e}")
        return False, str(e)


async def get_queue_media_ids(
    url: str, api_key: str, *, id_key: str, product: str, log_name: str
) -> set[int]:
    """IDs des médias ayant au moins un item actif dans la file de téléchargement *arr.

    Utilisé pour distinguer une vraie anomalie Plex (fichier importé mais introuvable
    dans Plex) d'un média encore en cours de téléchargement (ex: upgrade de qualité en
    file, ou d'autres épisodes de la même série toujours en attente).
    """
    try:
        client = ArrClient(url, api_key, timeout=20)
        resp = await client.get("/api/v3/queue", params={"pageSize": 200})
        resp.raise_for_status()
        records = resp.json().get("records", [])
    except Exception as e:
        logger.warning(f"{product} {log_name} échec: {e}")
        return set()
    return {r[id_key] for r in records if r.get(id_key)}


# ---------------------------------------------------------------------------
# Connexion et configuration
# ---------------------------------------------------------------------------


async def check_connection(url: str, api_key: str, *, product: str) -> tuple[bool, str]:
    """Teste la connectivité avec l'instance *arr.

    Returns:
        (success, message)
    """
    try:
        client = ArrClient(url, api_key, timeout=10)
        resp = await client.get("/api/v3/system/status")
        resp.raise_for_status()
        data = resp.json()
        return True, f"{product} v{data.get('version', '?')} connecté"
    except Exception as e:
        logger.warning(f"{product} check_connection échec ({url}): {e}")
        return False, safe_error_message(e)


async def get_quality_profiles(url: str, api_key: str) -> list[dict]:
    """Retourne les profils de qualité disponibles (pour le formulaire de config)."""
    client = ArrClient(url, api_key, timeout=10)
    resp = await client.get("/api/v3/qualityprofile")
    resp.raise_for_status()
    return [{"id": p["id"], "name": p["name"]} for p in resp.json()]


async def get_root_folders(url: str, api_key: str) -> list[dict]:
    """Retourne les dossiers racine configurés dans *arr (pour le formulaire de config)."""
    client = ArrClient(url, api_key, timeout=10)
    resp = await client.get("/api/v3/rootfolder")
    resp.raise_for_status()
    return [
        {
            "path": f["path"],
            "free_bytes": f.get("freeSpace"),
            "total_bytes": f.get("totalSpace"),
        }
        for f in resp.json()
    ]


async def get_tags(url: str, api_key: str) -> list[dict]:
    """Retourne les tags configurés dans *arr (id + label)."""
    client = ArrClient(url, api_key, timeout=10)
    resp = await client.get("/api/v3/tag")
    resp.raise_for_status()
    return [{"id": t["id"], "label": t["label"]} for t in resp.json()]


async def get_disk_space(url: str, api_key: str) -> list[dict]:
    """Retourne l'espace disque des volumes connus de *arr.

    Returns:
        Liste de {path, free_bytes, total_bytes}.
    """
    client = ArrClient(url, api_key, timeout=10)
    resp = await client.get("/api/v3/diskspace")
    resp.raise_for_status()
    return [{"path": d["path"], "free_bytes": d["freeSpace"], "total_bytes": d["totalSpace"]} for d in resp.json()]


async def get_calendar(
    url: str, api_key: str, start: str, end: str, *, product: str, extra_params: dict | None = None
) -> list[dict]:
    """Médias dont une date attendue tombe entre deux dates (GET /api/v3/calendar).

    `start`/`end` : dates ISO 8601. Sonarr renvoie les épisodes attendus/diffusés (avec
    `includeSeries=true` pour le titre, les identifiants externes et l'affiche) ; Radarr
    renvoie un film dès qu'UNE de ses dates (inCinemas/physicalRelease/digitalRelease)
    est dans la plage.
    """
    try:
        client = ArrClient(url, api_key, timeout=20)
        resp = await client.get(
            "/api/v3/calendar",
            params={"start": start, "end": end, **(extra_params or {})},
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"{product} get_calendar failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Connecteurs de notification (Settings → Connect)
# ---------------------------------------------------------------------------


async def get_notifications(url: str, api_key: str) -> list[dict]:
    """Retourne les connecteurs de notification configurés dans *arr (Settings → Connect)."""
    client = ArrClient(url, api_key, timeout=10)
    resp = await client.get("/api/v3/notification")
    resp.raise_for_status()
    return resp.json()


def find_webhook_notification(notifications: list[dict], webhook_path: str) -> dict | None:
    """Trouve, parmi les connecteurs *arr, celui de type Webhook pointant vers notre endpoint."""
    for notif in notifications:
        if notif.get("implementation") != "Webhook":
            continue
        for field in notif.get("fields", []):
            if field.get("name") == "url" and webhook_path in str(field.get("value", "")):
                return notif
    return None


def find_plex_notification(notifications: list[dict]) -> dict | None:
    """Trouve le connecteur natif 'Plex Media Server' de *arr, actif sur import/téléchargement.

    S'il existe, *arr notifie déjà Plex directement (scan ciblé sur le dossier importé)
    à chaque import — pas la peine de dupliquer avec notre propre refresh de section.
    """
    for notif in notifications:
        if notif.get("implementation") == "PlexServer" and (notif.get("onDownload") or notif.get("onImport")):
            return notif
    return None


async def test_notification(
    url: str, api_key: str, notification: dict, *, product: str
) -> tuple[bool, str]:
    """Déclenche depuis *arr un test réel du connecteur Webhook (round-trip vers notre endpoint).

    Réutilise l'endpoint /api/v3/notification/test, qui envoie une notification de test
    avec la configuration fournie sans la re-sauvegarder.
    """
    try:
        client = ArrClient(url, api_key, timeout=20)
        resp = await client.post("/api/v3/notification/test", json=notification)
        if resp.status_code in (200, 204):
            return True, f"Test envoyé et accepté par {product}"
        try:
            errors = resp.json()
            msg = (
                "; ".join(e.get("errorMessage", str(e)) for e in errors)
                if isinstance(errors, list)
                else str(errors)
            )
        except Exception:
            msg = resp.text
        return False, msg or f"HTTP {resp.status_code}"
    except Exception as e:
        return False, str(e)


async def get_webhook_schema(url: str, api_key: str) -> dict | None:
    """Retourne le schéma vierge du connecteur 'Webhook' (pour en créer un nouveau)."""
    client = ArrClient(url, api_key, timeout=10)
    resp = await client.get("/api/v3/notification/schema")
    resp.raise_for_status()
    for entry in resp.json():
        if entry.get("implementation") == "Webhook":
            return entry
    return None


def build_webhook_payload(schema: dict, webhook_url: str, flags: dict[str, bool], name: str = "Plexarr") -> dict:
    """Construit le payload de création d'un connecteur Webhook à partir du schéma *arr,
    en pré-remplissant l'URL et en n'activant que les événements passés dans `flags`."""
    payload = {k: v for k, v in schema.items() if k != "id"}
    fields = []
    for field in schema.get("fields", []):
        field = dict(field)
        if field.get("name") == "url":
            field["value"] = webhook_url
        elif field.get("name") == "method":
            field["value"] = 1  # POST
        fields.append(field)
    payload["fields"] = fields
    payload["name"] = name
    payload.update(flags)
    return payload


async def create_notification(url: str, api_key: str, payload: dict) -> dict:
    """Crée un nouveau connecteur de notification dans *arr (Settings → Connect)."""
    client = ArrClient(url, api_key, timeout=15)
    resp = await client.post("/api/v3/notification", json=payload)
    resp.raise_for_status()
    return resp.json()


async def update_notification(url: str, api_key: str, notification: dict) -> dict:
    """Met à jour un connecteur de notification existant dans *arr."""
    client = ArrClient(url, api_key, timeout=15)
    resp = await client.put(f"/api/v3/notification/{notification['id']}", json=notification)
    resp.raise_for_status()
    return resp.json()
