"""Effacement RGPD (Art. 17) : supprimer un utilisateur doit purger ses données
personnelles dispersées, pas seulement la ligne PlexUser — sinon la promesse
d'effacement de la page /privacy est mensongère (email conservé dans les journaux,
demandes orphelines, etc.).
"""

import json

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import (
    Base,
    MediaIssue,
    MediaRequest,
    NotificationLog,
    NotificationMilestone,
    PasskeyCredential,
    PlexUser,
    RequestStatus,
)
from app.routers.users_api import BulkDeleteUpdate, bulk_delete_users, delete_user
from app.services.gdpr import erase_user_data, export_user_data
from tests.async_support import TestSession


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = TestSession(sessionmaker(bind=engine, expire_on_commit=False)())
    yield session
    session.close()


async def _count(db, model, condition):
    result = await db.execute(select(func.count()).select_from(model).where(condition))
    return result.scalar()


def _seed_alice_and_bob(db):
    alice = PlexUser(
        plex_user_id="alice",
        display_name="Alice",
        plex_email="alice@example.com",
        notification_email="alice.notif@example.com",
    )
    bob = PlexUser(plex_user_id="bob", display_name="Bob", plex_email="bob@example.com")
    db.add_all([alice, bob])
    db.flush()

    # Données rattachées à Alice, dispersées dans plusieurs tables.
    db.add(MediaRequest(plex_user_id="alice", title="Dune", media_type="movie", status=RequestStatus.available))
    db.add(NotificationMilestone(req_id=1, plex_user_id="alice", direction="vf", milestone_type="available"))
    db.add(NotificationLog(event="available", recipient="alice@example.com", media_title="Dune"))
    db.add(NotificationLog(event="request", recipient="alice.notif@example.com", media_title="Dune"))
    db.add(MediaIssue(reporter_plex_user_id="alice", title="Dune", media_type="movie", issue_type="audio"))
    db.add(PasskeyCredential(user_id=alice.id, credential_id="cred-alice", public_key="k"))

    # Alice est co-demandeuse d'une demande portée par Bob.
    db.add(
        MediaRequest(
            plex_user_id="bob",
            title="Alien",
            media_type="movie",
            status=RequestStatus.pending,
            extra_requesters=json.dumps([{"plex_user_id": "alice", "display_name": "Alice"}]),
        )
    )
    # Données de Bob, qui ne doivent pas être touchées.
    db.add(NotificationLog(event="available", recipient="bob@example.com", media_title="Alien"))
    db.commit()
    return alice, bob


@pytest.mark.asyncio
async def test_erase_user_data_purges_all_personal_tables(db):
    alice, _bob = _seed_alice_and_bob(db)

    counts = await erase_user_data(db, alice)
    db.commit()

    assert counts["requests"] == 1
    assert counts["milestones"] == 1
    assert counts["notification_logs"] == 2  # les deux emails d'Alice
    assert counts["media_issues"] == 1
    assert counts["passkeys"] == 1
    assert counts["co_requester_scrubbed"] == 1

    # Plus aucune trace d'Alice.
    assert await _count(db, MediaRequest, MediaRequest.plex_user_id == "alice") == 0
    assert await _count(db, NotificationMilestone, NotificationMilestone.plex_user_id == "alice") == 0
    assert await _count(db, MediaIssue, MediaIssue.reporter_plex_user_id == "alice") == 0
    assert await _count(db, PasskeyCredential, PasskeyCredential.user_id == alice.id) == 0
    for email in ("alice@example.com", "alice.notif@example.com"):
        assert await _count(db, NotificationLog, NotificationLog.recipient == email) == 0


@pytest.mark.asyncio
async def test_erase_scrubs_co_requester_without_deleting_others_request(db):
    alice, _bob = _seed_alice_and_bob(db)

    await erase_user_data(db, alice)
    db.commit()

    # La demande de Bob existe toujours, mais sans Alice dans extra_requesters.
    bob_req = (await db.execute(select(MediaRequest).where(MediaRequest.plex_user_id == "bob"))).scalars().first()
    assert bob_req is not None
    assert json.loads(bob_req.extra_requesters) == []


@pytest.mark.asyncio
async def test_erase_leaves_other_users_untouched(db):
    alice, _bob = _seed_alice_and_bob(db)

    await erase_user_data(db, alice)
    db.commit()

    assert await _count(db, PlexUser, PlexUser.plex_user_id == "bob") == 1
    assert await _count(db, NotificationLog, NotificationLog.recipient == "bob@example.com") == 1


@pytest.mark.asyncio
async def test_delete_user_endpoint_erases_and_removes_account(db):
    alice, _bob = _seed_alice_and_bob(db)

    result = await delete_user(alice.id, db)

    assert result["status"] == "deleted"
    assert result["erased"]["requests"] == 1
    assert await _count(db, PlexUser, PlexUser.plex_user_id == "alice") == 0


@pytest.mark.asyncio
async def test_export_user_data_returns_only_that_person(db):
    alice, _bob = _seed_alice_and_bob(db)

    payload = await export_user_data(db, alice)

    assert payload["export_type"] == "data_subject_access_request"
    assert payload["subject"]["plex_user_id"] == "alice"
    assert len(payload["requests"]) == 1
    assert payload["requests"][0]["title"] == "Dune"
    assert len(payload["notification_logs"]) == 2  # les deux emails d'Alice, pas ceux de Bob
    assert {log["recipient"] for log in payload["notification_logs"]} == {
        "alice@example.com",
        "alice.notif@example.com",
    }
    assert len(payload["media_issues"]) == 1
    assert len(payload["passkeys"]) == 1


@pytest.mark.asyncio
async def test_export_user_data_excludes_secrets(db):
    alice = PlexUser(
        plex_user_id="alice",
        display_name="Alice",
        plex_email="alice@example.com",
        totp_secret="SUPERSECRET",
        totp_enabled=True,
    )
    db.add(alice)
    db.commit()

    payload = await export_user_data(db, alice)

    # La colonne chiffrée totp_secret ne doit jamais apparaître dans l'export.
    assert "totp_secret" not in payload["subject"]
    assert "totp_enabled" in payload["subject"]  # champ non-secret conservé


@pytest.mark.asyncio
async def test_bulk_delete_erases_personal_data(db):
    alice, _bob = _seed_alice_and_bob(db)

    result = await bulk_delete_users(BulkDeleteUpdate(user_ids=[alice.id]), db)

    assert result["deleted"] == 1
    assert await _count(db, MediaRequest, MediaRequest.plex_user_id == "alice") == 0
    assert await _count(db, PasskeyCredential, PasskeyCredential.user_id == alice.id) == 0
