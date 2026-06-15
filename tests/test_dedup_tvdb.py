"""
Tests pour les fonctionnalités de déduplication liées au tvdb_id :
- _find_global_request : fallback tvdb_id
- _clean_title : suppression du suffixe (YYYY)
- sync_seer_requests : conservation de la date la plus ancienne
- poll_watchlists : pas de recherche Seer si tvdb_id déjà présent
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, MediaRequest, PlexUser, RequestStatus, Settings
from app.scheduler import (
    _clean_title,
    _find_global_request,
    poll_watchlists,
    sync_seer_requests,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _settings(**kwargs) -> Settings:
    defaults = dict(
        sonarr_url="http://sonarr.local",
        sonarr_api_key="key",
        sonarr_enabled=True,
        sonarr_quality_profile_id=1,
        sonarr_root_folder="/tv",
        radarr_url="http://radarr.local",
        radarr_api_key="key",
        radarr_enabled=True,
        radarr_quality_profile_id=1,
        radarr_root_folder="/movies",
        radarr_minimum_availability="released",
        seer_enabled=False,
        seer_url=None,
        seer_api_key=None,
        email_on_request=False,
        email_on_available=False,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _req(
    plex_user_id="alice",
    title="Invincible",
    media_type="show",
    tmdb_id=None,
    tvdb_id="81763",
    status=RequestStatus.sent_to_arr,
    **kwargs,
) -> MediaRequest:
    return MediaRequest(
        plex_user_id=plex_user_id,
        plex_user=plex_user_id,
        title=title,
        media_type=media_type,
        tmdb_id=tmdb_id,
        tvdb_id=tvdb_id,
        status=status,
        **kwargs,
    )


def _patch_session(db):
    return patch("app.scheduler.SessionLocal", return_value=db)


def _patch_watchlist(items):
    return patch("app.scheduler.fetch_watchlist", new=AsyncMock(return_value=items))


def _patch_submit(arr_id=42, existed=False, slug=None):
    return patch("app.scheduler._submit_to_arr", new=AsyncMock(return_value=(arr_id, existed, slug)))


def _patch_enqueue():
    return patch("app.scheduler.enqueue_notification")


# ---------------------------------------------------------------------------
# _clean_title
# ---------------------------------------------------------------------------


def test_clean_title_removes_year_suffix():
    assert _clean_title("INVINCIBLE (2021)") == "INVINCIBLE"


def test_clean_title_removes_year_with_spaces():
    assert _clean_title("Liar Game  (2007)  ") == "Liar Game"


def test_clean_title_no_year_unchanged():
    assert _clean_title("Inception") == "Inception"


def test_clean_title_year_in_middle_unchanged():
    """Un (YYYY) au milieu du titre ne doit pas être retiré."""
    assert _clean_title("Star Wars (1977) Episode IV") == "Star Wars (1977) Episode IV"


def test_clean_title_empty_string():
    assert _clean_title("") == ""


# ---------------------------------------------------------------------------
# _find_global_request — fallback tvdb_id
# ---------------------------------------------------------------------------


def test_find_global_request_by_tvdb_id(db):
    """Sans tmdb_id, trouve par tvdb_id avant le titre."""
    db.add(_req(plex_user_id="alice", tmdb_id=None, tvdb_id="81763", title="Liar Game"))
    db.commit()

    result = _find_global_request(db, "show", None, "Titre différent", tvdb_id="81763")
    assert result is not None
    assert result.plex_user_id == "alice"


def test_find_global_request_tvdb_after_tmdb_miss(db):
    """Si tmdb_id ne matche pas, tente tvdb_id avant le titre."""
    db.add(_req(plex_user_id="alice", tmdb_id="99999", tvdb_id="81763"))
    db.commit()

    # tmdb_id "00001" introuvable → fallback tvdb_id "81763" → trouvé
    result = _find_global_request(db, "show", "00001", "Peu importe", tvdb_id="81763")
    assert result is not None


def test_find_global_request_tmdb_takes_priority_over_tvdb(db):
    """tmdb_id prioritaire : si deux entrées, retourne celle avec le bon tmdb_id."""
    db.add(_req(plex_user_id="alice", tmdb_id="27205", tvdb_id="81763"))
    db.add(_req(plex_user_id="bob", tmdb_id="99999", tvdb_id="00000"))
    db.commit()

    result = _find_global_request(db, "show", "27205", "Liar Game", tvdb_id="00000")
    assert result is not None
    assert result.plex_user_id == "alice"


def test_find_global_request_tvdb_not_found_falls_to_title(db):
    """tvdb_id inconnu → fallback titre."""
    db.add(_req(plex_user_id="alice", tmdb_id=None, tvdb_id=None, title="Liar Game"))
    db.commit()

    result = _find_global_request(db, "show", None, "Liar Game", tvdb_id="99999")
    assert result is not None
    assert result.plex_user_id == "alice"


def test_find_global_request_all_miss_returns_none(db):
    """tmdb, tvdb et titre tous introuvables → None."""
    result = _find_global_request(db, "show", "111", "Inconnu", tvdb_id="222")
    assert result is None


# ---------------------------------------------------------------------------
# sync_seer_requests — conservation de la date la plus ancienne
# ---------------------------------------------------------------------------


SEER_REQUEST_WITH_DATE = [
    {
        "seer_request_id": 7,
        "media_type": "movie",
        "tmdb_id": "27205",
        "tvdb_id": None,
        "imdb_id": None,
        "title": "Inception",
        "overview": "",
        "status": "sent_to_arr",
        "poster_url": None,
        # "requested_at" est le nom après remapping par seer_get_user_requests
        "requested_at": "2026-01-29T12:00:00.000Z",
    }
]


@pytest.mark.asyncio
async def test_seer_sync_keeps_older_rss_date(db):
    """Si la demande RSS est plus ancienne que Seer, la date RSS est conservée."""
    old_date = datetime(2026, 1, 1, 10, 0, 0)  # antérieure à createdAt Seer (29 janv)
    db.add(PlexUser(plex_user_id="alice", seer_user_id=3, enabled=True))
    db.add(
        MediaRequest(
            plex_user_id="alice",
            plex_user="alice",
            title="Inception",
            media_type="movie",
            tmdb_id="27205",
            status=RequestStatus.sent_to_arr,
            requested_at=old_date,
            source="rss",
        )
    )
    db.add(_settings(seer_enabled=True, seer_url="http://seer.local", seer_api_key="key"))
    db.commit()

    with (
        _patch_session(db),
        patch("app.scheduler.seer_get_user_requests", new=AsyncMock(return_value=SEER_REQUEST_WITH_DATE)),
    ):
        await sync_seer_requests()

    req = db.query(MediaRequest).one()
    assert req.requested_at == old_date


@pytest.mark.asyncio
async def test_seer_sync_replaces_newer_rss_date_with_seer(db):
    """Si la date RSS est plus récente que Seer, la date Seer (plus ancienne) est utilisée."""
    newer_date = datetime(2026, 2, 15, 10, 0, 0)  # postérieure au 29 janv Seer
    db.add(PlexUser(plex_user_id="alice", seer_user_id=3, enabled=True))
    db.add(
        MediaRequest(
            plex_user_id="alice",
            plex_user="alice",
            title="Inception",
            media_type="movie",
            tmdb_id="27205",
            status=RequestStatus.sent_to_arr,
            requested_at=newer_date,
            source="rss",
        )
    )
    db.add(_settings(seer_enabled=True, seer_url="http://seer.local", seer_api_key="key"))
    db.commit()

    with (
        _patch_session(db),
        patch("app.scheduler.seer_get_user_requests", new=AsyncMock(return_value=SEER_REQUEST_WITH_DATE)),
    ):
        await sync_seer_requests()

    req = db.query(MediaRequest).one()
    # La date Seer (29 janv) doit remplacer la date RSS (15 fév) car elle est plus ancienne
    assert req.requested_at < newer_date
    assert req.requested_at == datetime(2026, 1, 29, 12, 0, 0)


@pytest.mark.asyncio
async def test_seer_sync_date_preserved_if_no_created_at(db):
    """Si createdAt absent dans la réponse Seer, la date existante est conservée."""
    original_date = datetime(2026, 3, 1, 0, 0, 0)
    db.add(PlexUser(plex_user_id="alice", seer_user_id=3, enabled=True))
    db.add(
        MediaRequest(
            plex_user_id="alice",
            plex_user="alice",
            title="Inception",
            media_type="movie",
            tmdb_id="27205",
            status=RequestStatus.sent_to_arr,
            requested_at=original_date,
            source="rss",
        )
    )
    db.add(_settings(seer_enabled=True, seer_url="http://seer.local", seer_api_key="key"))
    db.commit()

    seer_req_no_date = [{k: v for k, v in SEER_REQUEST_WITH_DATE[0].items() if k != "requested_at"}]

    with (
        _patch_session(db),
        patch("app.scheduler.seer_get_user_requests", new=AsyncMock(return_value=seer_req_no_date)),
    ):
        await sync_seer_requests()

    req = db.query(MediaRequest).one()
    assert req.requested_at == original_date


# ---------------------------------------------------------------------------
# poll_watchlists — pas de recherche Seer si tvdb_id présent
# ---------------------------------------------------------------------------


def _show_item(user="alice", user_id="alice", tvdb_id="81763", tmdb_id=None):
    return dict(
        title="Invincible",
        year=2021,
        media_type="show",
        plex_user=user,
        plex_user_id=user_id,
        tmdb_id=tmdb_id,
        tvdb_id=tvdb_id,
        imdb_id=None,
        plex_guid=None,
        poster_url=None,
        overview="",
        source="rss",
    )


def _seer_settings(**kwargs):
    """Settings avec Seer activé pour les tests poll + Seer Search."""
    return _settings(
        seer_enabled=True,
        seer_url="http://seer.local",
        seer_api_key="key",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_poll_show_with_tvdb_does_not_call_seer_search(db):
    """Une série avec tvdb_id (RSS) ne déclenche pas de recherche Seer."""
    db.add(_seer_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True, seer_user_id=3, seer_active=True))
    db.commit()

    with (
        _patch_session(db),
        _patch_watchlist([_show_item(tvdb_id="81763", tmdb_id=None)]),
        _patch_submit(),
        _patch_enqueue(),
        patch("app.scheduler._seer_resolve_tmdb_id", new=AsyncMock()) as mock_resolve,
    ):
        await poll_watchlists()

    mock_resolve.assert_not_called()


@pytest.mark.asyncio
async def test_poll_show_without_tvdb_calls_seer_search(db):
    """Une série sans tvdb_id NI tmdb_id déclenche la recherche Seer."""
    db.add(_seer_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True, seer_user_id=3, seer_active=True))
    db.commit()

    with (
        _patch_session(db),
        _patch_watchlist([_show_item(tvdb_id=None, tmdb_id=None)]),
        _patch_submit(),
        _patch_enqueue(),
        patch("app.scheduler._seer_resolve_tmdb_id", new=AsyncMock(return_value=None)) as mock_resolve,
    ):
        await poll_watchlists()

    mock_resolve.assert_called_once()


@pytest.mark.asyncio
async def test_poll_show_with_tmdb_does_not_call_seer_search(db):
    """Une série avec tmdb_id direct ne déclenche pas non plus la recherche Seer."""
    db.add(_seer_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True, seer_user_id=3, seer_active=True))
    db.commit()

    with (
        _patch_session(db),
        _patch_watchlist([_show_item(tvdb_id=None, tmdb_id="12345")]),
        _patch_submit(),
        _patch_enqueue(),
        patch("app.scheduler._seer_resolve_tmdb_id", new=AsyncMock()) as mock_resolve,
    ):
        await poll_watchlists()

    mock_resolve.assert_not_called()
