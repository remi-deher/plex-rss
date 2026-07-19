"""Tests unitaires pour app/serializers.py."""

import json

from app.models import MediaRequest, RequestStatus
from app.serializers import serialize_media_request


def _req(**kwargs) -> MediaRequest:
    defaults = dict(
        plex_user_id="alice",
        plex_user="Alice",
        title="Dune",
        media_type="movie",
        status=RequestStatus.available,
    )
    defaults.update(kwargs)
    return MediaRequest(**defaults)


def test_serialize_media_request_basic_requester_ids():
    req = _req(extra_requesters=json.dumps([{"plex_user_id": "bob", "display_name": "Bob"}]))
    payload = serialize_media_request(req, {"alice": "Alice", "bob": "Bob"})
    assert payload["requester_ids"] == ["alice", "bob"]
    assert payload["requesters"] == ["Alice", "Bob"]


def test_serialize_media_request_dedupes_primary_duplicated_in_extras():
    """Régression : une ligne historique où extra_requesters contient à nouveau le
    demandeur principal (donnée corrompue, ex: remap d'utilisateurs) produisait
    requester_ids en double — ce qui cassait le :key du v-for côté frontend
    (MediaDetailDrawer.vue) et empêchait la fiche détail de s'afficher pour ces
    demandes (série "Chouchouté par l'Ange d'à côté" notamment)."""
    req = _req(
        extra_requesters=json.dumps(
            [
                {"plex_user_id": "alice", "display_name": "Alice"},
                {"plex_user_id": "bob", "display_name": "Bob"},
            ]
        )
    )
    payload = serialize_media_request(req, {"alice": "Alice", "bob": "Bob"})
    assert payload["requester_ids"] == ["alice", "bob"]
    assert payload["requesters"] == ["Alice", "Bob"]
    assert json.loads(payload["extra_requesters"]) == [{"plex_user_id": "bob", "display_name": "Bob"}]


def test_serialize_media_request_dedupes_repeated_extra():
    """Un co-demandeur liste deux fois dans extra_requesters (autre variante de
    donnee corrompue) ne doit apparaitre qu'une seule fois."""
    req = _req(
        extra_requesters=json.dumps(
            [
                {"plex_user_id": "bob", "display_name": "Bob"},
                {"plex_user_id": "bob", "display_name": "Bob"},
            ]
        )
    )
    payload = serialize_media_request(req, {"alice": "Alice", "bob": "Bob"})
    assert payload["requester_ids"] == ["alice", "bob"]


def test_serialize_media_request_no_extras():
    req = _req(extra_requesters=None)
    payload = serialize_media_request(req, {"alice": "Alice"})
    assert payload["requester_ids"] == ["alice"]
    assert payload["extra_requesters"] == "[]"


def test_serialize_media_request_malformed_extras_falls_back_gracefully():
    req = _req(extra_requesters="not-json")
    payload = serialize_media_request(req, {"alice": "Alice"})
    assert payload["requester_ids"] == ["alice"]
    assert payload["extra_requesters"] == "[]"
