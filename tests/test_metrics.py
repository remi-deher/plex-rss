"""Tests unitaires pour app/metrics.py — compteurs in-memory."""

import app.metrics as m


def _reset():
    """Réinitialise le singleton _m entre les tests."""
    from app.metrics import _Metrics
    import app.metrics as mod
    mod._m = _Metrics()


# ---------------------------------------------------------------------------
# record_poll
# ---------------------------------------------------------------------------


def test_record_poll_increments_count():
    _reset()
    m.record_poll(120.0)
    m.record_poll(80.0)
    assert m._m.poll_count == 2


def test_record_poll_stores_last_duration():
    _reset()
    m.record_poll(250.5)
    assert m._m.last_poll_duration_ms == 250.5


def test_record_poll_error_flag():
    _reset()
    m.record_poll(100.0, error=False)
    m.record_poll(200.0, error=True)
    assert m._m.poll_errors == 1
    assert m._m.poll_count == 2


def test_record_poll_sets_last_at():
    _reset()
    m.record_poll(50.0)
    assert m._m.last_poll_at is not None


# ---------------------------------------------------------------------------
# record_arr_submission
# ---------------------------------------------------------------------------


def test_record_arr_submission_success():
    _reset()
    m.record_arr_submission(True)
    m.record_arr_submission(True)
    m.record_arr_submission(False)
    assert m._m.arr_submissions == 2
    assert m._m.arr_errors == 1


def test_arr_error_rate():
    _reset()
    m.record_arr_submission(True)
    m.record_arr_submission(False)
    assert m._m.arr_error_rate == 50.0


def test_arr_error_rate_none_when_no_submissions():
    _reset()
    assert m._m.arr_error_rate is None


# ---------------------------------------------------------------------------
# record_notification
# ---------------------------------------------------------------------------


def test_record_notification_counts():
    _reset()
    m.record_notification(True)
    m.record_notification(True)
    m.record_notification(False)
    assert m._m.notifications_sent == 2
    assert m._m.notifications_failed == 1


def test_notification_failure_rate():
    _reset()
    m.record_notification(True)
    m.record_notification(False)
    assert m._m.notification_failure_rate == 50.0


def test_notification_failure_rate_none_when_no_notifications():
    _reset()
    assert m._m.notification_failure_rate is None


# ---------------------------------------------------------------------------
# latences *arr
# ---------------------------------------------------------------------------


def test_sonarr_avg_latency():
    _reset()
    m.record_sonarr_latency(100.0)
    m.record_sonarr_latency(200.0)
    assert m._m.sonarr_avg_ms == 150.0


def test_radarr_avg_latency():
    _reset()
    m.record_radarr_latency(50.0)
    assert m._m.radarr_avg_ms == 50.0


def test_overseerr_avg_latency():
    _reset()
    m.record_overseerr_latency(300.0)
    m.record_overseerr_latency(100.0)
    assert m._m.overseerr_avg_ms == 200.0


def test_latency_none_when_no_samples():
    _reset()
    assert m._m.sonarr_avg_ms is None
    assert m._m.radarr_avg_ms is None
    assert m._m.overseerr_avg_ms is None


def test_latency_window_capped_at_50():
    _reset()
    for i in range(60):
        m.record_sonarr_latency(float(i))
    assert len(m._m._sonarr_latencies) == 50
    # Seuls les 50 derniers (10–59) sont conservés
    assert m._m._sonarr_latencies[0] == 10.0


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------


def test_snapshot_structure():
    _reset()
    snap = m.snapshot()
    assert "poll" in snap
    assert "arr" in snap
    assert "notifications" in snap


def test_snapshot_reflects_recorded_data():
    _reset()
    m.record_poll(123.0)
    m.record_notification(True)
    m.record_arr_submission(False)

    snap = m.snapshot()
    assert snap["poll"]["count"] == 1
    assert snap["poll"]["last_duration_ms"] == 123.0
    assert snap["notifications"]["sent"] == 1
    assert snap["arr"]["errors"] == 1
