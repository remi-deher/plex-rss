"""
Compteurs in-memory légers pour l'observabilité runtime.

Ces métriques sont réinitialisées au redémarrage — elles mesurent
l'activité de la session courante, pas l'historique total (qui est dans la DB).
"""

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class _Metrics:
    # Cycles de polling
    poll_count: int = 0
    poll_errors: int = 0
    last_poll_at: Optional[float] = None
    last_poll_duration_ms: Optional[float] = None

    # Soumissions aux *arr
    arr_submissions: int = 0
    arr_errors: int = 0

    # Notifications email
    notifications_sent: int = 0
    notifications_failed: int = 0

    # Temps de réponse *arr (liste des N derniers, en ms)
    _sonarr_latencies: list = field(default_factory=list)
    _radarr_latencies: list = field(default_factory=list)
    _seer_latencies: list = field(default_factory=list)

    _MAX_LATENCY_SAMPLES: int = field(default=50, init=False, repr=False)

    def _add_latency(self, bucket: list, ms: float):
        bucket.append(ms)
        if len(bucket) > self._MAX_LATENCY_SAMPLES:
            bucket.pop(0)

    def record_sonarr_latency(self, ms: float):
        self._add_latency(self._sonarr_latencies, ms)

    def record_radarr_latency(self, ms: float):
        self._add_latency(self._radarr_latencies, ms)

    def record_seer_latency(self, ms: float):
        self._add_latency(self._seer_latencies, ms)

    def avg_latency(self, bucket: list) -> Optional[float]:
        return round(sum(bucket) / len(bucket), 1) if bucket else None

    @property
    def sonarr_avg_ms(self) -> Optional[float]:
        return self.avg_latency(self._sonarr_latencies)

    @property
    def radarr_avg_ms(self) -> Optional[float]:
        return self.avg_latency(self._radarr_latencies)

    @property
    def seer_avg_ms(self) -> Optional[float]:
        return self.avg_latency(self._seer_latencies)

    @property
    def notification_failure_rate(self) -> Optional[float]:
        total = self.notifications_sent + self.notifications_failed
        if total == 0:
            return None
        return round(self.notifications_failed / total * 100, 1)

    @property
    def arr_error_rate(self) -> Optional[float]:
        total = self.arr_submissions + self.arr_errors
        if total == 0:
            return None
        return round(self.arr_errors / total * 100, 1)


_m = _Metrics()


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------


def record_poll(duration_ms: float, error: bool = False):
    _m.poll_count += 1
    _m.last_poll_at = time.time()
    _m.last_poll_duration_ms = round(duration_ms, 1)
    if error:
        _m.poll_errors += 1


def record_arr_submission(success: bool):
    if success:
        _m.arr_submissions += 1
    else:
        _m.arr_errors += 1


def record_notification(success: bool):
    if success:
        _m.notifications_sent += 1
    else:
        _m.notifications_failed += 1


def record_sonarr_latency(ms: float):
    _m.record_sonarr_latency(ms)


def record_radarr_latency(ms: float):
    _m.record_radarr_latency(ms)


def record_seer_latency(ms: float):
    _m.record_seer_latency(ms)


def snapshot() -> dict:
    """Retourne un dict JSON-sérialisable des métriques courantes."""
    return {
        "poll": {
            "count": _m.poll_count,
            "errors": _m.poll_errors,
            "last_at": _m.last_poll_at,
            "last_duration_ms": _m.last_poll_duration_ms,
        },
        "arr": {
            "submissions": _m.arr_submissions,
            "errors": _m.arr_errors,
            "error_rate_pct": _m.arr_error_rate,
            "sonarr_avg_response_ms": _m.sonarr_avg_ms,
            "radarr_avg_response_ms": _m.radarr_avg_ms,
            "seer_avg_response_ms": _m.seer_avg_ms,
        },
        "notifications": {
            "sent": _m.notifications_sent,
            "failed": _m.notifications_failed,
            "failure_rate_pct": _m.notification_failure_rate,
        },
    }
