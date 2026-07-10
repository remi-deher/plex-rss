"""Tests unitaires de la fusion d'utilisateurs (_merge_users).

Vérifie que les données des deux comptes sont préservées sur le keeper :
demandeur principal, co-demandeurs (remap + dédoublonnage), jalons de
notification (respect de la contrainte unique), signalements, et consolidation
de profil ; la source est supprimée.
"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, MediaIssue, MediaRequest, NotificationMilestone, PlexUser, RequestStatus
from app.routers.users_api import _merge_users


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _mk_users(db):
    keeper = PlexUser(plex_user_id="admin", display_name="Admin", source="api", role="admin", notification_email=None)
    source = PlexUser(
        plex_user_id="seer42", display_name="Seer42", source="seer",
        seer_user_id=42, seer_active=True, notification_email="seer@example.com",
    )
    db.add_all([keeper, source])
    db.commit()
    return keeper, source


def test_merge_moves_primary_requests_and_deletes_source(db):
    keeper, source = _mk_users(db)
    db.add(MediaRequest(plex_user_id="seer42", plex_user="Seer42", title="Dune", media_type="movie",
                        tmdb_id="1", status=RequestStatus.sent_to_arr))
    db.commit()

    _merge_users(db, source, keeper)
    db.commit()

    reqs = db.query(MediaRequest).all()
    assert len(reqs) == 1
    assert reqs[0].plex_user_id == "admin"
    assert reqs[0].plex_user == "Admin"
    assert db.query(PlexUser).filter(PlexUser.plex_user_id == "seer42").first() is None


def test_merge_remaps_and_dedups_extra_requesters(db):
    keeper, source = _mk_users(db)
    # Demande où keeper est déjà principal et source co-demandeur -> l'entrée source doit disparaître.
    db.add(MediaRequest(plex_user_id="admin", plex_user="Admin", title="A", media_type="movie", tmdb_id="2",
                        status=RequestStatus.sent_to_arr,
                        extra_requesters=json.dumps([{"plex_user_id": "seer42", "display_name": "Seer42"}])))
    # Demande d'un tiers avec source en co-demandeur -> source remappé vers keeper.
    db.add(MediaRequest(plex_user_id="bob", plex_user="Bob", title="B", media_type="movie", tmdb_id="3",
                        status=RequestStatus.sent_to_arr,
                        extra_requesters=json.dumps([{"plex_user_id": "seer42", "display_name": "Seer42"}])))
    db.commit()

    _merge_users(db, source, keeper)
    db.commit()

    a = db.query(MediaRequest).filter(MediaRequest.title == "A").first()
    assert json.loads(a.extra_requesters) == []  # doublon retiré
    b = db.query(MediaRequest).filter(MediaRequest.title == "B").first()
    extras = json.loads(b.extra_requesters)
    assert [e["plex_user_id"] for e in extras] == ["admin"]  # remappé


def test_merge_milestones_respects_unique_constraint(db):
    keeper, source = _mk_users(db)
    # Collision : même (req_id, direction, type, season, episode) pour keeper et source.
    db.add(NotificationMilestone(req_id=1, plex_user_id="admin", direction="vo", milestone_type="season"))
    db.add(NotificationMilestone(req_id=1, plex_user_id="seer42", direction="vo", milestone_type="season"))
    # Non-collision : jalon propre à la source.
    db.add(NotificationMilestone(req_id=2, plex_user_id="seer42", direction="vf", milestone_type="episode"))
    db.commit()

    _merge_users(db, source, keeper)
    db.commit()  # ne doit PAS violer uq_notification_milestone

    admin_ms = db.query(NotificationMilestone).filter(NotificationMilestone.plex_user_id == "admin").all()
    keys = {(m.req_id, m.direction, m.milestone_type) for m in admin_ms}
    assert keys == {(1, "vo", "season"), (2, "vf", "episode")}
    assert db.query(NotificationMilestone).filter(NotificationMilestone.plex_user_id == "seer42").count() == 0


def test_merge_reassigns_issues_and_fills_profile(db):
    keeper, source = _mk_users(db)
    db.add(MediaIssue(issue_type="audio", title="X", media_type="movie", reporter_plex_user_id="seer42"))
    db.commit()

    _merge_users(db, source, keeper)
    db.commit()

    issue = db.query(MediaIssue).first()
    assert issue.reporter_plex_user_id == "admin"
    # Consolidation de profil : le keeper récupère les infos manquantes de la source.
    assert keeper.notification_email == "seer@example.com"
    assert keeper.seer_user_id == 42
    assert keeper.seer_active is True
    # Le keeper reste admin.
    assert keeper.role == "admin"
