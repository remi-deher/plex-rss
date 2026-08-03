import { beforeEach, describe, expect, it, vi } from 'vitest';

import { clearCache, dropCache, readCache, readCacheEntry, syncCacheOwner, writeCache } from './cache';

describe('cache SWR', () => {
  beforeEach(() => {
    sessionStorage.clear();
    clearCache();
    vi.useRealTimers();
  });

  it('relit une valeur ecrite', () => {
    writeCache('vue', { total: 3 });
    expect(readCache('vue')).toEqual({ total: 3 });
  });

  it('survit a la perte du cache memoire (rechargement de page)', () => {
    writeCache('vue', { total: 3 });
    // Simule un F5 : le module est reevalue, seul sessionStorage subsiste.
    clearMemoryOnly();
    expect(readCache('vue')).toEqual({ total: 3 });
  });

  it('refuse une entree plus vieille que maxAgeMs', () => {
    writeCache('vue', { total: 3 });
    expect(readCache('vue', { maxAgeMs: 60_000 })).toEqual({ total: 3 });

    vi.useFakeTimers();
    vi.setSystemTime(Date.now() + 120_000);
    expect(readCache('vue', { maxAgeMs: 60_000 })).toBeNull();
    // L'entree perimee est purgee, pas seulement ignoree.
    expect(sessionStorage.getItem('plexarr:swr:vue')).toBeNull();
  });

  it('expose la date d’enregistrement pour afficher un age honnete', () => {
    const before = Date.now();
    writeCache('vue', { total: 3 });
    const entry = readCacheEntry('vue');
    expect(entry.data).toEqual({ total: 3 });
    expect(entry.savedAt).toBeGreaterThanOrEqual(before);
  });

  it('dropCache ne supprime que la cle visee', () => {
    writeCache('a', 1);
    writeCache('b', 2);
    dropCache('a');
    expect(readCache('a')).toBeNull();
    expect(readCache('b')).toBe(2);
  });

  it('ignore une entree corrompue sans lever', () => {
    sessionStorage.setItem('plexarr:swr:vue', '{pas du json');
    expect(readCache('vue')).toBeNull();
  });

  it('purge tout au changement de compte dans le meme onglet', () => {
    syncCacheOwner({ id: 7 });
    writeCache('vue', { total: 3 });

    // Deconnexion puis reconnexion avec un autre compte : sessionStorage a survecu a la
    // navigation pleine page vers /logout, les donnees du precedent ne doivent pas
    // reapparaitre.
    syncCacheOwner({ id: 42 });
    expect(readCache('vue')).toBeNull();
  });

  it('conserve le cache quand c’est le meme compte', () => {
    syncCacheOwner({ id: 7 });
    writeCache('vue', { total: 3 });
    syncCacheOwner({ id: 7 });
    expect(readCache('vue')).toEqual({ total: 3 });
  });

  it('clearCache vide memoire et stockage', () => {
    writeCache('vue', { total: 3 });
    clearCache();
    expect(readCache('vue')).toBeNull();
    expect(sessionStorage.getItem('plexarr:swr:vue')).toBeNull();
  });
});

/** Vide le cache memoire en laissant sessionStorage intact. */
function clearMemoryOnly() {
  const saved = { ...sessionStorage };
  clearCache();
  for (const [key, value] of Object.entries(saved)) sessionStorage.setItem(key, value);
}
