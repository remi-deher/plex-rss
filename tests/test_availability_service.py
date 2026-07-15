"""Tests unitaires pour app/services/availability_service.py — has_plex_proof."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.models import LibraryItem, MediaRequest, RequestStatus, Settings
from app.services.availability_service import has_plex_proof


def _settings(**kwargs) -> Settings:
    defaults = dict(
        plex_url="http://plex.local",
        plex_token="plex-token",
        vff_libraries=json.dumps([{"name": "Films", "kind": "movie"}]),
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _req(**kwargs) -> MediaRequest:
    defaults = dict(
        plex_user_id="alice",
        title="Society of the Snow",
        media_type="movie",
        year=2023,
        tmdb_id="906126",
        imdb_id="tt16277242",
        status=RequestStatus.sent_to_arr,
    )
    defaults.update(kwargs)
    return MediaRequest(**defaults)


@pytest.mark.asyncio
async def test_has_plex_proof_true_when_library_item_cache_matches(async_db):
    async_db.add(_settings())
    async_db.add(LibraryItem(title="Society of the Snow", media_type="movie", year=2023, tmdb_id="906126"))
    async_db.add_all([])
    req = _req()
    async_db.add(req)
    async_db.commit()

    with patch("app.services.plex_finder") as mock_finder:
        result = await has_plex_proof(async_db, req)

    assert result is True
    mock_finder.connect.assert_not_called()  # cache suffit, pas de requete live


@pytest.mark.asyncio
async def test_has_plex_proof_falls_back_to_live_plex_when_cache_misses(async_db):
    """Régression production : "Society of the Snow" disponible dans Plex/Radarr (hasFile=true)
    mais aucune LibraryItem correspondante (le cache ne se resynchronise qu'une fois par jour,
    cron_plex_sync à 03:15) — has_plex_proof doit retomber sur une requête Plex live ciblée
    plutôt que de rester bloqué jusqu'au prochain sync complet."""
    async_db.add(_settings())
    # Un LibraryItem existe pour AUTRE chose, donc count(LibraryItem) > 0 : le court-circuit
    # "cache vide -> True" ne doit pas être ce qui fait passer ce test.
    async_db.add(LibraryItem(title="Unrelated Movie", media_type="movie", year=1999, tmdb_id="1"))
    req = _req()
    async_db.add(req)
    async_db.commit()

    mock_plex = MagicMock()
    mock_item = MagicMock()
    with patch("app.services.plex_finder") as mock_finder:
        mock_finder.connect.return_value = mock_plex
        mock_finder.find_item_in_libraries.return_value = mock_item
        result = await has_plex_proof(async_db, req)

    assert result is True
    mock_finder.connect.assert_called_once_with("http://plex.local", "plex-token")
    args = mock_finder.find_item_in_libraries.call_args
    assert args[0][0] is mock_plex
    assert args[0][1] == ["Films"]
    assert args[0][2] == "Society of the Snow"


@pytest.mark.asyncio
async def test_has_plex_proof_false_when_live_lookup_also_misses(async_db):
    async_db.add(_settings())
    async_db.add(LibraryItem(title="Unrelated Movie", media_type="movie", year=1999, tmdb_id="1"))
    req = _req()
    async_db.add(req)
    async_db.commit()

    with patch("app.services.plex_finder") as mock_finder:
        mock_finder.connect.return_value = MagicMock()
        mock_finder.find_item_in_libraries.return_value = None
        result = await has_plex_proof(async_db, req)

    assert result is False


@pytest.mark.asyncio
async def test_has_plex_proof_live_lookup_error_is_non_fatal(async_db):
    async_db.add(_settings())
    async_db.add(LibraryItem(title="Unrelated Movie", media_type="movie", year=1999, tmdb_id="1"))
    req = _req()
    async_db.add(req)
    async_db.commit()

    with patch("app.services.plex_finder") as mock_finder:
        mock_finder.connect.side_effect = Exception("Plex unreachable")
        result = await has_plex_proof(async_db, req)

    assert result is False


@pytest.mark.asyncio
async def test_has_plex_proof_no_live_fallback_without_matching_library_kind(async_db):
    """Aucune bibliothèque du bon type (film) configurée dans vff_libraries -> pas de
    requête live possible, refuse plutôt que de deviner."""
    async_db.add(_settings(vff_libraries=json.dumps([{"name": "Series", "kind": "series"}])))
    async_db.add(LibraryItem(title="Unrelated Movie", media_type="movie", year=1999, tmdb_id="1"))
    req = _req()
    async_db.add(req)
    async_db.commit()

    with patch("app.services.plex_finder") as mock_finder:
        result = await has_plex_proof(async_db, req)

    assert result is False
    mock_finder.connect.assert_not_called()
