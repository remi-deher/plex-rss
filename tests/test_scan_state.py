"""Tests de l'état de scan partagé entre process (app/services/scan_state.py).

Le scénario reproduit ici est celui de la production : le cron ARQ lance un scan dans le
conteneur worker, et le conteneur web — qui sert `/api/vff/scan-status` — n'en voit rien
puisque le dict de progression vit dans la mémoire d'un seul process.
"""

import json
from unittest.mock import patch

import pytest

from app.services import scan_state

RUNNING = {"status": "running", "items_scanned": 12, "total_items": 40, "error": None}
IDLE = {"status": "idle", "items_scanned": 0, "total_items": 0, "finished_at": None}


class FakeRedis:
    """Redis en mémoire, partagé par les deux « process » du test."""

    def __init__(self, store):
        self.store = store

    async def set(self, key, value, ex=None):
        self.store[key] = (value, ex)

    async def get(self, key):
        entry = self.store.get(key)
        return entry[0] if entry else None

    async def delete(self, key):
        self.store.pop(key, None)

    async def aclose(self):
        pass


@pytest.fixture()
def shared_redis():
    """Branche scan_state sur un Redis factice et retourne son magasin."""
    store: dict[str, tuple[str, int | None]] = {}

    async def _client():
        return FakeRedis(store)

    with patch.object(scan_state, "_client", _client):
        yield store


async def test_worker_scan_is_visible_from_the_other_process(shared_redis):
    # Process « worker » : son dict local tourne, il publie sa progression.
    await scan_state.write_section("scan", RUNNING, running=True)

    # Process « web » : son propre dict local est au repos.
    local_web = dict(IDLE)
    resolved = await scan_state.resolve("scan", local_web)

    assert resolved["status"] == "running"
    assert resolved["items_scanned"] == 12
    assert await scan_state.is_running("scan", local_web) is True


async def test_local_run_takes_precedence_over_the_shared_copy(shared_redis):
    """Le dict local d'un process qui scanne est mis à jour en continu ; la copie Redis a
    jusqu'à un cycle de retard. C'est donc le local qui fait autorité."""
    await scan_state.write_section("scan", {**RUNNING, "items_scanned": 12}, running=True)

    local = {**RUNNING, "items_scanned": 30}
    resolved = await scan_state.resolve("scan", local)

    assert resolved["items_scanned"] == 30


async def test_falls_back_to_local_state_without_shared_copy(shared_redis):
    local = dict(IDLE)
    assert await scan_state.resolve("scan", local) == local
    assert await scan_state.is_running("scan", local) is False


async def test_running_copy_expires_so_a_crashed_process_does_not_block_forever(shared_redis):
    """Le TTL court est le filet de sécurité : un process tué en plein scan laisserait
    sinon un « running » définitif, qui empêcherait tout scan ultérieur."""
    await scan_state.write_section("scan", RUNNING, running=True)
    _, ttl_running = shared_redis["plexarr:scan-state:v1:scan"]
    assert ttl_running == scan_state._RUNNING_TTL_SECONDS

    # Expiration simulée : la clé disparaît, la lecture retombe sur le local au repos.
    shared_redis.clear()
    local = dict(IDLE)
    assert await scan_state.is_running("scan", local) is False


async def test_finished_state_is_kept_longer_than_a_running_one(shared_redis):
    """Une fois terminé, plus personne ne rafraîchit : la copie doit survivre assez
    longtemps pour afficher « terminé il y a X »."""
    await scan_state.write_section("scan", {**IDLE, "finished_at": "2026-01-01T00:00:00"}, running=False)
    _, ttl = shared_redis["plexarr:scan-state:v1:scan"]
    assert ttl == scan_state._FINISHED_TTL_SECONDS
    assert ttl > scan_state._RUNNING_TTL_SECONDS


async def test_sections_do_not_overwrite_each_other(shared_redis):
    """Une section par clé : le worker qui publie « scan » ne doit pas effacer l'état
    d'une synchronisation menée par le conteneur web."""
    await scan_state.write_section("sync", {**RUNNING, "items_synced": 5}, running=True)
    await scan_state.write_section("scan", RUNNING, running=True)

    sync = await scan_state.resolve("sync", dict(IDLE))
    assert sync["items_synced"] == 5


async def test_without_redis_everything_falls_back_to_local(shared_redis):
    """Déploiement mono-process sans Redis : aucune régression, l'état local suffit."""

    async def _no_client():
        return None

    with patch.object(scan_state, "_client", _no_client):
        await scan_state.write_section("scan", RUNNING, running=True)  # ne doit pas lever
        assert await scan_state.read_section("scan") is None
        assert await scan_state.resolve("scan", dict(IDLE)) == IDLE
        assert await scan_state.is_running("scan", dict(RUNNING)) is True


async def test_corrupted_shared_copy_is_ignored(shared_redis):
    shared_redis["plexarr:scan-state:v1:scan"] = ("{pas du json", None)
    local = dict(IDLE)
    assert await scan_state.read_section("scan") is None
    assert await scan_state.resolve("scan", local) == local


async def test_written_payload_is_the_full_state(shared_redis):
    await scan_state.write_section("scan", RUNNING, running=True)
    raw, _ = shared_redis["plexarr:scan-state:v1:scan"]
    assert json.loads(raw) == RUNNING
