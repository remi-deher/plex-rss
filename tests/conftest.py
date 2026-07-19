"""Configuration pytest partagée : suppression des ResourceWarning SQLite et patch du démarrage."""

import warnings
from unittest.mock import AsyncMock, patch

import pytest

from tests.async_support import make_test_session

# Les connexions SQLite non fermées viennent du pool SQLAlchemy créé à l'import de app.database.
# Ce n'est pas un bug fonctionnel (l'OS récupère les ressources), on filtre le bruit.
warnings.filterwarnings("ignore", "unclosed database", ResourceWarning)


@pytest.fixture(autouse=True)
def _patch_app_startup():
    """Empêche le scheduler et le worker de démarrer pendant les tests."""
    with (
        patch("app.scheduler.start_scheduler"),
        patch("app.notification_queue.start_worker", return_value=None),
    ):
        yield


@pytest.fixture(autouse=True)
def _isolate_application_cache(monkeypatch):
    """Keep cache tests deterministic when CI exposes a shared Redis service.

    Redis transport itself is covered by test_realtime_redis.py. Endpoint and
    stale-while-revalidate tests must use their per-instance memory cache;
    otherwise fixed production keys leak values between otherwise isolated tests.
    """
    from app.cache import Cache, _refreshing_keys, cache

    async def memory_only_client(self):
        return None

    monkeypatch.setattr(Cache, "_client", memory_only_client)
    cache._memory.clear()
    _refreshing_keys.clear()
    yield
    cache._memory.clear()
    _refreshing_keys.clear()


@pytest.fixture()
def async_db():
    """Hybrid session for synchronous TestClient tests of async endpoints."""
    db = make_test_session()
    yield db
    db.close()
