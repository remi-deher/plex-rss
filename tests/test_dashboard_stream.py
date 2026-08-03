"""Chargement au fil de l'eau du tableau de bord (/api/dashboard/snapshot/stream).

`/api/dashboard/snapshot` calcule dix sections en parallèle puis répond d'un bloc : le
premier affichage attend donc la plus lente des dix, même si les neuf autres sont prêtes
depuis longtemps. Le flux émet chaque section dès qu'elle arrive.
"""

import asyncio
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.database import get_db_async
from app.dependencies import require_admin, require_auth
from app.main import app
from app.routers import dashboard_api


def _client(db):
    app.dependency_overrides[get_db_async] = lambda: db
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_admin] = lambda: None
    return TestClient(app, raise_server_exceptions=True)


def _cleanup():
    app.dependency_overrides.pop(get_db_async, None)
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(require_admin, None)


def _frames(text):
    """Décode les trames SSE reçues, dans leur ordre d'arrivée."""
    payloads = []
    for block in text.split("\n\n"):
        data = "".join(
            line[len("data:") :].strip() for line in block.split("\n") if line.startswith("data:")
        )
        if data:
            payloads.append(json.loads(data))
    return payloads


def _fake_calls(delays):
    """Fabrique des sections dont on contrôle le temps de réponse."""

    def _build():
        calls = {}
        for name, delay in delays.items():

            def _make(name=name, delay=delay):
                async def _call(_db):
                    await asyncio.sleep(delay)
                    return {"section": name}

                return _call

            calls[name] = _make()
        return calls

    return _build


def test_sections_arrive_as_they_complete(async_db):
    """La section lente ne doit pas retenir les rapides : l'ordre d'arrivée suit le temps
    de calcul, pas l'ordre de déclaration."""
    delays = {"lente": 0.20, "moyenne": 0.10, "rapide": 0.01}
    client = _client(async_db)
    try:
        with patch.object(dashboard_api, "_snapshot_calls", _fake_calls(delays)):
            response = client.get("/api/dashboard/snapshot/stream")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        payloads = _frames(response.text)
        # next_poll ne fait aucune I/O : il part avant toutes les autres.
        assert "next_poll" in payloads[0]
        assert [next(iter(p)) for p in payloads[1:]] == ["rapide", "moyenne", "lente"]
    finally:
        _cleanup()


def test_each_frame_carries_a_single_section(async_db):
    """C'est ce qui permet à la vue d'appliquer une section sans toucher aux autres."""
    client = _client(async_db)
    try:
        with patch.object(dashboard_api, "_snapshot_calls", _fake_calls({"a": 0, "b": 0})):
            response = client.get("/api/dashboard/snapshot/stream")

        payloads = _frames(response.text)
        assert all(len(payload) == 1 for payload in payloads)
        assert {"a", "b"} <= {key for payload in payloads for key in payload}
    finally:
        _cleanup()


def test_a_failing_section_does_not_abort_the_others(async_db):
    """Une section en échec est signalée à part ; le reste du tableau de bord s'affiche."""

    def _calls():
        async def _ok(_db):
            return {"ok": True}

        async def _boom(_db):
            raise RuntimeError("Sonarr injoignable")

        return {"bonne": _ok, "cassee": _boom}

    client = _client(async_db)
    try:
        with patch.object(dashboard_api, "_snapshot_calls", _calls):
            response = client.get("/api/dashboard/snapshot/stream")

        payloads = _frames(response.text)
        assert {"bonne": {"ok": True}} in payloads
        assert {"errors": ["cassee"]} in payloads
    finally:
        _cleanup()


def test_stream_is_not_gzipped(async_db):
    """Le GZipMiddleware n'exclut que `text/event-stream`. Compressé, le flux serait
    tamponné et arriverait d'un bloc — le streaming ne servirait plus à rien."""
    client = _client(async_db)
    try:
        with patch.object(dashboard_api, "_snapshot_calls", _fake_calls({"a": 0})):
            response = client.get(
                "/api/dashboard/snapshot/stream", headers={"Accept-Encoding": "gzip"}
            )
        assert response.headers.get("content-encoding") != "gzip"
        assert response.headers.get("x-accel-buffering") == "no"
    finally:
        _cleanup()


def test_successful_stream_warms_the_shared_cache(async_db):
    """Le rafraîchissement ciblé et le repli non streamé doivent repartir d'une valeur
    chaude plutôt que de tout recalculer."""
    stored = {}

    async def _set_json(key, value, ttl_seconds):
        stored[key] = value

    client = _client(async_db)
    try:
        with patch.object(dashboard_api, "_snapshot_calls", _fake_calls({"a": 0, "b": 0})), patch.object(
            dashboard_api.cache, "set_json", _set_json
        ):
            client.get("/api/dashboard/snapshot/stream")

        assert dashboard_api._CACHE_KEY in stored
        cached = stored[dashboard_api._CACHE_KEY]["value"]
        assert cached["a"] == {"section": "a"}
        assert cached["b"] == {"section": "b"}
        assert "next_poll" in cached
    finally:
        _cleanup()


def test_partial_failure_does_not_warm_the_cache(async_db):
    """Mettre en cache un tableau de bord amputé le figerait pour tout le monde pendant
    la durée du TTL."""
    stored = {}

    async def _set_json(key, value, ttl_seconds):
        stored[key] = value

    def _calls():
        async def _ok(_db):
            return {"ok": True}

        async def _boom(_db):
            raise RuntimeError("indisponible")

        return {"bonne": _ok, "cassee": _boom}

    client = _client(async_db)
    try:
        with patch.object(dashboard_api, "_snapshot_calls", _calls), patch.object(
            dashboard_api.cache, "set_json", _set_json
        ):
            client.get("/api/dashboard/snapshot/stream")
        assert stored == {}
    finally:
        _cleanup()
