"""Tests pour app/cache.py, en particulier Cache.get_or_refresh (stale-while-revalidate)."""

import asyncio

import pytest

from app.cache import Cache


@pytest.mark.asyncio
async def test_get_or_refresh_computes_synchronously_on_cold_cache():
    cache = Cache()
    calls = []

    async def compute():
        calls.append(1)
        return {"n": len(calls)}

    result = await cache.get_or_refresh("k", soft_ttl_seconds=60, hard_ttl_seconds=600, compute_sync=compute)
    assert result == {"n": 1}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_get_or_refresh_serves_cached_value_within_soft_ttl_without_recomputing():
    cache = Cache()
    calls = []

    async def compute():
        calls.append(1)
        return {"n": len(calls)}

    first = await cache.get_or_refresh("k", soft_ttl_seconds=60, hard_ttl_seconds=600, compute_sync=compute)
    second = await cache.get_or_refresh("k", soft_ttl_seconds=60, hard_ttl_seconds=600, compute_sync=compute)
    assert first == second == {"n": 1}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_get_or_refresh_serves_stale_value_immediately_and_refreshes_in_background():
    """Passe soft_ttl : la valeur perimee doit etre renvoyee IMMEDIATEMENT (jamais
    d'attente sur le recalcul), pendant qu'un rafraichissement tourne en tache de
    fond et alimente le PROCHAIN appel."""
    cache = Cache()
    calls = []

    async def compute():
        calls.append(1)
        return {"n": len(calls)}

    first = await cache.get_or_refresh("k", soft_ttl_seconds=0, hard_ttl_seconds=600, compute_sync=compute)
    assert first == {"n": 1}

    # soft_ttl_seconds=0 : la valeur est deja "perimee" des le prochain appel.
    second = await cache.get_or_refresh("k", soft_ttl_seconds=0, hard_ttl_seconds=600, compute_sync=compute)
    assert second == {"n": 1}  # valeur perimee servie sans attendre le recalcul

    # Laisse la tache de fond se terminer, puis verifie qu'elle a bien recalcule.
    await asyncio.sleep(0.05)
    assert len(calls) == 2
    third = await cache.get_or_refresh("k", soft_ttl_seconds=60, hard_ttl_seconds=600, compute_sync=compute)
    assert third == {"n": 2}


@pytest.mark.asyncio
async def test_get_or_refresh_uses_compute_background_for_stale_refresh():
    """compute_background (pas compute_sync) doit etre utilise pour le
    rafraichissement en arriere-plan -- important car compute_sync peut fermer sur
    des ressources liees a la requete d'origine (ex: session DB) qui ne sont plus
    valides une fois la reponse HTTP repartie."""
    cache = Cache()
    sync_calls, background_calls = [], []

    async def compute_sync():
        sync_calls.append(1)
        return {"source": "sync"}

    async def compute_background():
        background_calls.append(1)
        return {"source": "background"}

    await cache.get_or_refresh("k", 0, 600, compute_sync=compute_sync, compute_background=compute_background)
    await cache.get_or_refresh("k", 0, 600, compute_sync=compute_sync, compute_background=compute_background)
    await asyncio.sleep(0.05)

    assert len(sync_calls) == 1
    assert len(background_calls) == 1


@pytest.mark.asyncio
async def test_get_or_refresh_does_not_duplicate_concurrent_background_refreshes():
    """Deux appels concurrents sur une valeur perimee ne doivent lancer qu'UN SEUL
    rafraichissement en arriere-plan, pas un par appel."""
    cache = Cache()
    calls = []

    async def compute():
        calls.append(1)
        await asyncio.sleep(0.02)
        return {"n": len(calls)}

    await cache.get_or_refresh("k", 0, 600, compute_sync=compute)
    await asyncio.gather(
        cache.get_or_refresh("k", 0, 600, compute_sync=compute),
        cache.get_or_refresh("k", 0, 600, compute_sync=compute),
    )
    await asyncio.sleep(0.05)
    assert len(calls) == 2  # 1 premier calcul synchrone + 1 seul rafraichissement de fond
