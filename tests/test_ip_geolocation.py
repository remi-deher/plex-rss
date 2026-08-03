from unittest.mock import AsyncMock, patch

import pytest

from app.models import PlaybackIpLocation
from app.services.ip_geolocation import (
    _parse_plex_geoip,
    lookup_ip_location,
    lookup_ip_locations,
)


def test_parse_plex_geoip_extracts_location_and_coordinates():
    result = _parse_plex_geoip(
        '<location code="FR" country="France" city="Lyon" subdivisions="Auvergne-Rhone-Alpes" '
        'coordinates="45.75, 4.85" />'
    )

    assert result == {
        "geo_status": "resolved",
        "geo_city": "Lyon",
        "geo_region": "Auvergne-Rhone-Alpes",
        "geo_country": "France",
        "geo_country_code": "FR",
        "geo_lat": 45.75,
        "geo_lon": 4.85,
    }


@pytest.mark.asyncio
async def test_private_ip_is_not_sent_to_external_lookup():
    with patch("app.services.ip_geolocation.httpx.AsyncClient") as client:
        result = await lookup_ip_location("192.168.1.25")

    assert result["geo_status"] == "local"
    assert result["geo_country"] == "local"
    client.assert_not_called()


@pytest.mark.asyncio
async def test_anonymized_ip_is_not_sent_to_external_lookup():
    with patch("app.services.ip_geolocation.httpx.AsyncClient", new=AsyncMock()) as client:
        result = await lookup_ip_location("8.8.8.0", anonymized=True)

    assert result["geo_status"] == "anonymized"
    client.assert_not_called()


@pytest.mark.asyncio
async def test_persistent_location_is_reused_without_storing_raw_ip(async_db):
    resolved = {
        "geo_status": "resolved",
        "geo_city": "Paris",
        "geo_region": "Île-de-France",
        "geo_country": "France",
        "geo_country_code": "FR",
        "geo_lat": 48.8566,
        "geo_lon": 2.3522,
    }
    with patch(
        "app.services.ip_geolocation.lookup_ip_location",
        new=AsyncMock(return_value=resolved),
    ) as lookup:
        first = await lookup_ip_locations({"82.64.10.20"}, db=async_db)
        await async_db.commit()
        second = await lookup_ip_locations({"82.64.10.20"}, db=async_db)

    assert first["82.64.10.20"] == resolved
    assert second["82.64.10.20"] == resolved
    lookup.assert_awaited_once_with("82.64.10.20")
    stored = async_db.query(PlaybackIpLocation).one()
    assert stored.geo_city == "Paris"
    assert "82.64.10.20" not in stored.address_hash
