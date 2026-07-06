"""Tests unitaires pour app/scheduler.py — poll_watchlists et check_arr_statuses."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, MediaRequest, PlexUser, RequestStatus, Settings
from app.scheduler import check_arr_statuses, poll_watchlists, sync_users_from_feed

# ---------------------------------------------------------------------------
# Fixtures DB in-memory
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
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
        email_on_request=True,
        email_on_available=True,
        smtp_from="admin@example.com",
        admin_notification_email=None,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _movie_item(**kwargs) -> dict:
    defaults = dict(
        title="Inception",
        year=2010,
        media_type="movie",
        plex_user="alice",
        plex_user_id="alice",
        tmdb_id="27205",
        tvdb_id=None,
        imdb_id="tt1375666",
        plex_guid="plex://movie/abc",
        poster_url=None,
        overview="",
        source="api",
    )
    defaults.update(kwargs)
    return defaults


def _show_item(**kwargs) -> dict:
    defaults = dict(
        title="Breaking Bad",
        year=2008,
        media_type="show",
        plex_user="alice",
        plex_user_id="alice",
        tmdb_id=None,
        tvdb_id="81189",
        imdb_id=None,
        plex_guid="plex://show/xyz",
        poster_url=None,
        overview="",
        source="api",
    )
    defaults.update(kwargs)
    return defaults


# ---------------------------------------------------------------------------
# Helpers de patch
# ---------------------------------------------------------------------------


def _patch_session(db):
    """Remplace SessionLocal par une factory retournant la session de test."""
    return patch("app.scheduler.SessionLocal", return_value=db)


def _patch_watchlist(items):
    return patch("app.scheduler.fetch_watchlist", new=AsyncMock(return_value=items))


def _patch_submit(arr_id=42, already_existed=False, arr_slug="inception"):
    return patch(
        "app.scheduler._submit_to_arr",
        new=AsyncMock(return_value=(arr_id, already_existed, arr_slug)),
    )


def _patch_enqueue():
    return patch("app.scheduler.enqueue_notification")


# ---------------------------------------------------------------------------
# poll_watchlists — cas nominaux
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_new_item_creates_request_and_notifies(db):
    """Nouvel item → MediaRequest créé avec status sent_to_arr, notification enqueued."""
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.commit()

    with _patch_session(db), _patch_watchlist([_movie_item()]), _patch_submit(), _patch_enqueue() as mock_enqueue:
        await poll_watchlists()

    req = db.query(MediaRequest).first()
    assert req is not None
    assert req.title == "Inception"
    assert req.status == RequestStatus.sent_to_arr
    assert req.arr_id == 42
    mock_enqueue.assert_called_once()
    event = mock_enqueue.call_args[0][0]
    assert event == "request"


@pytest.mark.asyncio
async def test_poll_existing_sent_to_arr_is_skipped(db):
    """Item déjà sent_to_arr → pas de doublon, pas de notification."""
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    existing = MediaRequest(
        plex_user_id="alice",
        plex_user="alice",
        title="Inception",
        media_type="movie",
        status=RequestStatus.sent_to_arr,
    )
    db.add(existing)
    db.commit()

    with (
        _patch_session(db),
        _patch_watchlist([_movie_item()]),
        _patch_submit() as mock_submit,
        _patch_enqueue() as mock_enqueue,
    ):
        await poll_watchlists()

    mock_submit.assert_not_called()
    mock_enqueue.assert_not_called()
    assert db.query(MediaRequest).count() == 1


@pytest.mark.asyncio
async def test_poll_failed_request_is_retried(db):
    """Item en statut failed → retenté et passé à sent_to_arr."""
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.add(
        MediaRequest(
            plex_user_id="alice",
            plex_user="alice",
            title="Inception",
            media_type="movie",
            status=RequestStatus.failed,
        )
    )
    db.commit()

    with _patch_session(db), _patch_watchlist([_movie_item()]), _patch_submit(), _patch_enqueue():
        await poll_watchlists()

    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.sent_to_arr
    assert db.query(MediaRequest).count() == 1  # pas de doublon


@pytest.mark.asyncio
async def test_poll_arr_error_sets_failed_and_notifies_failure(db):
    """Échec de _submit_to_arr → status failed, notification d'échec."""
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.commit()

    with (
        _patch_session(db),
        _patch_watchlist([_movie_item()]),
        patch("app.scheduler._submit_to_arr", new=AsyncMock(side_effect=Exception("timeout"))),
        _patch_enqueue() as mock_enqueue,
    ):
        await poll_watchlists()

    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.failed
    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args[0][0] == "failed"


@pytest.mark.asyncio
async def test_poll_already_existed_skips_notification(db):
    """already_existed=True → status sent_to_arr mais aucune notification."""
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.commit()

    with (
        _patch_session(db),
        _patch_watchlist([_movie_item()]),
        _patch_submit(already_existed=True),
        _patch_enqueue() as mock_enqueue,
    ):
        await poll_watchlists()

    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.sent_to_arr
    mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_poll_disabled_user_is_skipped(db):
    """Utilisateur désactivé → son item est ignoré."""
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=False))
    db.commit()

    with _patch_session(db), _patch_watchlist([_movie_item()]), _patch_submit() as mock_submit:
        await poll_watchlists()

    mock_submit.assert_not_called()
    assert db.query(MediaRequest).count() == 0


@pytest.mark.asyncio
async def test_poll_no_settings_returns_early(db):
    """Aucun Settings en DB → retour immédiat sans crash."""
    with _patch_session(db), _patch_watchlist([_movie_item()]) as mock_fetch:
        await poll_watchlists()

    mock_fetch.assert_not_called()  # fetch_watchlist appelé seulement après settings check


@pytest.mark.asyncio
async def test_poll_empty_watchlist_returns_early(db):
    """Watchlist vide → aucune demande créée."""
    db.add(_settings())
    db.commit()

    with _patch_session(db), _patch_watchlist([]), _patch_submit() as mock_submit:
        await poll_watchlists()

    mock_submit.assert_not_called()
    assert db.query(MediaRequest).count() == 0


@pytest.mark.asyncio
async def test_poll_show_item_routes_to_sonarr(db):
    """Item de type show → _submit_to_arr appelé (vérification du type)."""
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.commit()

    with _patch_session(db), _patch_watchlist([_show_item()]), _patch_submit() as mock_submit, _patch_enqueue():
        await poll_watchlists()

    mock_submit.assert_called_once()
    _, item_arg, _user = mock_submit.call_args[0]
    assert item_arg["media_type"] == "show"

    req = db.query(MediaRequest).first()
    assert req.media_type == "show"
    assert req.status == RequestStatus.sent_to_arr


# ---------------------------------------------------------------------------
# check_arr_statuses — cas nominaux
# ---------------------------------------------------------------------------


def _sent_request(**kwargs) -> MediaRequest:
    defaults = dict(
        plex_user_id="alice",
        plex_user="alice",
        title="Inception",
        media_type="movie",
        status=RequestStatus.sent_to_arr,
        arr_id=42,
        tmdb_id="27205",
        available_mail_sent=False,
    )
    defaults.update(kwargs)
    return MediaRequest(**defaults)


@pytest.mark.asyncio
async def test_check_arr_movie_becomes_available(db):
    """is_movie_available → True : statut passe à available, notification enqueued."""
    db.add(_settings())
    db.add(_sent_request())
    db.commit()

    with (
        _patch_session(db),
        patch("app.scheduler.is_movie_available", new=AsyncMock(return_value=(True, 42, None))),
        _patch_enqueue() as mock_enqueue,
    ):
        await check_arr_statuses()

    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.available
    assert req.available_at is not None
    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args[0][0] == "available"


@pytest.mark.asyncio
async def test_check_arr_movie_not_yet_available(db):
    """is_movie_available → False : statut reste sent_to_arr."""
    db.add(_settings())
    db.add(_sent_request())
    db.commit()

    with (
        _patch_session(db),
        patch("app.scheduler.is_movie_available", new=AsyncMock(return_value=(False, None, None))),
        _patch_enqueue() as mock_enqueue,
    ):
        await check_arr_statuses()

    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.sent_to_arr
    mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_check_arr_show_becomes_available(db):
    """get_series_episode_stats → série complète : statut passe à available."""
    db.add(_settings())
    db.add(_sent_request(title="Breaking Bad", media_type="show", tvdb_id="81189"))
    db.commit()

    series_stats = {
        "arr_id": 7, "title_slug": None,
        "episode_file_count": 5, "episode_count": 5, "total_episode_count": 5,
    }
    with (
        _patch_session(db),
        patch("app.scheduler.get_series_episode_stats", new=AsyncMock(return_value=series_stats)),
        _patch_enqueue() as mock_enqueue,
    ):
        await check_arr_statuses()

    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.available
    assert req.episodes_available_count == 5
    assert req.episodes_total_count == 5
    mock_enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_check_arr_no_candidates_returns_early(db):
    """Aucune demande sent_to_arr → aucun check effectué."""
    db.add(_settings())
    db.add(
        MediaRequest(
            plex_user_id="alice", plex_user="alice", title="X", media_type="movie", status=RequestStatus.available
        )
    )
    db.commit()

    with _patch_session(db), patch("app.scheduler.is_movie_available", new=AsyncMock()) as mock_check:
        await check_arr_statuses()

    mock_check.assert_not_called()


@pytest.mark.asyncio
async def test_check_arr_seer_used_when_enabled(db):
    """Seer activé → seer_available utilisé à la place de is_movie_available."""
    s = _settings(seer_enabled=True, seer_url="http://seer.local", seer_api_key="key")
    db.add(s)
    db.add(_sent_request())
    db.commit()

    with (
        _patch_session(db),
        patch("app.scheduler.seer_available", new=AsyncMock(return_value=(True, 42, None))) as mock_seer,
        patch("app.scheduler.is_movie_available", new=AsyncMock()) as mock_radarr,
        _patch_enqueue(),
    ):
        await check_arr_statuses()

    mock_seer.assert_called_once()
    mock_radarr.assert_not_called()


@pytest.mark.asyncio
async def test_check_arr_seer_unavailable_falls_back_to_radarr(db):
    """Seer dit non dispo → fallback direct sur Radarr qui dit dispo."""
    s = _settings(seer_enabled=True, seer_url="http://seer.local", seer_api_key="key")
    db.add(s)
    db.add(_sent_request())
    db.commit()

    with (
        _patch_session(db),
        patch("app.scheduler.seer_available", new=AsyncMock(return_value=(False, None, None))),
        patch("app.scheduler.is_movie_available", new=AsyncMock(return_value=(True, 99, "inception"))) as mock_radarr,
        _patch_enqueue() as mock_enqueue,
    ):
        await check_arr_statuses()

    mock_radarr.assert_called_once()
    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.available
    assert req.arr_slug == "inception"
    mock_enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_check_arr_seer_unavailable_falls_back_to_sonarr(db):
    """Seer dit non dispo → fallback direct sur Sonarr qui dit dispo."""
    s = _settings(seer_enabled=True, seer_url="http://seer.local", seer_api_key="key")
    db.add(s)
    db.add(_sent_request(title="Breaking Bad", media_type="show", tvdb_id="81189"))
    db.commit()

    series_stats = {
        "arr_id": 7, "title_slug": None,
        "episode_file_count": 5, "episode_count": 5, "total_episode_count": 5,
    }
    with (
        _patch_session(db),
        patch("app.scheduler.seer_available", new=AsyncMock(return_value=(False, None, None))),
        patch("app.scheduler.get_series_episode_stats", new=AsyncMock(return_value=series_stats)) as mock_sonarr,
        _patch_enqueue() as mock_enqueue,
    ):
        await check_arr_statuses()

    mock_sonarr.assert_called_once()
    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.available
    mock_enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_check_arr_seer_unavailable_radarr_also_unavailable(db):
    """Seer et Radarr disent tous les deux non dispo → reste sent_to_arr."""
    s = _settings(seer_enabled=True, seer_url="http://seer.local", seer_api_key="key")
    db.add(s)
    db.add(_sent_request())
    db.commit()

    with (
        _patch_session(db),
        patch("app.scheduler.seer_available", new=AsyncMock(return_value=(False, None, None))),
        patch("app.scheduler.is_movie_available", new=AsyncMock(return_value=(False, None, None))) as mock_radarr,
        _patch_enqueue() as mock_enqueue,
    ):
        await check_arr_statuses()

    mock_radarr.assert_called_once()
    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.sent_to_arr
    mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_check_arr_exception_does_not_crash_loop(db):
    """Exception sur un item → les autres items continuent d'être traités."""
    db.add(_settings())
    db.add(_sent_request(title="Movie A", arr_id=1, tmdb_id="111"))
    db.add(_sent_request(title="Movie B", arr_id=2, tmdb_id="222"))
    db.commit()

    call_count = 0

    async def flaky(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("network error")
        return (True, 2, None)

    with (
        _patch_session(db),
        patch("app.scheduler.is_movie_available", new=AsyncMock(side_effect=flaky)),
        _patch_enqueue(),
    ):
        await check_arr_statuses()

    statuses = {r.title: r.status for r in db.query(MediaRequest).all()}
    # Le second item est passé à available malgré l'échec du premier
    assert statuses["Movie B"] == RequestStatus.available


# ---------------------------------------------------------------------------
# sync_users_from_feed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_users_creates_unknown_user(db):
    """Utilisateur inconnu dans le flux → PlexUser auto-créé avec enabled=True."""
    items = [{"plex_user_id": "bob", "title": "X", "media_type": "movie"}]
    await sync_users_from_feed(items, db)

    user = db.query(PlexUser).filter(PlexUser.plex_user_id == "bob").first()
    assert user is not None
    assert user.enabled is True


@pytest.mark.asyncio
async def test_sync_users_does_not_duplicate(db):
    """Utilisateur déjà connu → pas de doublon."""
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.commit()

    items = [{"plex_user_id": "alice", "title": "X", "media_type": "movie"}]
    await sync_users_from_feed(items, db)

    assert db.query(PlexUser).count() == 1
