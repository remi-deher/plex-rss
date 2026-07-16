"""Tests unitaires pour /api/image-proxy et son cache disque (app/routers/misc_api.py)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import require_auth
from app.main import app


def _client():
    app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)


def _cleanup():
    app.dependency_overrides.pop(require_auth, None)


def _resp(status_code=200, content=b"fake-image-bytes", content_type="image/jpeg"):
    r = MagicMock()
    r.status_code = status_code
    r.content = content
    r.headers = {"content-type": content_type}
    r.raise_for_status = MagicMock()
    return r


def _fake_httpx_client(resp=None, side_effect=None):
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    if side_effect is not None:
        client.get = AsyncMock(side_effect=side_effect)
    else:
        client.get = AsyncMock(return_value=resp)
    return client


@pytest.fixture()
def cache_dir(tmp_path):
    with patch("app.routers.misc_api._IMAGE_CACHE_DIR", str(tmp_path / "image_cache")):
        yield tmp_path / "image_cache"


def test_image_proxy_invalid_url_rejected():
    client = _client()
    try:
        resp = client.get("/api/image-proxy?url=not-a-url")
        assert resp.status_code == 400
    finally:
        _cleanup()


def test_image_proxy_fetches_and_caches(cache_dir):
    client = _client()
    fake = _fake_httpx_client(resp=_resp())
    try:
        with patch("app.routers.misc_api.httpx.AsyncClient", return_value=fake):
            resp = client.get("/api/image-proxy?url=http://plex.local/poster.jpg")
        assert resp.status_code == 200
        assert resp.content == b"fake-image-bytes"
        fake.get.assert_awaited_once()
        assert cache_dir.exists()
        assert len(list(cache_dir.glob("*.bin"))) == 1
    finally:
        _cleanup()


def test_image_proxy_second_call_uses_cache_not_plex(cache_dir):
    """Régression : un deuxième affichage de la même image ne doit plus jamais
    retaper Plex — c'est ce qui évite de le saturer lors des rafales de vignettes."""
    client = _client()
    fake = _fake_httpx_client(resp=_resp())
    try:
        with patch("app.routers.misc_api.httpx.AsyncClient", return_value=fake):
            first = client.get("/api/image-proxy?url=http://plex.local/poster.jpg")
            second = client.get("/api/image-proxy?url=http://plex.local/poster.jpg")
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.content == b"fake-image-bytes"
        fake.get.assert_awaited_once()  # une seule requete Plex pour les deux appels
    finally:
        _cleanup()


def test_image_proxy_expired_cache_refetches(cache_dir):
    client = _client()
    fake = _fake_httpx_client(resp=_resp())
    try:
        with patch("app.routers.misc_api.httpx.AsyncClient", return_value=fake):
            client.get("/api/image-proxy?url=http://plex.local/poster.jpg")
        with patch("app.routers.misc_api.time.time", return_value=__import__("time").time() + 999999):
            with patch("app.routers.misc_api.httpx.AsyncClient", return_value=fake):
                client.get("/api/image-proxy?url=http://plex.local/poster.jpg")
        assert fake.get.await_count == 2
    finally:
        _cleanup()


def test_image_proxy_serves_stale_cache_on_plex_failure(cache_dir):
    """Régression : si Plex échoue mais qu'une version (même périmée) est en cache,
    on la sert plutôt que de renvoyer 502 — l'incident rapporté ('image inaccessible'
    lors des rafales) doit devenir invisible pour l'utilisateur une fois l'image
    déjà vue une première fois."""
    client = _client()
    fake_ok = _fake_httpx_client(resp=_resp())
    fake_fail = _fake_httpx_client(side_effect=Exception("connection reset"))
    try:
        with patch("app.routers.misc_api.httpx.AsyncClient", return_value=fake_ok):
            first = client.get("/api/image-proxy?url=http://plex.local/poster.jpg")
        assert first.status_code == 200

        # Force le cache a etre considere perime pour declencher un re-fetch...
        with patch("app.routers.misc_api.time.time", return_value=__import__("time").time() + 999999):
            with patch("app.routers.misc_api.httpx.AsyncClient", return_value=fake_fail):
                second = client.get("/api/image-proxy?url=http://plex.local/poster.jpg")
        # ...qui echoue cote Plex, mais le cache perime sert quand meme de filet.
        assert second.status_code == 200
        assert second.content == b"fake-image-bytes"
    finally:
        _cleanup()


def test_image_proxy_no_cache_and_plex_failure_returns_502():
    """Comportement preexistant : sans aucun cache, un echec Plex reste un 502."""
    client = _client()
    fake_fail = _fake_httpx_client(side_effect=Exception("connection reset"))
    with patch("app.routers.misc_api._IMAGE_CACHE_DIR", "/nonexistent/path/that/has/no/cache"):
        try:
            with patch("app.routers.misc_api.httpx.AsyncClient", return_value=fake_fail):
                resp = client.get("/api/image-proxy?url=http://plex.local/poster.jpg")
            assert resp.status_code == 502
        finally:
            _cleanup()


def test_image_proxy_rejects_non_image_content_type(cache_dir):
    client = _client()
    fake = _fake_httpx_client(resp=_resp(content_type="text/html"))
    try:
        with patch("app.routers.misc_api.httpx.AsyncClient", return_value=fake):
            resp = client.get("/api/image-proxy?url=http://plex.local/poster.jpg")
        assert resp.status_code == 415
    finally:
        _cleanup()
