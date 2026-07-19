"""Tests unitaires pour le routage SPA (app/main.py::serve_spa / SPA_ROOTS)."""

from fastapi.testclient import TestClient

from app.database import get_db_async
from app.dependencies import require_admin, require_auth
from app.main import app


def _client(db):
    app.dependency_overrides[get_db_async] = lambda: db
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_admin] = lambda: None
    return TestClient(app, raise_server_exceptions=False)


def _cleanup():
    app.dependency_overrides.pop(get_db_async, None)
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(require_admin, None)


def test_media_detail_route_is_served_not_404(async_db):
    """Régression : /media/:kind/:id (page de fiche détail) doit être servie par le SPA
    (index.html, routage géré côté Vue Router), pas renvoyer 404 depuis le backend —
    ce cas se produit sur un rechargement de page ou un lien direct vers /media/..."""
    client = _client(async_db)
    try:
        resp = client.get("/media/library/1342")
        assert resp.status_code == 200
        resp2 = client.get("/media/request/42")
        assert resp2.status_code == 200
        resp3 = client.get("/media/discover/438631?media_type=movie")
        assert resp3.status_code == 200
    finally:
        _cleanup()


def test_unknown_spa_root_still_404s(async_db):
    """Un chemin de premier niveau non enregistré doit toujours 404 (pas de faille par
    laquelle n'importe quelle route arbitraire serait servie comme du SPA)."""
    client = _client(async_db)
    try:
        resp = client.get("/totally-unknown-route")
        assert resp.status_code == 404
    finally:
        _cleanup()
