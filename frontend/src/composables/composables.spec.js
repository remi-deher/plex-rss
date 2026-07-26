import { mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useDebounced } from './useDebounced';
import { useLatestRequest } from './useLatestRequest';
import { usePolling } from './usePolling';

/** Monte un composant minimal pour disposer d'un contexte de cycle de vie. */
function withSetup(composable) {
  let result;
  const wrapper = mount({
    setup() {
      result = composable();
      return () => null;
    },
  });
  return { result, wrapper };
}

describe('useLatestRequest', () => {
  it('abandonne la requête précédente à chaque nouveau begin()', () => {
    const { result } = withSetup(useLatestRequest);
    const first = result.begin();
    expect(first.signal.aborted).toBe(false);

    const second = result.begin();
    expect(first.signal.aborted).toBe(true);
    expect(second.signal.aborted).toBe(false);
  });

  // Le point clé : une réponse peut revenir après l'abandon, ou deux chargements
  // concurrents dans le désordre. Seul le dernier doit pouvoir écrire dans l'état.
  it('ne reconnaît comme courante que la dernière demande', () => {
    const { result } = withSetup(useLatestRequest);
    const first = result.begin();
    expect(first.isCurrent()).toBe(true);

    const second = result.begin();
    expect(first.isCurrent()).toBe(false);
    expect(second.isCurrent()).toBe(true);
  });

  it('extend() garde le signal en cours mais prend un nouveau jeton', () => {
    const { result } = withSetup(useLatestRequest);
    const page1 = result.begin();
    const page2 = result.extend();

    // La page déjà demandée ne doit pas être annulée par « charger plus ».
    expect(page1.signal.aborted).toBe(false);
    expect(page2.signal).toBe(page1.signal);
    expect(page1.isCurrent()).toBe(false);
    expect(page2.isCurrent()).toBe(true);

    // …mais un rechargement complet survenu entre-temps invalide bien la pagination.
    const reload = result.begin();
    expect(page2.isCurrent()).toBe(false);
    expect(reload.isCurrent()).toBe(true);
  });

  it('abort() annule sans repartir, et le démontage annule aussi', () => {
    const { result, wrapper } = withSetup(useLatestRequest);
    const inflight = result.begin();
    result.abort();
    expect(inflight.signal.aborted).toBe(true);

    const { result: other, wrapper: otherWrapper } = withSetup(useLatestRequest);
    const pending = other.begin();
    otherWrapper.unmount();
    expect(pending.signal.aborted).toBe(true);
    wrapper.unmount();
  });

  it('reconnaît une AbortError', () => {
    const { result } = withSetup(useLatestRequest);
    expect(result.isAbort({ name: 'AbortError' })).toBe(true);
    expect(result.isAbort(new Error('réseau'))).toBe(false);
    expect(result.isAbort(undefined)).toBe(false);
  });
});

describe('usePolling', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('appelle le callback à chaque période et s’arrête au démontage', () => {
    const tick = vi.fn();
    const { wrapper } = withSetup(() => usePolling(tick, 1000));
    expect(tick).not.toHaveBeenCalled();

    vi.advanceTimersByTime(2500);
    expect(tick).toHaveBeenCalledTimes(2);

    wrapper.unmount();
    vi.advanceTimersByTime(5000);
    expect(tick).toHaveBeenCalledTimes(2);
  });

  it('saute les ticks quand l’onglet est masqué', () => {
    const tick = vi.fn();
    const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
    const { wrapper } = withSetup(() => usePolling(tick, 1000));

    vi.advanceTimersByTime(3000);
    expect(tick).not.toHaveBeenCalled();

    hidden.mockReturnValue(false);
    vi.advanceTimersByTime(1000);
    expect(tick).toHaveBeenCalledTimes(1);
    wrapper.unmount();
    hidden.mockRestore();
  });

  // Une horloge locale (compte à rebours, « actualisé il y a N s ») doit avancer même
  // onglet masqué, sinon l'affichage est faux au retour sur l'onglet.
  it('tourne malgré tout avec whenVisible: false', () => {
    const tick = vi.fn();
    const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
    const { wrapper } = withSetup(() => usePolling(tick, 1000, { whenVisible: false }));

    vi.advanceTimersByTime(3000);
    expect(tick).toHaveBeenCalledTimes(3);
    wrapper.unmount();
    hidden.mockRestore();
  });

  it('déclenche un premier appel immédiat si demandé', () => {
    const tick = vi.fn();
    const { wrapper } = withSetup(() => usePolling(tick, 1000, { immediate: true }));
    expect(tick).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });
});

describe('useDebounced', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('ne garde que le dernier appel de la salve', () => {
    const run = vi.fn();
    const { result, wrapper } = withSetup(() => useDebounced(run, 300));

    result('a');
    result('ab');
    result('abc');
    vi.advanceTimersByTime(299);
    expect(run).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    expect(run).toHaveBeenCalledExactlyOnceWith('abc');
    wrapper.unmount();
  });

  it('cancel() abandonne l’appel en attente', () => {
    const run = vi.fn();
    const { result, wrapper } = withSetup(() => useDebounced(run, 300));
    result();
    result.cancel();
    vi.advanceTimersByTime(1000);
    expect(run).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('flush() exécute tout de suite, une seule fois', () => {
    const run = vi.fn();
    const { result, wrapper } = withSetup(() => useDebounced(run, 300));
    result('x');
    result.flush('y');
    expect(run).toHaveBeenCalledExactlyOnceWith('y');
    vi.advanceTimersByTime(1000);
    expect(run).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  // Sans annulation au démontage, quitter la page pendant le délai déclenchait un appel
  // sur un composant déjà démonté.
  it('annule au démontage', () => {
    const run = vi.fn();
    const { result, wrapper } = withSetup(() => useDebounced(run, 300));
    result();
    wrapper.unmount();
    vi.advanceTimersByTime(1000);
    expect(run).not.toHaveBeenCalled();
  });
});
