"""Resolution GeoIP des lecteurs Plex, avec cache et degradation gracieuse."""

from __future__ import annotations

import hashlib
import ipaddress
import logging
from xml.etree import ElementTree

import httpx

from ..cache import cache

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
        result["geo_country"] = "Reseau local"
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
