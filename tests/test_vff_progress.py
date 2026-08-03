"""Tests de la diffusion SSE de la progression VFF (app/services/vff_progress.py).

Le tableau de bord sondait `/api/vff/scan-status`, `/api/vff/sync-status` et
`/api/vff/counts` toutes les 5 secondes. Ces tests verrouillent le contrat qui remplace
ce sondage : progression poussée pendant le scan, arrêt complet au repos.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.realtime import EVENT_TYPES
from app.services import vff_progress


@pytest.fixture(autouse=True)
def no_shared_state_writes():
    """Neutralise le miroir Redis par défaut : sans cela, ces tests écriraient dans le
    Redis réel dès que `REDIS_URL` est présent dans l'environnement. Le test dédié au
    miroir repose son propre patch par-dessus."""
    with patch.object(vff_progress.scan_state, "write_section", AsyncMock()):
        yield


_IDLE = {
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "items_scanned": 0,
    "items_synced": 0,
    "total_items": 0,
    "error": None,
}


def _reset(state, backup):
    state.clear()
    state.update(backup)


async def _wait_until(predicate, timeout=3.0):
    """Attend une condition plutôt qu'une durée fixe : la suite complète charge la boucle
    asyncio, des `sleep` calibrés à vide y deviennent instables."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            return False
        await asyncio.sleep(0.005)
    return True


async def _run_watcher(mutate):
    """Lance la diffusion, applique `mutate` (une coroutine pilotant les dicts d'état),
    et retourne les évènements publiés.

    Les deux dicts sont remis au repos avant le scénario : ce sont des globales de module
    que d'autres tests laissent parfois en "running", et `_is_running` les regarde toutes
    les deux — la tâche ne s'arrêterait alors jamais.
    """
    from app.services.plex_sync import plex_sync_state
    from app.services.vff_scanner import vff_scan_state

    scan_backup, sync_backup = dict(vff_scan_state), dict(plex_sync_state)
    _reset(vff_scan_state, _IDLE)
    _reset(plex_sync_state, _IDLE)
    published: list[tuple[str, dict]] = []

    async def _fake_publish(event_type, payload=None, **kwargs):
        published.append((event_type, payload))
        return "event-id"

    try:
        with (
            patch.object(vff_progress, "publish", _fake_publish),
            patch.object(vff_progress, "_POLL_INTERVAL_SECONDS", 0.01),
            patch.object(
                vff_progress,
                "_library_counts",
                AsyncMock(return_value={"vo_pending": 1, "vf_available": 3, "unchecked": 0}),
            ),
        ):
            await mutate(vff_scan_state, plex_sync_state, published)
    finally:
        _reset(vff_scan_state, scan_backup)
        _reset(plex_sync_state, sync_backup)
        if vff_progress._watcher is not None:
            vff_progress._watcher.cancel()
            vff_progress._watcher = None
    return published


async def test_vff_updated_is_a_known_event_type():
    """`publish` rejette les types inconnus : sans cette entrée, toute la diffusion
    lèverait ValueError au premier évènement."""
    assert "vff.updated" in EVENT_TYPES


async def test_publishes_each_change_then_stops_when_idle():
    async def scenario(scan, _sync, published):
        scan.update({"status": "running", "items_scanned": 0, "total_items": 10, "error": None})
        vff_progress.notify_vff_progress()
        assert await _wait_until(lambda: len(published) == 1)

        scan["items_scanned"] = 5
        assert await _wait_until(lambda: len(published) == 2)

        scan.update({"status": "idle", "finished_at": "2026-01-01T00:00:00"})
        assert await _wait_until(lambda: len(published) == 3)
        # La tâche se termine d'elle-même : aucun coût quand plus rien ne tourne.
        assert await _wait_until(lambda: vff_progress._watcher is None)

    published = await _run_watcher(scenario)

    assert [event_type for event_type, _ in published] == ["vff.updated"] * 3
    assert published[0][1]["scan"]["items_scanned"] == 0
    assert published[1][1]["scan"]["items_scanned"] == 5
    assert published[2][1]["scan"]["status"] == "idle"


async def test_counts_are_attached_only_at_the_end_of_a_scan():
    """Trois COUNT en base à chaque tick reproduiraient le coût qu'on vient de supprimer :
    les compteurs ne bougent qu'une fois le scan terminé."""

    async def scenario(scan, _sync, published):
        scan.update({"status": "running", "items_scanned": 0, "total_items": 4})
        vff_progress.notify_vff_progress()
        assert await _wait_until(lambda: len(published) == 1)
        scan["items_scanned"] = 2
        assert await _wait_until(lambda: len(published) == 2)
        scan.update({"status": "idle", "finished_at": "2026-01-01T00:00:00"})
        assert await _wait_until(lambda: len(published) == 3)

    published = await _run_watcher(scenario)

    assert "counts" not in published[0][1]
    assert "counts" not in published[1][1]
    assert published[-1][1]["counts"] == {"vo_pending": 1, "vf_available": 3, "unchecked": 0}


async def test_identical_states_are_not_republished():
    async def scenario(scan, _sync, published):
        scan.update({"status": "running", "items_scanned": 1, "total_items": 9})
        vff_progress.notify_vff_progress()
        assert await _wait_until(lambda: len(published) == 1)
        # Plusieurs cycles d'observation sans aucune mutation : rien ne doit repartir.
        await asyncio.sleep(0.08)
        assert len(published) == 1
        scan.update({"status": "idle", "finished_at": "2026-01-01T00:00:00"})
        assert await _wait_until(lambda: len(published) == 2)

    published = await _run_watcher(scenario)

    assert len(published) == 2  # l'état de départ, puis l'état final


async def test_notify_does_not_start_a_second_watcher():
    async def scenario(scan, _sync, published):
        scan.update({"status": "running", "items_scanned": 0, "total_items": 3})
        vff_progress.notify_vff_progress()
        first = vff_progress._watcher
        vff_progress.notify_vff_progress()
        vff_progress.notify_vff_progress()
        assert vff_progress._watcher is first
        scan.update({"status": "idle", "finished_at": "2026-01-01T00:00:00"})
        assert await _wait_until(lambda: vff_progress._watcher is None)

    published = await _run_watcher(scenario)
    # Une seule tâche : l'état est passé à idle avant le premier cycle d'observation, donc
    # un unique évènement — trois tâches concurrentes en auraient produit trois.
    assert len(published) == 1


async def test_plex_sync_progress_is_broadcast_too():
    async def scenario(_scan, sync, published):
        sync.update({"status": "running", "items_synced": 0, "total_items": 50})
        vff_progress.notify_vff_progress()
        assert await _wait_until(lambda: len(published) == 1)
        sync["items_synced"] = 25
        assert await _wait_until(lambda: len(published) == 2)
        sync.update({"status": "idle", "finished_at": "2026-01-01T00:00:00"})
        assert await _wait_until(lambda: len(published) == 3)

    published = await _run_watcher(scenario)

    assert published[0][1]["sync"]["items_synced"] == 0
    assert published[1][1]["sync"]["items_synced"] == 25
    assert published[-1][1]["sync"]["status"] == "idle"


async def test_only_sections_this_process_runs_are_mirrored():
    """La tâche publie dans Redis la progression du process qui scanne, pour que l'autre
    la voie. Elle ne doit toucher que les sections qu'elle a vues tourner : le worker,
    dont le dict `sync` local est resté aux valeurs par défaut, effacerait sinon l'état
    d'une synchronisation menée par le conteneur web."""
    written: list[tuple[str, dict, bool]] = []

    async def _fake_write(section, state, *, running):
        written.append((section, dict(state), running))

    async def scenario(scan, _sync, published):
        scan.update({"status": "running", "items_scanned": 0, "total_items": 6})
        vff_progress.notify_vff_progress()
        assert await _wait_until(lambda: len(published) == 1)
        scan.update({"status": "idle", "finished_at": "2026-01-01T00:00:00"})
        assert await _wait_until(lambda: len(published) == 2)

    with patch.object(vff_progress.scan_state, "write_section", _fake_write):
        await _run_watcher(scenario)

    sections = {section for section, _, _ in written}
    assert sections == {"scan"}
    # Le TTL court ne s'applique que tant que ça tourne : l'écriture finale doit être
    # marquée terminée pour être conservée plus longtemps.
    assert written[0][2] is True
    assert written[-1][2] is False
    assert written[-1][1]["status"] == "idle"
