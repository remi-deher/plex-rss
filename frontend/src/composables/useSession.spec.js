import { mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.fn();
vi.mock('@/api', () => ({ api: (...args) => api(...args) }));

// Le cache vit au niveau du module : chaque test le recharge pour repartir à zéro.
async function freshModule() {
  vi.resetModules();
  return import('./useSession');
}

// Implémentation par défaut résolue : sans elle, un appel résiduel d'un test précédent
// hériterait du rejet du test en cours et remonterait en rejet non géré.
beforeEach(() => {
  api.mockReset();
  api.mockResolvedValue(null);
});

describe('isAdminSession', () => {
  it('reconnaît le propriétaire et le rôle admin, rien d’autre', async () => {
    const { isAdminSession } = await freshModule();
    expect(isAdminSession({ is_owner: true })).toBe(true);
    expect(isAdminSession({ role: 'admin' })).toBe(true);
    expect(isAdminSession({ role: 'user' })).toBe(false);
    expect(isAdminSession(null)).toBe(false);
    expect(isAdminSession(undefined)).toBe(false);
  });
});

describe('isModeratorSession / canModerateSession', () => {
  it('isModeratorSession ne reconnaît que le rôle moderator', async () => {
    const { isModeratorSession } = await freshModule();
    expect(isModeratorSession({ role: 'moderator' })).toBe(true);
    expect(isModeratorSession({ role: 'admin' })).toBe(false);
    expect(isModeratorSession({ role: 'user' })).toBe(false);
    expect(isModeratorSession(null)).toBe(false);
  });

  it('canModerateSession accepte admin, owner et moderator, rien d’autre', async () => {
    const { canModerateSession } = await freshModule();
    expect(canModerateSession({ is_owner: true })).toBe(true);
    expect(canModerateSession({ role: 'admin' })).toBe(true);
    expect(canModerateSession({ role: 'moderator' })).toBe(true);
    expect(canModerateSession({ role: 'user' })).toBe(false);
    expect(canModerateSession(null)).toBe(false);
  });
});

describe('loadSession', () => {
  // Trois vues appelaient /api/session séparément, et la fiche média la relançait à chaque
  // changement de route : c'est précisément ce que la mémoïsation supprime.
  it('n’interroge l’API qu’une fois, même sur appels concurrents', async () => {
    const { loadSession } = await freshModule();
    api.mockResolvedValue({ id: 1, role: 'admin' });

    const [a, b] = await Promise.all([loadSession(), loadSession()]);
    const c = await loadSession();

    expect(api).toHaveBeenCalledExactlyOnceWith('/api/session');
    expect(a).toEqual({ id: 1, role: 'admin' });
    expect(b).toBe(a);
    expect(c).toBe(a);
  });

  it('renvoie null sans lever quand l’utilisateur n’est pas authentifié', async () => {
    const { loadSession } = await freshModule();
    // mockRejectedValue crée la promesse rejetée immédiatement, que vitest signale
    // comme non gérée avant que loadSession ne l'attrape : on la crée à l'appel.
    api.mockImplementation(() => Promise.reject(new Error('HTTP 401')));
    await expect(loadSession()).resolves.toBeNull();
  });

  it('invalidateSession() force un nouvel appel', async () => {
    const { loadSession, invalidateSession } = await freshModule();
    api.mockResolvedValue({ id: 1 });
    await loadSession();
    invalidateSession();
    await loadSession();
    expect(api).toHaveBeenCalledTimes(2);
  });
});

describe('useSession', () => {
  it('expose la session, le drapeau admin et l’état de chargement', async () => {
    const { useSession } = await freshModule();
    api.mockResolvedValue({ id: 7, is_owner: true });

    let state;
    mount({
      setup() {
        state = useSession();
        return () => null;
      },
    });

    expect(state.ready.value).toBe(false);
    expect(state.isAdmin.value).toBe(false);

    await vi.waitUntil(() => state.ready.value);
    expect(state.session.value).toEqual({ id: 7, is_owner: true });
    expect(state.isAdmin.value).toBe(true);
  });

  it('reste inerte pour un visiteur non authentifié', async () => {
    const { useSession } = await freshModule();
    // mockRejectedValue crée la promesse rejetée immédiatement, que vitest signale
    // comme non gérée avant que loadSession ne l'attrape : on la crée à l'appel.
    api.mockImplementation(() => Promise.reject(new Error('HTTP 401')));

    let state;
    mount({
      setup() {
        state = useSession();
        return () => null;
      },
    });

    await vi.waitUntil(() => state.ready.value);
    expect(state.session.value).toBeNull();
    expect(state.isAdmin.value).toBe(false);
  });
});
