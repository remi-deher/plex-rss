"""_ensure_tmdb_id : resolution IMDB -> TMDB pour les films RSS (toujours munis d'un
imdb_id, voir plex_rss.py). Radarr est tente en premier (table de correspondance
externe deja utilisee pour l'envoi), avec un repli direct sur l'API TMDB
(/find/{imdb_id}) quand Radarr n'a pas pu resoudre — independant de Radarr,
utile quand il est injoignable ou ne connait pas encore un titre recent.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import Settings
from app.services.tmdb import TmdbNotConfigured
from app.services.watchlist_poller import _ensure_tmdb_id


def _movie_item(**kwargs):
    defaults = dict(
        title="Lee Cronin's The Mummy",
        year=2026,
        media_type="movie",
        imdb_id="tt32612507",
        tvdb_id=None,
        tmdb_id=None,
    )
    defaults.update(kwargs)
    return defaults


def _settings(**kwargs):
    defaults = dict(radarr_url=None, radarr_api_key=None, seer_url=None, seer_api_key=None)
    defaults.update(kwargs)
    return Settings(**defaults)


def _fake_db():
    """Session dont db.execute(...).scalars().first() renvoie toujours None
    (pas d'ArrInstance Radarr par defaut trouvee)."""
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_ensure_tmdb_id_already_present_skips_everything():
    item = _movie_item(tmdb_id="12345")
    result = await _ensure_tmdb_id(item, _settings(), None, db=None)
    assert result is item


@pytest.mark.asyncio
async def test_ensure_tmdb_id_falls_back_to_tmdb_when_radarr_not_configured():
    item = _movie_item()
    with patch(
        "app.services.watchlist_poller.tmdb_find_by_external_id", new=AsyncMock(return_value=42718)
    ) as mock_tmdb:
        result = await _ensure_tmdb_id(item, _settings(), None, db=_fake_db())
    mock_tmdb.assert_awaited_once()
    assert result["tmdb_id"] == "42718"


@pytest.mark.asyncio
async def test_ensure_tmdb_id_radarr_success_skips_tmdb_fallback():
    item = _movie_item()
    with (
        patch("app.services.watchlist_poller.resolve_tmdb_id", new=AsyncMock(return_value="42718")),
        patch("app.services.watchlist_poller.tmdb_find_by_external_id", new=AsyncMock()) as mock_tmdb,
    ):
        result = await _ensure_tmdb_id(
            item, _settings(radarr_url="http://radarr", radarr_api_key="key"), None, db=object()
        )
    mock_tmdb.assert_not_called()
    assert result["tmdb_id"] == "42718"


@pytest.mark.asyncio
async def test_ensure_tmdb_id_tmdb_not_configured_is_silently_ignored():
    item = _movie_item()
    with patch(
        "app.services.watchlist_poller.tmdb_find_by_external_id",
        new=AsyncMock(side_effect=TmdbNotConfigured("no key")),
    ):
        result = await _ensure_tmdb_id(item, _settings(), None, db=_fake_db())
    assert result.get("tmdb_id") is None
