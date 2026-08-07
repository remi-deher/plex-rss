"""Proxy et cache disque des affiches : contourne le blocage mixed-content et les hotes prives (serveur Plex/*arr du LAN, injoignable depuis l'exterieur)."""

import asyncio
import hashlib
import logging
import os as _os
import time
from io import BytesIO
from urllib.parse import urlparse, urlunparse
from weakref import WeakValueDictionary

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError
from sqlalchemy.future import select

from ..database import AsyncSessionLocal
from ..dependencies import require_auth
from ..models import ArrInstance, LibraryItem, MediaRequest, Settings
from ..utils import safe_error_message

router = APIRouter(prefix="/api", tags=["misc"])
logger = logging.getLogger(__name__)

_STATIC_ALLOWED_IMAGE_HOSTS = {
    "image.tmdb.org",
    "artworks.thetvdb.com",
    "thetvdb.com",
    "banner.thetvdb.com",
    "media.themoviedb.org",
    "plex.tv",
}
_allowed_hosts_cache: tuple[float, set[str]] = (0.0, set())
_allowed_hosts_lock = asyncio.Lock()

async def _allowed_image_hosts() -> set[str]:
    """Hôtes vers lesquels /api/image-proxy est autorisé à faire une requête.

    Limité aux hôtes explicitement configurés par l'admin (serveur Plex, instances
    *arr) plus le CDN TMDB, afin d'empêcher un utilisateur authentifié d'utiliser ce
    proxy pour atteindre des hôtes internes/externes arbitraires (SSRF).

    La session DB est ouverte ici, seulement quand le cache (60 s) est froid, plutot
    qu'injectee dans la route : une grille de posters declenchait sinon une connexion par
    image, y compris pour les requetes servies depuis le cache disque.
    """
    global _allowed_hosts_cache
    if time.monotonic() - _allowed_hosts_cache[0] < 60:
        return set(_allowed_hosts_cache[1])
    async with _allowed_hosts_lock:
        if time.monotonic() - _allowed_hosts_cache[0] < 60:
            return set(_allowed_hosts_cache[1])
        hosts = set(_STATIC_ALLOWED_IMAGE_HOSTS)
        async with AsyncSessionLocal() as db:
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
        _allowed_hosts_cache = (time.monotonic(), hosts)
        return set(hosts)

_IMAGE_CACHE_DIR = _os.path.join("data", "image_cache")

_IMAGE_CACHE_TTL = 86400  # aligné sur le Cache-Control déjà envoyé au navigateur
_image_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

def _image_cache_paths(url: str) -> tuple[str, str]:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return (
        _os.path.join(_IMAGE_CACHE_DIR, f"{digest}.bin"),
        _os.path.join(_IMAGE_CACHE_DIR, f"{digest}.meta"),
    )

def _read_image_meta(url: str) -> tuple[str, float] | None:
    """Lit le seul fichier .meta (quelques octets), sans toucher a l'image elle-meme.

    Permet de trancher fraicheur et ETag avant de payer la lecture du binaire : sur une
    grille de posters, la quasi-totalite des requetes se termine en 304.
    """
    _, meta_path = _image_cache_paths(url)
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            content_type, cached_at = f.read().split("\n", 1)
        return content_type, float(cached_at)
    except Exception:
        return None


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

def _write_image_cache(url: str, content: bytes, content_type: str, cached_at: float) -> None:
    """`cached_at` est fourni par l'appelant plutot que pris ici : il entre dans l'ETag,
    qui doit designer exactement la version ecrite sur disque."""
    try:
        _os.makedirs(_IMAGE_CACHE_DIR, exist_ok=True)
        content_path, meta_path = _image_cache_paths(url)
        with open(content_path, "wb") as f:
            f.write(content)
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write(f"{content_type}\n{cached_at}")
    except Exception as e:
        logger.warning(f"Cache image : écriture impossible pour {url}: {e}")


def _variant_key(url: str, width: int | None, height: int | None, quality: int, image_format: str) -> str:
    if not width and not height and image_format == "original":
        return url
    return f"{url}|w={width or 0}|h={height or 0}|q={quality}|fmt={image_format}"


def _transform_image(
    content: bytes, width: int | None, height: int | None, quality: int, image_format: str
) -> tuple[bytes, str]:
    try:
        with Image.open(BytesIO(content)) as image:
            source_format = image.format or "PNG"
            image.load()
            image.thumbnail((width or image.width, height or image.height), Image.Resampling.LANCZOS)
            output_format = source_format if image_format == "original" else image_format.upper()
            if output_format in {"WEBP", "AVIF"} and image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGB")
            output = BytesIO()
            image.save(output, format=output_format, quality=quality, optimize=True)
            mime_format = "jpeg" if output_format.upper() == "JPEG" else output_format.lower()
            return output.getvalue(), f"image/{mime_format}"
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError(f"Transformation d'image impossible: {exc}") from exc


_CACHE_HEADERS = {"Cache-Control": "private, max-age=86400, stale-while-revalidate=604800"}


def _variant_etag(variant_key: str, cached_at: float) -> str:
    """ETag derive de l'identite de la variante et de sa date de mise en cache.

    `variant_key` designe deja un contenu unique (URL source + dimensions + qualite +
    format) et `cached_at` change a chaque re-telechargement : hacher ces quelques octets
    suffit, la ou hacher l'image entiere coutait un SHA-256 sur plusieurs centaines de Ko
    a chaque requete, y compris celles qui repartent en 304.
    """
    digest = hashlib.sha256(f"{variant_key}|{cached_at}".encode("utf-8")).hexdigest()
    return f'"{digest}"'


def _image_response(content: bytes, content_type: str, etag: str) -> Response:
    return Response(content=content, media_type=content_type, headers={**_CACHE_HEADERS, "ETag": etag})

@router.get("/image-proxy", dependencies=[Depends(require_auth)])
async def image_proxy(
    request: Request,
    url: str,
    width: int | None = Query(None, ge=32, le=1600),
    height: int | None = Query(None, ge=32, le=1600),
    quality: int = Query(82, ge=40, le=95),
    image_format: str = Query("original", alias="format", pattern="^(original|webp|avif)$"),
):
    """Proxy, redimensionne et met en cache les affiches de l'interface."""
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(400, "URL image invalide")
    allowed_hosts = await _allowed_image_hosts()
    if not parsed.hostname or parsed.hostname.lower() not in allowed_hosts:
        raise HTTPException(400, "Hôte d'image non autorisé")
    safe_url = urlunparse(parsed)
    variant_key = _variant_key(safe_url, width, height, quality, image_format)

    async def _serve_if_cached() -> Response | None:
        """Sert la variante depuis le cache disque, en 304 si le navigateur l'a deja."""
        meta = await asyncio.to_thread(_read_image_meta, variant_key)
        if not meta or time.time() - meta[1] >= _IMAGE_CACHE_TTL:
            return None
        content_type, cached_at = meta
        etag = _variant_etag(variant_key, cached_at)
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={**_CACHE_HEADERS, "ETag": etag})
        cached = await asyncio.to_thread(_read_image_cache, variant_key)
        if not cached:
            return None
        return _image_response(cached[0], cached[1], etag)

    response = await _serve_if_cached()
    if response is not None:
        return response

    # Une seule récupération/transformation à la fois par variante, même lors du rendu
    # simultané de plusieurs cartes qui utilisent la même affiche.
    lock = _image_locks.setdefault(variant_key, asyncio.Lock())
    async with lock:
        response = await _serve_if_cached()
        if response is not None:
            return response

        source = await asyncio.to_thread(_read_image_cache, safe_url)
        if not source or time.time() - source[2] >= _IMAGE_CACHE_TTL:
            try:
                async with httpx.AsyncClient(
                    timeout=15, follow_redirects=False, verify=False
                ) as client:
                    upstream = await client.get(safe_url)
                    upstream.raise_for_status()
                content_type = upstream.headers.get(
                    "content-type", "application/octet-stream"
                ).split(";")[0].strip().lower()
                if not content_type.startswith("image/"):
                    raise HTTPException(415, "La ressource n'est pas une image")
                fetched_at = time.time()
                source = (upstream.content, content_type, fetched_at)
                await asyncio.to_thread(
                    _write_image_cache, safe_url, upstream.content, content_type, fetched_at
                )
            except HTTPException:
                raise
            except Exception as exc:
                if not source:
                    raise HTTPException(
                        502, f"Image inaccessible: {safe_error_message(exc)}"
                    ) from exc
                logger.warning(
                    "Image inaccessible, repli sur le cache périmé pour %s: %s",
                    safe_url,
                    exc,
                )

        content, content_type, variant_cached_at = source
        if width or height or image_format != "original":
            try:
                content, content_type = await asyncio.to_thread(
                    _transform_image, content, width, height, quality, image_format
                )
            except ValueError as exc:
                raise HTTPException(415, str(exc)) from exc
            variant_cached_at = time.time()
            await asyncio.to_thread(
                _write_image_cache, variant_key, content, content_type, variant_cached_at
            )
        return _image_response(content, content_type, _variant_etag(variant_key, variant_cached_at))


@router.get("/image-proxy/library/{library_item_id}", dependencies=[Depends(require_auth)])
async def library_image_proxy(
    request: Request,
    library_item_id: int,
    width: int | None = Query(500, ge=32, le=1600),
    height: int | None = Query(None, ge=32, le=1600),
    quality: int = Query(82, ge=40, le=95),
    image_format: str = Query("webp", alias="format", pattern="^(original|webp|avif)$"),
):
    """Sert une affiche Plex sans révéler son URL signée au navigateur."""
    async with AsyncSessionLocal() as db:
        item = (
            await db.execute(select(LibraryItem).filter(LibraryItem.id == library_item_id))
        ).scalars().first()
    if not item or not item.poster_url:
        raise HTTPException(404, "Affiche introuvable")
    return await image_proxy(
        request=request,
        url=item.poster_url,
        width=width,
        height=height,
        quality=quality,
        image_format=image_format,
    )


@router.get("/image-proxy/request/{request_id}", dependencies=[Depends(require_auth)])
async def request_image_proxy(
    request: Request,
    request_id: int,
    width: int | None = Query(500, ge=32, le=1600),
    height: int | None = Query(None, ge=32, le=1600),
    quality: int = Query(82, ge=40, le=95),
    image_format: str = Query("webp", alias="format", pattern="^(original|webp|avif)$"),
):
    """Sert l'affiche d'une demande sans révéler son éventuelle URL Plex signée."""
    async with AsyncSessionLocal() as db:
        media_request = (
            await db.execute(select(MediaRequest).filter(MediaRequest.id == request_id))
        ).scalars().first()
    if not media_request or not media_request.poster_url:
        raise HTTPException(404, "Affiche introuvable")
    return await image_proxy(
        request=request,
        url=media_request.poster_url,
        width=width,
        height=height,
        quality=quality,
        image_format=image_format,
    )
