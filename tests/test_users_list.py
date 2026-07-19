"""GET /api/users doit renvoyer le nombre de demandes par utilisateur (colonne
"Demandes" de l'UI) — régression : l'endpoint renvoyait les PlexUser bruts sans
aucune stat, la colonne affichait toujours "-".
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, MediaRequest, PlexUser, RequestStatus
from app.routers.users_api import list_users
from tests.async_support import TestSession


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = TestSession(sessionmaker(bind=engine)())
    yield session
    session.close()


@pytest.mark.asyncio
async def test_list_users_includes_request_count(db):
    alice = PlexUser(plex_user_id="alice", display_name="Alice")
    bob = PlexUser(plex_user_id="bob", display_name="Bob")
    db.add_all([alice, bob])
    db.add(MediaRequest(plex_user_id="alice", title="Dune", media_type="movie", status=RequestStatus.available))
    db.add(MediaRequest(plex_user_id="alice", title="Alien", media_type="movie", status=RequestStatus.pending))
    db.commit()

    result = await list_users(db)
    by_id = {u["plex_user_id"]: u for u in result}

    assert by_id["alice"]["stats"]["total"] == 2
    assert by_id["bob"]["stats"]["total"] == 0
