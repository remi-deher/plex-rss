"""arr_processed_at doit être posé automatiquement à la première transition vers
sent_to_arr, quel que soit l'endroit du code qui fait `req.status = ...` — voir la
fiche détail (section Demandes) qui l'affiche à côté de requested_at/available_at.
"""

from app.models import MediaRequest, RequestStatus


def test_stamps_arr_processed_at_on_transition_to_sent_to_arr():
    req = MediaRequest(plex_user_id="alice", title="Dune", media_type="movie", status=RequestStatus.pending)
    assert req.arr_processed_at is None

    req.status = RequestStatus.sent_to_arr
    assert req.arr_processed_at is not None
    first_stamp = req.arr_processed_at

    # Une transition ultérieure (ex: passage à "available") ne doit pas l'écraser.
    req.status = RequestStatus.available
    assert req.arr_processed_at == first_stamp


def test_does_not_stamp_for_non_sent_to_arr_statuses():
    req = MediaRequest(plex_user_id="alice", title="Dune", media_type="movie", status=RequestStatus.pending)
    req.status = RequestStatus.failed
    assert req.arr_processed_at is None


def test_stamps_when_constructed_directly_with_sent_to_arr():
    req = MediaRequest(
        plex_user_id="system", title="Dune", media_type="movie", status=RequestStatus.sent_to_arr
    )
    assert req.arr_processed_at is not None
