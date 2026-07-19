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
    assert projection["workflow_timeline"][0]["key"] == "submitted"
    assert "requested" not in {step["key"] for step in projection["workflow_timeline"]}
    assert next(step for step in projection["workflow_timeline"] if step["key"] == "downloading")["state"] == "current"


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
    assert projection["workflow_timeline"] == [{
        "key": "completed",
        "label": "Deja present dans Plex",
        "state": "completed",
        "occurred_at": None,
    }]


def test_pending_approval_timeline_has_only_one_current_step():
    projection = request_operational_projection(SimpleNamespace(
        source="rss",
        fulfillment_status=FulfillmentStatus.not_submitted,
        fulfillment_error=None,
        requested_at=None,
        approved_at=None,
    ))

    current = [step["key"] for step in projection["workflow_timeline"] if step["state"] == "current"]
    assert current == ["approval"]
    assert projection["workflow_timeline"][0]["key"] == "requested"
