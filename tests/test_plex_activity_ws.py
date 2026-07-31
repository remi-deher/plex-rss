"""Tests du signalement d'état de l'écouteur websocket Plex.

Ces tests couvrent la *visibilité* des pannes (l'écouteur meurt / n'est pas configuré /
échoue en série), pas le dialogue réel avec un serveur Plex : la charge utile websocket
n'est pas simulée ici.
"""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import jobs
from app.services import plex_activity_ws as ws


class _EmptyDB:
    """Session minimale : le démarrage ne fait qu'y lire les notifications en attente."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, *args, **kwargs):
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        return result


@pytest.mark.asyncio
async def test_startup_wires_crash_reporting_on_the_detached_listener():
    """Le démarrage réel doit brancher la remontée d'erreur, pas seulement la définir.

    Passe volontairement par `jobs.startup()` : un test qui poserait lui-même le
    callback validerait `_on_listener_exit` tout en laissant le câblage cassé.
    """
    recorded = []

    async def fake_record(action, status, message, details=None):
        recorded.append((action, status, message))

    async def boom():
        raise RuntimeError("module websockets absent")

    ctx = {"redis": AsyncMock()}
    with (
        patch.object(jobs, "init_db", AsyncMock()),
        patch.object(jobs, "AsyncSessionLocal", lambda: _EmptyDB()),
        patch.object(jobs, "record_worker_event", fake_record),
        patch.object(ws, "run_alert_listener", boom),
    ):
        await jobs.startup(ctx)
        with contextlib.suppress(RuntimeError):
            await ctx["ws_listener_task"]
        for _ in range(3):  # laisse le callback planifier puis exécuter l'enregistrement
            await asyncio.sleep(0)

    crash = [entry for entry in recorded if entry[0] == "websocket.stopped"]
    assert crash, "la mort de l'écouteur doit laisser une trace durable"
    assert crash[0][1] == "error"
    assert "websockets absent" in crash[0][2]


@pytest.mark.asyncio
async def test_deliberate_shutdown_is_not_reported_as_a_failure():
    """L'arrêt propre du worker ne doit pas polluer le journal d'incidents."""
    recorded = []

    async def fake_record(action, status, message, details=None):
        recorded.append(action)

    async def forever():
        await asyncio.sleep(3600)

    with patch.object(jobs, "record_worker_event", fake_record):
        task = asyncio.create_task(forever())
        task.add_done_callback(jobs._on_listener_exit)
        await asyncio.sleep(0)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        for _ in range(3):
            await asyncio.sleep(0)

    assert recorded == []


@pytest.mark.asyncio
async def test_unconfigured_plex_is_reported_once_not_every_cycle():
    """Sans Plex configuré la boucle tourne indéfiniment : elle ne doit alerter qu'une fois."""
    recorded = []
    calls = {"n": 0}

    async def fake_record(action, status, message, details=None):
        recorded.append(action)

    async def fake_load_settings():
        calls["n"] += 1
        if calls["n"] > 4:
            raise asyncio.CancelledError
        return None

    with (
        patch.object(ws, "_record", fake_record),
        patch.object(ws, "_load_settings", fake_load_settings),
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        with pytest.raises(asyncio.CancelledError):
            await ws.run_alert_listener()

    assert recorded == ["websocket.idle"], "un seul signalement malgré plusieurs cycles"


@pytest.mark.asyncio
async def test_startup_aborts_loudly_when_migrations_fail():
    """Un worker sur un schéma désynchronisé doit refuser de démarrer, pas continuer."""
    recorded = []

    async def fake_record(action, status, message, details=None):
        recorded.append((action, status))

    with (
        patch.object(jobs, "init_db", AsyncMock(side_effect=RuntimeError("colonne manquante"))),
        patch.object(jobs, "record_worker_event", fake_record),
    ):
        with pytest.raises(RuntimeError):
            await jobs.startup({})

    assert ("startup.db", "error") in recorded
