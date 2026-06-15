"""Configuration pytest partagée : suppression des ResourceWarning SQLite et patch du démarrage."""

import warnings
from unittest.mock import AsyncMock, patch

import pytest

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
