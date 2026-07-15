"""Régression : la création de MediaRequest sans tmdb_id/tvdb_id ne doit jamais crasher.

Couvre le bug où `_create_pending_request` et la déduplication de `/media/add`
appelaient `.first()` directement sur un `select()` non exécuté (AttributeError),
faisant perdre le suivi local d'une demande alors même que l'ajout à Radarr/Sonarr/
Seer avait déjà réussi.
"""

import pytest

from app.routers.library_api import MediaAddRequest, _create_pending_request
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
