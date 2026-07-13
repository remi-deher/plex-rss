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
def _clear_memory_cache():
    """Prevent cached endpoint responses from leaking between tests."""
    from app.cache import cache

    cache._memory.clear()
    yield
    cache._memory.clear()


@pytest.fixture()
def async_db():
    """Hybrid session for synchronous TestClient tests of async endpoints."""
    db = make_test_session()
    yield db
    db.close()
