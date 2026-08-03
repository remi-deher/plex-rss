from unittest.mock import AsyncMock, patch

import pytest

from app.services.ip_geolocation import _parse_plex_geoip, lookup_ip_location


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
    assert result["geo_country"] == "Reseau local"
    client.assert_not_called()


@pytest.mark.asyncio
async def test_anonymized_ip_is_not_sent_to_external_lookup():
    with patch("app.services.ip_geolocation.httpx.AsyncClient", new=AsyncMock()) as client:
        result = await lookup_ip_location("8.8.8.0", anonymized=True)

    assert result["geo_status"] == "anonymized"
    client.assert_not_called()
