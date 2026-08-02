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
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import get_db_async
from ..dependencies import require_auth
from ..models import ArrInstance, Settings
from ..utils import safe_error_message

router = APIRouter(prefix="/api", tags=["misc"])
logger = logging.getLogger(__name__)

_STATIC_ALLOWED_IMAGE_HOSTS = {"image.tmdb.org"}
_allowed_hosts_cache: tuple[float, set[str]] = (0.0, set())
_allowed_hosts_lock = asyncio.Lock()

async def _allowed_image_hosts(db: AsyncSession) -> set[str]:
    """Hôtes vers lesquels /api/image-proxy est autorisé à faire une requête.

    Limité aux hôtes explicitement configurés par l'admin (serveur Plex, instances
    *arr) plus le CDN TMDB, afin d'empêcher un utilisateur authentifié d'utiliser ce
    proxy pour atteindre des hôtes internes/externes arbitraires (SSRF).
    """
    global _allowed_hosts_cache
    if time.monotonic() - _allowed_hosts_cache[0] < 60:
        return set(_allowed_hosts_cache[1])
    async with _allowed_hosts_lock:
        if time.monotonic() - _allowed_hosts_cache[0] < 60:
            return set(_allowed_hosts_cache[1])
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


def _image_response(content: bytes, content_type: str, request: Request) -> Response:
    etag = f'"{hashlib.sha256(content).hexdigest()}"'
    headers = {
        "Cache-Control": "private, max-age=86400, stale-while-revalidate=604800",
        "ETag": etag,
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=content, media_type=content_type, headers=headers)

@router.get("/image-proxy", dependencies=[Depends(require_auth)])
async def image_proxy(
    request: Request,
    url: str,
    width: int | None = Query(None, ge=32, le=1600),
    height: int | None = Query(None, ge=32, le=1600),
    quality: int = Query(82, ge=40, le=95),
    image_format: str = Query("original", alias="format", pattern="^(original|webp|avif)$"),
    db: AsyncSession = Depends(get_db_async),
):
    """Proxy, redimensionne et met en cache les affiches de l'interface."""
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(400, "URL image invalide")
    allowed_hosts = await _allowed_image_hosts(db)
    if not parsed.hostname or parsed.hostname.lower() not in allowed_hosts:
        raise HTTPException(400, "Hôte d'image non autorisé")
    safe_url = urlunparse(parsed)
    variant_key = _variant_key(safe_url, width, height, quality, image_format)

    cached = await asyncio.to_thread(_read_image_cache, variant_key)
    if cached and time.time() - cached[2] < _IMAGE_CACHE_TTL:
        return _image_response(cached[0], cached[1], request)

    # Une seule récupération/transformation à la fois par variante, même lors du rendu
    # simultané de plusieurs cartes qui utilisent la même affiche.
    lock = _image_locks.setdefault(variant_key, asyncio.Lock())
    async with lock:
        cached = await asyncio.to_thread(_read_image_cache, variant_key)
        if cached and time.time() - cached[2] < _IMAGE_CACHE_TTL:
            return _image_response(cached[0], cached[1], request)

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
                source = (upstream.content, content_type, time.time())
                await asyncio.to_thread(
                    _write_image_cache, safe_url, upstream.content, content_type
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

        content, content_type, _ = source
        if width or height or image_format != "original":
            try:
                content, content_type = await asyncio.to_thread(
                    _transform_image, content, width, height, quality, image_format
                )
            except ValueError as exc:
                raise HTTPException(415, str(exc)) from exc
            await asyncio.to_thread(
                _write_image_cache, variant_key, content, content_type
            )
        return _image_response(content, content_type, request)
