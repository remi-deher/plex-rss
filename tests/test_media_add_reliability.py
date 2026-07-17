"""Régression : la création de MediaRequest sans tmdb_id/tvdb_id ne doit jamais crasher.

Couvre le bug où `_create_pending_request` et la déduplication de `/media/add`
appelaient `.first()` directement sur un `select()` non exécuté (AttributeError),
faisant perdre le suivi local d'une demande alors même que l'ajout à Radarr/Sonarr/
Seer avait déjà réussi.
"""

import pytest

from app.routers.library_api import MediaAddRequest, _create_pending_request, _needs_approval
from app.services import deleted_media
from tests.async_support import make_test_session


@pytest.mark.asyncio
async def test_create_pending_request_without_ids_does_not_crash():
    db = make_test_session()
    try:
        body = MediaAddRequest(
            title="Film Sans Identifiant",
            media_type="movie",
            plex_user_id="user1",
        )
        result = await _create_pending_request(db, body)
        assert result["ok"] is True
        assert result["already_existed"] is False

        # Une seconde demande pour le même titre doit être déduplifiée, pas planter.
        result2 = await _create_pending_request(db, body)
        assert result2["already_existed"] is True
        assert result2["id"] == result["id"]
    finally:
        db.close()


@pytest.mark.asyncio
async def test_needs_approval_forces_pending_for_tombstoned_media():
    """Un média qu'un admin a supprimé force une nouvelle validation, même si
    l'approbation globale est désactivée et l'utilisateur auto-approuvé."""
    db = make_test_session()
    try:
        await deleted_media.record_deletion(db, "movie", "Removed Movie", tmdb_id="55")
        db.commit()

        body = MediaAddRequest(title="Removed Movie", media_type="movie", tmdb_id="55", plex_user_id="user1")
        caller = {"plex_user_id": "user1", "role": "user"}

        # settings=None (equivaut a require_approval desactive) : sans le garde-fou
        # tombstone, ceci retournerait False.
        assert await _needs_approval(db, None, caller, "user1", body) is True
    finally:
        db.close()


@pytest.mark.asyncio
async def test_needs_approval_admin_bypasses_tombstone():
    """Un admin qui redemande lui-meme un media supprime n'a pas besoin d'une
    seconde validation -- sa demande explicite EST deja la decision consciente."""
    db = make_test_session()
    try:
        await deleted_media.record_deletion(db, "movie", "Removed Movie", tmdb_id="55")
        db.commit()

        body = MediaAddRequest(title="Removed Movie", media_type="movie", tmdb_id="55", plex_user_id="admin1")
        caller = {"plex_user_id": "admin1", "role": "admin"}

        assert await _needs_approval(db, None, caller, "admin1", body) is False
    finally:
        db.close()


@pytest.mark.asyncio
async def test_needs_approval_not_tombstoned_falls_back_to_normal_rules():
    """Sans trace de suppression, le comportement habituel (pas d'approbation
    requise si les reglages ne l'exigent pas) reste inchange."""
    db = make_test_session()
    try:
        body = MediaAddRequest(title="Never Deleted", media_type="movie", tmdb_id="1", plex_user_id="user1")
        caller = {"plex_user_id": "user1", "role": "user"}

        assert await _needs_approval(db, None, caller, "user1", body) is False
    finally:
        db.close()
