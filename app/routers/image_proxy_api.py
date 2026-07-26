"""Proxy et cache disque des affiches : contourne le blocage mixed-content et les hotes prives (serveur Plex/*arr du LAN, injoignable depuis l'exterieur)."""

import asyncio
import hashlib
import logging
import os as _os
import time
from urllib.parse import urlparse, urlunparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import get_db_async
from ..dependencies import require_auth
from ..models import ArrInstance, Settings
from ..utils import safe_error_message

router = APIRouter(prefix="/api", tags=["misc"])
logger = logging.getLogger(__name__)

_STATIC_ALLOWED_IMAGE_HOSTS = {"image.tmdb.org"}

async def _allowed_image_hosts(db: AsyncSession) -> set[str]:
    """Hôtes vers lesquels /api/image-proxy est autorisé à faire une requête.

    Limité aux hôtes explicitement configurés par l'admin (serveur Plex, instances
    *arr) plus le CDN TMDB, afin d'empêcher un utilisateur authentifié d'utiliser ce
    proxy pour atteindre des hôtes internes/externes arbitraires (SSRF).
    """
    hosts = set(_STATIC_ALLOWED_IMAGE_HOSTS)
    settings = (await db.execute(select(Settings))).scalars().first()
    if settings and settings.plex_url:
        host = urlparse(settings.plex_url).hostname
        if host:
            hosts.add(host.lower())
    instances = (await db.execute(select(ArrInstance))).scalars().all()
    for inst in instances:
        if inst.url:
            host = urlparse(inst.url).hostname
            if host:
                hosts.add(host.lower())
    return hosts

_IMAGE_CACHE_DIR = _os.path.join("data", "image_cache")

_IMAGE_CACHE_TTL = 86400  # aligné sur le Cache-Control déjà envoyé au navigateur

def _image_cache_paths(url: str) -> tuple[str, str]:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return (
        _os.path.join(_IMAGE_CACHE_DIR, f"{digest}.bin"),
        _os.path.join(_IMAGE_CACHE_DIR, f"{digest}.meta"),
    )

def _read_image_cache(url: str) -> tuple[bytes, str, float] | None:
    content_path, meta_path = _image_cache_paths(url)
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            content_type, cached_at = f.read().split("\n", 1)
        with open(content_path, "rb") as f:
            content = f.read()
        return content, content_type, float(cached_at)
    except Exception:
        return None

def _write_image_cache(url: str, content: bytes, content_type: str) -> None:
    try:
        _os.makedirs(_IMAGE_CACHE_DIR, exist_ok=True)
        content_path, meta_path = _image_cache_paths(url)
        with open(content_path, "wb") as f:
            f.write(content)
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write(f"{content_type}\n{time.time()}")
    except Exception as e:
        logger.warning(f"Cache image : écriture impossible pour {url}: {e}")

@router.get("/image-proxy", dependencies=[Depends(require_auth)])
async def image_proxy(url: str, db: AsyncSession = Depends(get_db_async)):
    """Proxy authenticated UI images to avoid HTTPS pages loading HTTP posters directly.

    Mis en cache sur disque 24h (voir `_IMAGE_CACHE_DIR`) : la majorité des affichages
    ne retapent donc jamais Plex, et en cas d'échec Plex ponctuel une version périmée
    du cache est servie plutôt qu'un 502 si elle existe.
    """
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(400, "URL image invalide")

    # SSRF : n'autorise que les hôtes configurés (Plex, instances *arr) + TMDB. Sans ce
    # contrôle, tout utilisateur authentifié (même non-admin) pouvait faire proxier par
    # le serveur une requête vers n'importe quel hôte, y compris interne (réseau privé,
    # métadonnées cloud) puisque le endpoint suivait les redirections et acceptait
    # n'importe quel netloc.
    allowed_hosts = await _allowed_image_hosts(db)
    if not parsed.hostname or parsed.hostname.lower() not in allowed_hosts:
        raise HTTPException(400, "Hôte d'image non autorisé")
    # La requête HTTP réelle part de l'URL reconstruite depuis les composants déjà
    # validés (parsed.scheme/netloc/...), jamais de la valeur brute reçue en entrée :
    # exclut par construction toute confusion d'hôte (ex. userinfo `http://ok@evil`)
    # qui aurait pu échapper à la seule comparaison sur `parsed.hostname`.
    safe_url = urlunparse(parsed)

    cached = await asyncio.to_thread(_read_image_cache, safe_url)
    if cached:
        content, content_type, cached_at = cached
        if time.time() - cached_at < _IMAGE_CACHE_TTL:
            return Response(content=content, media_type=content_type, headers={"Cache-Control": "private, max-age=86400"})

    try:
        # follow_redirects=False : une redirection vers un hôte non autorisé contournerait
        # sinon le contrôle ci-dessus.
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, verify=False) as client:
            resp = await client.get(safe_url)
            resp.raise_for_status()
    except Exception as e:
        if cached:
            content, content_type, _ = cached
            logger.warning(f"Image inaccessible, repli sur le cache périmé pour {safe_url}: {e}")
            return Response(content=content, media_type=content_type, headers={"Cache-Control": "private, max-age=86400"})
        raise HTTPException(502, f"Image inaccessible: {safe_error_message(e)}") from e

    content_type = resp.headers.get("content-type", "application/octet-stream").split(";")[0].strip().lower()
    if not content_type.startswith("image/"):
        raise HTTPException(415, "La ressource n'est pas une image")
    await asyncio.to_thread(_write_image_cache, safe_url, resp.content, content_type)
    return Response(
        content=resp.content,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )
