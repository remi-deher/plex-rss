"""
Tests unitaires pour la déduplication des demandes.

Couvre :
- _find_global_request / _add_co_requester (helpers)
- poll_watchlists : fusion multi-utilisateurs
- sync_seer_requests : dédup RSS↔Seer, co-demandeurs
- merge_duplicates (script de migration)
"""

import json
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, LibraryItem, MediaRequest, PlexUser, RequestStatus, Settings
from app.scheduler import (
    _add_co_requester,
    _find_global_request,
    poll_watchlists,
    sync_seer_requests,
)
from tests.async_support import TestSession

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
    session = TestSession(Session())
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
        # plex_url/plex_token configurés par défaut : has_plex_proof() bypasse en True
        # (proof considérée acquise) si l'un des deux est absent — ce qui rendrait les
        # tests de disponibilité muets. Voir _unmatched_library_item ci-dessous.
        plex_url="http://plex.local",
        plex_token="plex-token",
        email_on_request=False,
        email_on_available=False,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _unmatched_library_item(**kwargs) -> LibraryItem:
    """LibraryItem qui ne correspond à aucune des demandes de test ci-dessous.

    Force has_plex_proof() à effectuer une vraie recherche de correspondance
    (count(LibraryItem) > 0) sans jamais matcher.
    """
    defaults = dict(
        title="Some Other Movie",
        year=1999,
        media_type="movie",
        tmdb_id="999999",
        tvdb_id=None,
        imdb_id=None,
        plex_guid="plex://movie/unrelated",
        poster_url=None,
        overview="",
        added_at=None,
        arr_instance_id=None,
        arr_id=None,
        arr_slug=None,
    )
    defaults.update(kwargs)
    return LibraryItem(**defaults)


def _req(
    plex_user_id="alice",
    title="Inception",
    media_type="movie",
    tmdb_id="27205",
    status=RequestStatus.sent_to_arr,
    **kwargs,
) -> MediaRequest:
    return MediaRequest(
        plex_user_id=plex_user_id,
        plex_user=plex_user_id,
        title=title,
        media_type=media_type,
        tmdb_id=tmdb_id,
        status=status,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# _find_global_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_global_request_by_tmdb_id(db):
    """Trouve une demande existante par tmdb_id (tous utilisateurs)."""
    db.add(_req(plex_user_id="alice", tmdb_id="27205"))
    db.commit()

    result = await _find_global_request(db, "movie", "27205", "Inception")
    assert result is not None
    assert result.plex_user_id == "alice"


@pytest.mark.asyncio
async def test_find_global_request_by_title_fallback(db):
    """Sans tmdb_id, fallback sur le titre."""
    db.add(_req(plex_user_id="alice", tmdb_id=None, title="Inception"))
    db.commit()

    result = await _find_global_request(db, "movie", None, "Inception")
    assert result is not None


@pytest.mark.asyncio
async def test_find_global_request_not_found(db):
    """Aucune demande correspondante → None."""
    result = await _find_global_request(db, "movie", "99999", "Inconnu")
    assert result is None


@pytest.mark.asyncio
async def test_find_global_request_tmdb_takes_priority(db):
    """Si tmdb_id fourni, cherche par tmdb même si le titre diffère."""
    db.add(_req(plex_user_id="alice", tmdb_id="27205", title="Inception (2010)"))
    db.commit()

    result = await _find_global_request(db, "movie", "27205", "Titre différent")
    assert result is not None


# ---------------------------------------------------------------------------
# _add_co_requester
# ---------------------------------------------------------------------------


def test_add_co_requester_adds_new(db):
    """Ajoute un co-demandeur absent."""
    req = _req(plex_user_id="alice")
    db.add(req)
    db.commit()

    added = _add_co_requester(req, "bob", "Bob")
    assert added is True
    extras = json.loads(req.extra_requesters)
    assert len(extras) == 1
    assert extras[0]["plex_user_id"] == "bob"
    assert extras[0]["display_name"] == "Bob"


def test_add_co_requester_skips_primary(db):
    """N'ajoute pas le demandeur principal comme co-demandeur."""
    req = _req(plex_user_id="alice")
    db.add(req)
    db.commit()

    added = _add_co_requester(req, "alice", "Alice")
    assert added is False
    assert req.extra_requesters is None


def test_add_co_requester_skips_duplicate(db):
    """N'ajoute pas deux fois le même co-demandeur."""
    req = _req(plex_user_id="alice", extra_requesters='[{"plex_user_id":"bob","display_name":"Bob"}]')
    db.add(req)
    db.commit()

    added = _add_co_requester(req, "bob", "Bob")
    assert added is False
    extras = json.loads(req.extra_requesters)
    assert len(extras) == 1


def test_add_co_requester_multiple(db):
    """Accumule plusieurs co-demandeurs distincts."""
    req = _req(plex_user_id="alice")
    db.add(req)
    db.commit()

    _add_co_requester(req, "bob", "Bob")
    _add_co_requester(req, "charlie", "Charlie")
    extras = json.loads(req.extra_requesters)
    assert len(extras) == 2
    ids = {e["plex_user_id"] for e in extras}
    assert ids == {"bob", "charlie"}


# ---------------------------------------------------------------------------
# poll_watchlists — dédup multi-utilisateurs
# ---------------------------------------------------------------------------


@contextmanager
def _patch_session(db):
    with (
        patch("app.services.watchlist_poller.AsyncSessionLocal", return_value=db),
        patch("app.services.seer_sync.AsyncSessionLocal", return_value=db),
    ):
        yield


def _patch_watchlist(items):
    return patch("app.services.watchlist_poller.fetch_watchlist", new=AsyncMock(return_value=items))


def _patch_submit(arr_id=42, existed=False, slug=None):
    return patch("app.services.watchlist_poller._submit_to_arr", new=AsyncMock(return_value=(arr_id, existed, slug)))


def _patch_enqueue():
    return patch("app.services.notification_orchestrator.enqueue", new_callable=AsyncMock)


def _movie_item(user="alice", user_id="alice", tmdb_id="27205"):
    return dict(
        title="Inception",
        year=2010,
        media_type="movie",
        plex_user=user,
        plex_user_id=user_id,
        tmdb_id=tmdb_id,
        tvdb_id=None,
        imdb_id=None,
        plex_guid=None,
        poster_url=None,
        overview="",
        source="rss",
    )


@pytest.mark.asyncio
async def test_poll_two_users_same_movie_no_duplicate(db):
    """Deux utilisateurs demandent le même film → une seule ligne, bob en co-demandeur."""
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.add(PlexUser(plex_user_id="bob", enabled=True))
    db.commit()

    items = [
        _movie_item(user="alice", user_id="alice"),
        _movie_item(user="bob", user_id="bob"),
    ]

    with _patch_session(db), _patch_watchlist(items), _patch_submit(), _patch_enqueue():
        await poll_watchlists()

    rows = db.query(MediaRequest).all()
    assert len(rows) == 1
    assert rows[0].plex_user_id == "alice"
    extras = json.loads(rows[0].extra_requesters or "[]")
    assert any(e["plex_user_id"] == "bob" for e in extras)


@pytest.mark.asyncio
async def test_poll_same_user_same_movie_no_duplicate(db):
    """Même utilisateur, même film deux fois → une seule ligne."""
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.commit()

    items = [_movie_item(), _movie_item()]

    with _patch_session(db), _patch_watchlist(items), _patch_submit(), _patch_enqueue():
        await poll_watchlists()

    rows = db.query(MediaRequest).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_poll_different_movies_both_created(db):
    """Films différents → deux lignes distinctes."""
    db.add(_settings())
    db.add(PlexUser(plex_user_id="alice", enabled=True))
    db.commit()

    items = [
        _movie_item(tmdb_id="27205"),
        {**_movie_item(tmdb_id="11"), "title": "Star Wars"},
    ]

    with _patch_session(db), _patch_watchlist(items), _patch_submit(), _patch_enqueue():
        await poll_watchlists()

    rows = db.query(MediaRequest).all()
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# sync_seer_requests — dédup RSS↔Seer et enrichissement
# ---------------------------------------------------------------------------


SEER_REQUESTS = [
    {
        "seer_request_id": 7,
        "media_type": "movie",
        "tmdb_id": "27205",
        "tvdb_id": None,
        "imdb_id": None,
        "title": "Inception",
        "overview": "Un voleur de rêves.",
        "status": "sent_to_arr",
        "poster_url": "https://image.tmdb.org/t/p/w200/poster.jpg",
    }
]


@pytest.mark.asyncio
async def test_seer_sync_updates_placeholder_title(db):
    """Une demande [Seer #7] existante est corrigée avec le vrai titre."""
    db.add(PlexUser(plex_user_id="alice", seer_user_id=3, enabled=True))
    db.add(_req(plex_user_id="alice", title="[Seer #7]", tmdb_id="27205"))
    db.commit()

    settings = _settings(seer_enabled=True, seer_url="http://seer.local", seer_api_key="key")
    db.add(settings)
    db.commit()

    with (
        _patch_session(db),
        patch("app.services.seer_sync.seer_get_user_requests", new=AsyncMock(return_value=SEER_REQUESTS)),
    ):
        await sync_seer_requests()

    req = db.query(MediaRequest).first()
    assert req.title == "Inception"
    assert req.poster_url is not None
    assert req.overview == "Un voleur de rêves."


@pytest.mark.asyncio
async def test_seer_sync_no_duplicate_when_rss_exists(db):
    """Demande RSS déjà en base → sync Seer ne crée pas de doublon."""
    alice = PlexUser(plex_user_id="alice", seer_user_id=3, enabled=True)
    db.add(alice)
    # Demande venue du RSS
    db.add(_req(plex_user_id="alice", title="Inception", tmdb_id="27205", source="rss"))
    settings = _settings(seer_enabled=True, seer_url="http://seer.local", seer_api_key="key")
    db.add(settings)
    db.commit()

    with (
        _patch_session(db),
        patch("app.services.seer_sync.seer_get_user_requests", new=AsyncMock(return_value=SEER_REQUESTS)),
    ):
        await sync_seer_requests()

    rows = db.query(MediaRequest).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_seer_sync_adds_co_requester_for_other_user(db):
    """Bob a déjà demandé via RSS, Alice a le même film sur Seer → Alice ajoutée en co-demandeur."""
    bob = PlexUser(plex_user_id="bob", enabled=True)
    alice = PlexUser(plex_user_id="alice", seer_user_id=3, enabled=True, display_name="Alice")
    db.add(bob)
    db.add(alice)
    # Demande existante appartient à Bob
    db.add(_req(plex_user_id="bob", title="Inception", tmdb_id="27205", source="rss"))
    settings = _settings(seer_enabled=True, seer_url="http://seer.local", seer_api_key="key")
    db.add(settings)
    db.commit()

    with (
        _patch_session(db),
        patch("app.services.seer_sync.seer_get_user_requests", new=AsyncMock(return_value=SEER_REQUESTS)),
    ):
        await sync_seer_requests()

    rows = db.query(MediaRequest).all()
    assert len(rows) == 1
    assert rows[0].plex_user_id == "bob"
    extras = json.loads(rows[0].extra_requesters or "[]")
    assert any(e["plex_user_id"] == "alice" for e in extras)


@pytest.mark.asyncio
async def test_seer_sync_status_updated_to_available(db):
    """sync_seer_requests met à jour le statut vers available si Seer indique disponible."""
    alice = PlexUser(plex_user_id="alice", seer_user_id=3, enabled=True)
    db.add(alice)
    db.add(_req(plex_user_id="alice", tmdb_id="27205", status=RequestStatus.sent_to_arr))
    db.add(_unmatched_library_item())
    settings = _settings(seer_enabled=True, seer_url="http://seer.local", seer_api_key="key")
    db.add(settings)
    db.commit()

    available_req = [{**SEER_REQUESTS[0], "status": "available"}]

    with (
        _patch_session(db),
        patch("app.services.seer_sync.seer_get_user_requests", new=AsyncMock(return_value=available_req)),
    ):
        await sync_seer_requests()

    req = db.query(MediaRequest).first()
    assert req.status == RequestStatus.sent_to_arr


@pytest.mark.asyncio
async def test_seer_sync_status_updated_to_available_when_plex_confirms(db):
    """Seer available + Plex library match marks the request available."""
    alice = PlexUser(plex_user_id="alice", seer_user_id=3, enabled=True)
    db.add(alice)
    db.add(_req(plex_user_id="alice", tmdb_id="27205", status=RequestStatus.sent_to_arr))
    db.add(
        LibraryItem(
            title="Inception",
            year=None,
            media_type="movie",
            tmdb_id="27205",
            tvdb_id=None,
            imdb_id=None,
            plex_guid="plex://movie/inception",
            poster_url=None,
            overview="",
            added_at=None,
            arr_instance_id=None,
            arr_id=None,
            arr_slug=None,
        )
    )
    settings = _settings(seer_enabled=True, seer_url="http://seer.local", seer_api_key="key")
    db.add(settings)
    db.commit()

    available_req = [{**SEER_REQUESTS[0], "status": "available"}]

    with (
        _patch_session(db),
        patch("app.services.seer_sync.seer_get_user_requests", new=AsyncMock(return_value=available_req)),
    ):
        await sync_seer_requests()

    req = db.query(MediaRequest).filter(MediaRequest.title == "Inception").first()
    assert req.status == RequestStatus.available
    assert req.library_item_id is not None


# ---------------------------------------------------------------------------
# merge_duplicates (script de migration)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_duplicates_fuses_two_users(db):
    """Deux lignes même tmdb_id, utilisateurs différents → fusion en une seule."""
    from scripts.merge_duplicate_requests import merge_duplicates

    db.add(_req(plex_user_id="alice", title="Inception", tmdb_id="27205"))
    db.add(_req(plex_user_id="bob", title="Inception", tmdb_id="27205"))
    db.commit()

    with patch("scripts.merge_duplicate_requests.AsyncSessionLocal", return_value=db):
        await merge_duplicates(dry_run=False)

    rows = db.query(MediaRequest).all()
    assert len(rows) == 1
    extras = json.loads(rows[0].extra_requesters or "[]")
    assert any(e["plex_user_id"] == "bob" for e in extras)


@pytest.mark.asyncio
async def test_merge_duplicates_dry_run_no_change(db):
    """Mode dry-run → aucune modification en base."""
    from scripts.merge_duplicate_requests import merge_duplicates

    db.add(_req(plex_user_id="alice", title="Inception", tmdb_id="27205"))
    db.add(_req(plex_user_id="bob", title="Inception", tmdb_id="27205"))
    db.commit()

    with patch("scripts.merge_duplicate_requests.AsyncSessionLocal", return_value=db):
        await merge_duplicates(dry_run=True)

    rows = db.query(MediaRequest).all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_merge_duplicates_no_duplicates(db):
    """Sans doublons → aucune modification."""
    from scripts.merge_duplicate_requests import merge_duplicates

    db.add(_req(plex_user_id="alice", tmdb_id="27205"))
    db.add(_req(plex_user_id="alice", title="Dune", tmdb_id="438631"))
    db.commit()

    with patch("scripts.merge_duplicate_requests.AsyncSessionLocal", return_value=db):
        await merge_duplicates(dry_run=False)

    assert db.query(MediaRequest).count() == 2


@pytest.mark.asyncio
async def test_merge_duplicates_keeps_best_status(db):
    """La ligne fusionnée conserve le meilleur statut (available > sent_to_arr)."""
    from scripts.merge_duplicate_requests import merge_duplicates

    db.add(_req(plex_user_id="alice", tmdb_id="27205", status=RequestStatus.sent_to_arr))
    db.add(_req(plex_user_id="bob", tmdb_id="27205", status=RequestStatus.available))
    db.commit()

    with patch("scripts.merge_duplicate_requests.AsyncSessionLocal", return_value=db):
        await merge_duplicates(dry_run=False)

    row = db.query(MediaRequest).one()
    assert row.status == RequestStatus.available


@pytest.mark.asyncio
async def test_merge_duplicates_enriches_missing_poster(db):
    """La fusion copie le poster_url depuis un doublon si le primaire n'en a pas."""
    from scripts.merge_duplicate_requests import merge_duplicates

    db.add(_req(plex_user_id="alice", tmdb_id="27205", poster_url=None))
    db.add(_req(plex_user_id="bob", tmdb_id="27205", poster_url="https://img/poster.jpg"))
    db.commit()

    with patch("scripts.merge_duplicate_requests.AsyncSessionLocal", return_value=db):
        await merge_duplicates(dry_run=False)

    row = db.query(MediaRequest).one()
    assert row.poster_url == "https://img/poster.jpg"


@pytest.mark.asyncio
async def test_merge_duplicates_fixes_placeholder_title(db):
    """Le placeholder [Seer #N] est remplacé par le vrai titre du doublon."""
    from scripts.merge_duplicate_requests import merge_duplicates

    db.add(_req(plex_user_id="alice", tmdb_id="27205", title="[Seer #7]"))
    db.add(_req(plex_user_id="bob", tmdb_id="27205", title="Inception"))
    db.commit()

    with patch("scripts.merge_duplicate_requests.AsyncSessionLocal", return_value=db):
        await merge_duplicates(dry_run=False)

    row = db.query(MediaRequest).one()
    assert row.title == "Inception"


@pytest.mark.asyncio
async def test_merge_duplicates_ignores_no_tmdb(db):
    """Les demandes sans tmdb_id ne sont pas fusionnées (risque faux positif)."""
    from scripts.merge_duplicate_requests import merge_duplicates

    db.add(_req(plex_user_id="alice", tmdb_id=None, title="Film sans ID"))
    db.add(_req(plex_user_id="bob", tmdb_id=None, title="Film sans ID"))
    db.commit()

    with patch("scripts.merge_duplicate_requests.AsyncSessionLocal", return_value=db):
        await merge_duplicates(dry_run=False)

    assert db.query(MediaRequest).count() == 2
