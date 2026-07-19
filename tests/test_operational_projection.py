from types import SimpleNamespace

from app.models import FulfillmentStatus
from app.services.operational_projection import (
    plex_library_projection,
    request_operational_projection,
    request_origin,
)


def test_arr_origin_does_not_invent_user_request():
    projection = request_operational_projection(SimpleNamespace(
        source="arr_sync",
        fulfillment_status=FulfillmentStatus.downloading,
        fulfillment_error=None,
    ))

    assert projection["origin_kind"] == "arr"
    assert projection["origin_label"] == "Ajoute directement dans *ARR"
    assert projection["operational_status_label"] == "Telechargement en cours"


def test_request_origin_preserves_external_request_channel():
    assert request_origin("seer") == {
        "kind": "request",
        "label": "Demande via Seerr",
    }
    assert request_origin("rss")["label"] == "Demande utilisateur"


def test_plex_only_projection_is_immediately_available():
    projection = plex_library_projection()

    assert projection["origin_kind"] == "plex"
    assert projection["operational_status"] == "completed"
    assert projection["waiting_reason"] is None
