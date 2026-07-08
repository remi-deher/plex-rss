"""Tests pour le lien MediaRequest <-> LibraryItem (source de vérité VF unique).

Avant ce lien, une demande et un élément de bibliothèque représentant le même média
physique pouvaient avoir un has_vf scanné indépendamment et donc en désaccord (ex:
Bibliothèque affiche VF, Demandes affiche encore VO en attente pour le même titre).
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, LibraryItem, MediaRequest, RequestStatus, Settings
from app.scheduler import _link_request_to_library_item, check_vf_statuses


def _make_db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_link_by_plex_guid():
    db = _make_db()
    li = LibraryItem(title="Dune", year=2021, media_type="movie", plex_guid="plex://movie/abc")
    db.add(li)
    db.commit()

    req = MediaRequest(
        plex_user_id="u1", title="Dune", year=2021, media_type="movie",
        plex_guid="plex://movie/abc", status=RequestStatus.available,
    )
    db.add(req)
    db.commit()

    found = _link_request_to_library_item(db, req)
    assert found is not None
    assert found.id == li.id
    assert req.library_item_id == li.id


def test_link_by_tmdb_id_fallback():
    db = _make_db()
    li = LibraryItem(title="Dune", year=2021, media_type="movie", tmdb_id="438631")
    db.add(li)
    db.commit()

    req = MediaRequest(
        plex_user_id="u1", title="Dune (2021)", year=2021, media_type="movie",
        tmdb_id="438631", status=RequestStatus.available,
    )
    db.add(req)
    db.commit()

    found = _link_request_to_library_item(db, req)
    assert found is not None
    assert found.id == li.id


def test_link_by_title_year_type_fallback():
    db = _make_db()
    li = LibraryItem(title="Arrival", year=2016, media_type="movie")
    db.add(li)
    db.commit()

    req = MediaRequest(
        plex_user_id="u1", title="Arrival", year=2016, media_type="movie",
        status=RequestStatus.available,
    )
    db.add(req)
    db.commit()

    found = _link_request_to_library_item(db, req)
    assert found is not None
    assert found.id == li.id


def test_no_match_returns_none():
    db = _make_db()
    req = MediaRequest(
        plex_user_id="u1", title="Unreleased Movie", year=2099, media_type="movie",
        status=RequestStatus.pending,
    )
    db.add(req)
    db.commit()

    found = _link_request_to_library_item(db, req)
    assert found is None
    assert req.library_item_id is None


def test_orphaned_link_is_relinked():
    db = _make_db()
    li_old = LibraryItem(title="Old", year=2000, media_type="movie")
    db.add(li_old)
    db.commit()
    old_id = li_old.id

    req = MediaRequest(
        plex_user_id="u1", title="New Title", year=2020, media_type="movie",
        status=RequestStatus.available, library_item_id=old_id,
    )
    db.add(req)
    db.commit()
    db.delete(li_old)
    db.commit()

    li_new = LibraryItem(title="New Title", year=2020, media_type="movie")
    db.add(li_new)
    db.commit()

    found = _link_request_to_library_item(db, req)
    assert found is not None
    assert found.id == li_new.id
    assert req.library_item_id == li_new.id


@pytest.mark.asyncio
async def test_check_vf_statuses_propagates_linked_library_item_without_rescanning_request():
    """Une demande liée à un LibraryItem déjà résolu (has_vf=True) doit être mise à jour
    et notifiée SANS déclencher de scan Plex indépendant pour cette demande."""
    db = _make_db()
    settings = Settings(
        id=1, plex_url="http://plex", plex_token="tok", vff_enabled=True,
        vff_libraries='[{"name": "Films", "kind": "movie"}]',
        email_on_vf_available=True,
    )
    db.add(settings)

    li = LibraryItem(title="Dune", year=2021, media_type="movie", plex_guid="plex://movie/abc", has_vf=True)
    db.add(li)
    db.commit()

    req = MediaRequest(
        plex_user_id="u1", title="Dune", year=2021, media_type="movie",
        plex_guid="plex://movie/abc", status=RequestStatus.available,
        has_vf=False,  # suivi VO au passage précédent -> transition attendue vers VF
        library_item_id=li.id,
    )
    db.add(req)
    db.commit()

    with (
        patch("app.services.vff_scanner.SessionLocal", return_value=db),
        patch("app.services.notification_orchestrator.enqueue_notification") as mock_enqueue,
        patch("app.services.vff_scanner._scan_vf_blocking") as mock_scan,
    ):
        await check_vf_statuses()

    # La demande liée doit refléter le has_vf du LibraryItem, sans scan Plex dédié
    # (les deux candidats — demande liée + LibraryItem déjà résolu — n'appellent jamais
    # _scan_vf_blocking puisqu'aucun des deux n'a besoin d'un scan Plex : la demande
    # est liée et le LibraryItem est déjà résolu à has_vf=True).
    mock_scan.assert_not_called()
    assert req.has_vf is True
    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args[0][0] == "vf_available"


@pytest.mark.asyncio
async def test_check_vf_statuses_promotes_stuck_request_via_library_presence():
    """Une demande bloquée en sent_to_arr (arr ne détecte jamais le fichier) doit être
    promue 'available' dès qu'un LibraryItem correspondant existe dans Plex, et suivre
    ensuite le même traitement VF que les demandes déjà disponibles."""
    db = _make_db()
    settings = Settings(
        id=1, plex_url="http://plex", plex_token="tok", vff_enabled=True,
        vff_libraries='[{"name": "Films", "kind": "movie"}]',
    )
    db.add(settings)

    li = LibraryItem(title="Dune", year=2021, media_type="movie", plex_guid="plex://movie/abc", has_vf=True)
    db.add(li)
    db.commit()
    li_id = li.id

    req = MediaRequest(
        plex_user_id="u1", title="Dune", year=2021, media_type="movie",
        plex_guid="plex://movie/abc", status=RequestStatus.sent_to_arr,
    )
    db.add(req)
    db.commit()

    with (
        patch("app.services.vff_scanner.SessionLocal", return_value=db),
        patch("app.services.notification_orchestrator.enqueue_notification"),
        patch("app.services.vff_scanner._scan_vf_blocking") as mock_scan,
    ):
        await check_vf_statuses()

    assert req.status == RequestStatus.available
    assert req.available_at is not None
    assert req.library_item_id == li_id
    assert req.has_vf is True
    mock_scan.assert_not_called()
