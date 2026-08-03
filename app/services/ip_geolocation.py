"""Resolution GeoIP des lecteurs Plex, avec cache et degradation gracieuse."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
from xml.etree import ElementTree

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cache import cache
from ..models import PlaybackIpLocation
from ..utils import now_utc_naive

logger = logging.getLogger(__name__)

_PLEX_GEOIP_URL = "https://plex.tv/api/v2/geoip"
_GEOIP_SOFT_TTL = 24 * 60 * 60
_GEOIP_HARD_TTL = 7 * 24 * 60 * 60


def _empty_location(status: str) -> dict:
    return {
        "geo_status": status,
        "geo_city": None,
        "geo_region": None,
        "geo_country": None,
        "geo_country_code": None,
        "geo_lat": None,
        "geo_lon": None,
    }


_LOCATION_FIELDS = tuple(_empty_location("unavailable"))


def _persistent_location(row: PlaybackIpLocation) -> dict:
    return {field: getattr(row, field) for field in _LOCATION_FIELDS}


def _canonical_address(address: str | None) -> str | None:
    if not address:
        return None
    try:
        return str(ipaddress.ip_address(str(address).removeprefix("::ffff:")))
    except ValueError:
        return None


def _address_hash(address: str) -> str:
    return hashlib.sha256(address.encode()).hexdigest()


def _parse_plex_geoip(xml: str) -> dict:
    root = ElementTree.fromstring(xml)
    location = root if root.tag.lower().endswith("location") else root.find(".//location")
    if location is None:
        return _empty_location("unavailable")
    coordinates = [part.strip() for part in location.get("coordinates", "").split(",")]
    try:
        latitude, longitude = (float(coordinates[0]), float(coordinates[1]))
    except (IndexError, TypeError, ValueError):
        latitude = longitude = None
    result = {
        "geo_status": "resolved",
        "geo_city": location.get("city") or None,
        "geo_region": location.get("subdivisions") or None,
        "geo_country": location.get("country") or None,
        "geo_country_code": location.get("code") or None,
        "geo_lat": latitude,
        "geo_lon": longitude,
    }
    if not any(result[key] for key in ("geo_city", "geo_region", "geo_country", "geo_lat")):
        result["geo_status"] = "unavailable"
    return result


async def lookup_ip_location(address: str | None, *, anonymized: bool = False) -> dict:
    """Retourne une localisation approximative sans jamais faire echouer la collecte.

    Les IP privees ne quittent pas l'instance. Pour une IP publique, l'API GeoIP de
    Plex est interrogee puis le resultat est conserve une semaine. La cle de cache est
    hachee afin de ne pas recopier l'adresse brute dans Redis.
    """
    if anonymized:
        return _empty_location("anonymized")
    if not address:
        return _empty_location("unavailable")
    try:
        parsed = ipaddress.ip_address(address.removeprefix("::ffff:"))
    except ValueError:
        return _empty_location("unavailable")
    if parsed.is_private or parsed.is_loopback or parsed.is_link_local:
        result = _empty_location("local")
        result["geo_country"] = "local"
        return result

    digest = hashlib.sha256(str(parsed).encode()).hexdigest()
    cache_key = f"plexarr:geoip:v1:{digest}"

    async def resolve() -> dict:
        try:
            async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
                response = await client.get(
                    _PLEX_GEOIP_URL,
                    params={"ip_address": str(parsed)},
                    headers={"Accept": "application/xml"},
                )
                response.raise_for_status()
            return _parse_plex_geoip(response.text)
        except Exception as exc:
            logger.info("Resolution GeoIP Plex impossible pour %s: %s", digest[:10], exc)
            return _empty_location("unavailable")

    return await cache.get_or_refresh(
        cache_key,
        _GEOIP_SOFT_TTL,
        _GEOIP_HARD_TTL,
        resolve,
    )


async def lookup_ip_locations(
    addresses: list[str | None] | set[str | None],
    *,
    db: AsyncSession,
    anonymized: bool = False,
    seed_locations: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """Résout chaque IP une fois et conserve le résultat sans stocker l'IP brute.

    Une correspondance existante n'est jamais remplacée. ``seed_locations`` permet au
    recalcul historique de réutiliser une ancienne localisation déjà valide.
    """
    originals = {str(address).strip() for address in addresses if str(address or "").strip()}
    if anonymized:
        value = _empty_location("anonymized")
        return {address: value.copy() for address in originals}

    canonical_by_original = {
        address: canonical
        for address in originals
        if (canonical := _canonical_address(address)) is not None
    }
    hashes = {_address_hash(address) for address in canonical_by_original.values()}
    existing = (
        await db.execute(
            select(PlaybackIpLocation).where(PlaybackIpLocation.address_hash.in_(hashes))
        )
    ).scalars().all() if hashes else []
    stored = {row.address_hash: row for row in existing}
    now = now_utc_naive()
    for row in existing:
        row.last_used_at = now

    seed_locations = seed_locations or {}
    missing = {
        canonical
        for canonical in canonical_by_original.values()
        if _address_hash(canonical) not in stored
    }

    semaphore = asyncio.Semaphore(8)

    async def resolve(address: str) -> tuple[str, dict]:
        seeded = seed_locations.get(address)
        if seeded and seeded.get("geo_status") in {"resolved", "local"}:
            return address, {field: seeded.get(field) for field in _LOCATION_FIELDS}
        async with semaphore:
            return address, await lookup_ip_location(address)

    resolved = dict(await asyncio.gather(*(resolve(address) for address in missing)))
    for address, location in resolved.items():
        if location.get("geo_status") not in {"resolved", "local"}:
            continue
        row = PlaybackIpLocation(
            address_hash=_address_hash(address),
            created_at=now,
            last_used_at=now,
            **{field: location.get(field) for field in _LOCATION_FIELDS},
        )
        db.add(row)
        stored[row.address_hash] = row

    result = {}
    for original in originals:
        canonical = canonical_by_original.get(original)
        if canonical is None:
            result[original] = _empty_location("unavailable")
            continue
        row = stored.get(_address_hash(canonical))
        result[original] = (
            _persistent_location(row)
            if row is not None
            else resolved.get(canonical, _empty_location("unavailable"))
        )
    return result
