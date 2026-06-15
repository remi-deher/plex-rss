"""
Tests pour la synchronisation des utilisateurs Seer-only (passe 4 de sync_seer_users).

Couvre :
- Création d'un PlexUser avec source="seer" pour un utilisateur Seer sans RSS
- Non-création si request_count == 0
- Non-création si déjà matché par les passes 1-3
- Mise à jour des infos (display_name, seer_active) si le user existe déjà
- ID synthétique "seer:{id}" et email correctement renseigné
- poll_watchlists ignore les IDs synthétiques (pas dans les items RSS)
"""

from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, PlexUser, Settings
from app.scheduler import sync_seer_users


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@contextmanager
def _session_from_engine(engine):
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def engine():
    return _make_engine()


@pytest.fixture()
def db(engine):
    with _session_from_engine(engine) as s:
        yield s


def _add_settings(db, **kwargs) -> Settings:
    defaults = dict(
        seer_enabled=True,
        seer_url="http://seer.local",
        seer_api_key="key",
        sonarr_enabled=False,
        radarr_enabled=False,
        email_on_request=False,
        email_on_available=False,
    )
    defaults.update(kwargs)
    s = Settings(**defaults)
    db.add(s)
    db.commit()
    return s


def _seer_users_response(**overrides):
    """Simule la réponse de seer_get_users pour Charlie, utilisateur Seer-only."""
    base = {
        "charlie@example.com": {
            "id": 99,
            "display_name": "Charlie Seer",
            "request_count": 7,
            "plex_username": "charlie_plex",
            "plex_id": None,
            "user_type": 1,
        }
    }
    base.update(overrides)
    return base


def _run_sync_seer_users(db, seer_resp, seer_requests_resp=None):
    """Helper : patch SessionLocal + seer_get_users + seer_get_user_requests puis appelle sync."""
    if seer_requests_resp is None:
        seer_requests_resp = []

    import asyncio

    with (
        patch("app.scheduler.SessionLocal", return_value=db),
        patch("app.scheduler.seer_get_users", new=AsyncMock(return_value=seer_resp)),
        patch("app.scheduler.seer_get_user_requests", new=AsyncMock(return_value=seer_requests_resp)),
    ):
        asyncio.run(sync_seer_users())


# ---------------------------------------------------------------------------
# Passe 4 : création utilisateur Seer-only
# ---------------------------------------------------------------------------


def test_seer_only_user_created(db):
    """Un utilisateur Seer avec des demandes et sans équivalent RSS → PlexUser créé."""
    _add_settings(db)

    _run_sync_seer_users(db, _seer_users_response())

    users = db.query(PlexUser).all()
    assert len(users) == 1
    u = users[0]
    assert u.plex_user_id == "seer:99"
    assert u.source == "seer"
    assert u.seer_user_id == 99
    assert u.seer_active is True
    assert u.display_name == "Charlie Seer"
    assert u.plex_email == "charlie@example.com"
    assert u.enabled is True


def test_seer_only_user_not_created_if_no_requests(db):
    """Un utilisateur Seer avec 0 demandes n'est pas importé."""
    _add_settings(db)
    seer_resp = _seer_users_response()
    seer_resp["charlie@example.com"]["request_count"] = 0

    _run_sync_seer_users(db, seer_resp)

    assert db.query(PlexUser).count() == 0


def test_seer_only_user_not_created_if_already_matched_by_email(db):
    """Si un PlexUser RSS est matché à Seer par email (passe 1), la passe 4 ne crée pas de doublon."""
    _add_settings(db)
    db.add(PlexUser(
        plex_user_id="abc123",
        display_name="charlie_plex",
        plex_email="charlie@example.com",
        enabled=True,
    ))
    db.commit()

    _run_sync_seer_users(db, _seer_users_response())

    users = db.query(PlexUser).all()
    assert len(users) == 1
    assert users[0].plex_user_id == "abc123"
    assert users[0].seer_user_id == 99


def test_seer_only_user_updated_on_resync(db):
    """Un utilisateur Seer-only déjà créé a son display_name mis à jour si changé."""
    _add_settings(db)
    db.add(PlexUser(
        plex_user_id="seer:99",
        display_name="Ancien Nom",
        seer_user_id=99,
        seer_active=True,
        source="seer",
        enabled=True,
    ))
    db.commit()

    updated_resp = _seer_users_response()
    updated_resp["charlie@example.com"]["display_name"] = "Nouveau Nom"

    _run_sync_seer_users(db, updated_resp)

    db.expire_all()
    u = db.query(PlexUser).filter_by(plex_user_id="seer:99").first()
    assert u.display_name == "Nouveau Nom"


def test_seer_only_user_not_duplicated_on_resync(db):
    """Resync ne crée pas de doublon si le user seer:X existe déjà."""
    _add_settings(db)
    db.add(PlexUser(
        plex_user_id="seer:99",
        display_name="Charlie Seer",
        seer_user_id=99,
        seer_active=True,
        source="seer",
        enabled=True,
    ))
    db.commit()

    _run_sync_seer_users(db, _seer_users_response())

    assert db.query(PlexUser).count() == 1


def test_multiple_seer_only_users_all_created(db):
    """Plusieurs utilisateurs Seer-only sont tous créés en une passe."""
    _add_settings(db)
    seer_resp = {
        "charlie@example.com": {"id": 99, "display_name": "Charlie", "request_count": 5, "plex_username": "", "plex_id": None, "user_type": 1},
        "diana@example.com":   {"id": 100, "display_name": "Diana",   "request_count": 3, "plex_username": "", "plex_id": None, "user_type": 1},
    }

    _run_sync_seer_users(db, seer_resp)

    users = db.query(PlexUser).order_by(PlexUser.plex_user_id).all()
    assert len(users) == 2
    ids = {u.plex_user_id for u in users}
    assert ids == {"seer:99", "seer:100"}
    assert all(u.source == "seer" for u in users)


def test_seer_only_and_rss_user_coexist(db):
    """Un user RSS matché + un user Seer-only : le RSS est mis à jour, le Seer-only est créé."""
    _add_settings(db)
    db.add(PlexUser(
        plex_user_id="abc123",
        display_name="alice_plex",
        plex_email="alice@example.com",
        enabled=True,
    ))
    db.commit()

    seer_resp = {
        "alice@example.com": {"id": 1, "display_name": "Alice", "request_count": 4, "plex_username": "alice_plex", "plex_id": 1, "user_type": 2},
        "charlie@example.com": {"id": 99, "display_name": "Charlie", "request_count": 7, "plex_username": "", "plex_id": None, "user_type": 1},
    }

    _run_sync_seer_users(db, seer_resp)

    db.expire_all()
    users = db.query(PlexUser).all()
    assert len(users) == 2

    alice = db.query(PlexUser).filter_by(plex_user_id="abc123").first()
    assert alice.seer_user_id == 1

    charlie = db.query(PlexUser).filter_by(plex_user_id="seer:99").first()
    assert charlie is not None
    assert charlie.source == "seer"


def test_seer_only_seer_active_updated_when_requests_drop_to_zero(db):
    """seer_active passe à False si request_count tombe à 0 lors d'une resync."""
    _add_settings(db)
    db.add(PlexUser(
        plex_user_id="seer:99",
        display_name="Charlie Seer",
        seer_user_id=99,
        seer_active=True,
        source="seer",
        enabled=True,
    ))
    db.commit()

    resp = _seer_users_response()
    resp["charlie@example.com"]["request_count"] = 0

    _run_sync_seer_users(db, resp)

    db.expire_all()
    u = db.query(PlexUser).filter_by(plex_user_id="seer:99").first()
    # request_count == 0 → seer_active doit être False
    assert u.seer_active is False


# ---------------------------------------------------------------------------
# Invariants des utilisateurs Seer-only vis-à-vis du flux RSS
# ---------------------------------------------------------------------------


def test_sync_users_from_feed_does_not_overwrite_seer_source(db):
    """sync_users_from_feed ne doit pas écraser source='seer' sur un PlexUser seer-only."""
    import asyncio
    from app.scheduler import sync_users_from_feed

    db.add(PlexUser(
        plex_user_id="seer:99",
        display_name="Charlie Seer",
        source="seer",
        seer_user_id=99,
        enabled=True,
    ))
    db.commit()

    # Un item RSS ne peut jamais avoir plex_user_id="seer:X" — test de robustesse
    # en passant un item avec un ID réel différent pour confirmer qu'il n'affecte pas seer:99
    rss_items = [{
        "title": "Inception", "year": 2010, "media_type": "movie",
        "plex_user": "real_user", "plex_user_id": "abc123",
        "tmdb_id": "27205", "tvdb_id": None, "imdb_id": None,
        "plex_guid": None, "poster_url": None, "overview": "", "source": "rss",
    }]

    asyncio.run(sync_users_from_feed(rss_items, db))
    db.expire_all()

    seer_user = db.query(PlexUser).filter_by(plex_user_id="seer:99").first()
    assert seer_user is not None
    assert seer_user.source == "seer"


def test_seer_only_user_has_synthetic_id_format(db):
    """L'ID synthétique suit le format 'seer:{seer_user_id}' et est unique."""
    _add_settings(db)
    seer_resp = {
        "a@example.com": {"id": 1, "display_name": "A", "request_count": 1, "plex_username": "", "plex_id": None, "user_type": 1},
        "b@example.com": {"id": 2, "display_name": "B", "request_count": 1, "plex_username": "", "plex_id": None, "user_type": 1},
    }

    _run_sync_seer_users(db, seer_resp)

    ids = {u.plex_user_id for u in db.query(PlexUser).all()}
    assert ids == {"seer:1", "seer:2"}
