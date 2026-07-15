"""Tests unitaires pour app/services/vff_scanner.py."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.models import Settings
from app.services import vff_scanner
from app.services.vff_scanner import trigger_plex_library_refresh


@pytest.fixture(autouse=True)
def _reset_section_refresh_cooldown():
    """`_last_section_refresh` est un cache anti-rebond au niveau module (45s) : le vider
    avant chaque test évite qu'un appel précédent sur la même section fausse l'assertion
    suivante (refresh ignoré comme "déjà fait récemment" au lieu du comportement testé)."""
    vff_scanner._last_section_refresh.clear()
    yield
    vff_scanner._last_section_refresh.clear()


def _settings(**kwargs) -> Settings:
    defaults = dict(
        vff_enabled=True,
        plex_url="http://plex.local",
        plex_token="plex-token",
        vff_libraries=json.dumps([{"name": "Films", "kind": "movie"}]),
    )
    defaults.update(kwargs)
    return Settings(**defaults)


@pytest.mark.asyncio
async def test_trigger_plex_library_refresh_calls_plex_finder():
    """Régression : le refresh Plex accéléré appelait `vff.refresh_sections_blocking`, un
    nom jamais importé dans ce module (NameError silencieusement avalé par le
    `except Exception` englobant) — le refresh ciblé sur webhook *arr n'avait donc jamais
    lieu, forçant un délai de détection VF sur le seul cron planifié. La bonne fonction
    est `plex_finder.refresh_sections_blocking` (import réel du module, ligne 17)."""
    settings = _settings()
    with patch("app.services.vff_scanner.plex_finder.refresh_sections_blocking") as mock_refresh:
        await trigger_plex_library_refresh(settings, "movie")

    mock_refresh.assert_called_once_with("http://plex.local", "plex-token", ["Films"])


@pytest.mark.asyncio
async def test_trigger_plex_library_refresh_noop_without_matching_library():
    settings = _settings(vff_libraries=json.dumps([{"name": "Series", "kind": "series"}]))
    with patch("app.services.vff_scanner.plex_finder.refresh_sections_blocking") as mock_refresh:
        await trigger_plex_library_refresh(settings, "movie")

    mock_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_plex_library_refresh_noop_when_vff_disabled():
    settings = _settings(vff_enabled=False)
    with patch("app.services.vff_scanner.plex_finder.refresh_sections_blocking") as mock_refresh:
        await trigger_plex_library_refresh(settings, "movie")

    mock_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_plex_library_refresh_skips_when_arr_has_native_connector():
    settings = _settings()
    with (
        patch("app.services.vff_scanner.has_native_plex_connector", new=AsyncMock(return_value=True)),
        patch("app.services.vff_scanner.plex_finder.refresh_sections_blocking") as mock_refresh,
    ):
        await trigger_plex_library_refresh(
            settings, "movie", arr_type="radarr", arr_url="http://radarr.local", arr_api_key="key", cache_key="radarr:1"
        )

    mock_refresh.assert_not_called()
