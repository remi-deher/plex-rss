/**
 * Sous 640px la grille mensuelle ne tient pas et etait masquee en CSS, alors que
 * le bouton « Mois » restait affiche : le taper vidait la page. Le selecteur est
 * desormais retire en mode compact et la vue retombe sur l'agenda, y compris
 * quand une preference « mois » vient d'un usage sur grand ecran.
 */
import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import CalendarView from './CalendarView.vue';

const apiMock = vi.fn();
vi.mock('@/api', () => ({ api: (...args) => apiMock(...args) }));
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }));

let listeners = [];
let viewportWidth = 1280;

// `matches` est un getter : le composant conserve le MediaQueryList obtenu au
// montage, il doit donc voir les changements de largeur ulterieurs.
window.matchMedia = query => ({
  media: query,
  get matches() {
    return /max-width: ?640px/.test(query) ? viewportWidth <= 640 : false;
  },
  addEventListener: (_event, handler) => listeners.push(handler),
  removeEventListener: (_event, handler) => {
    listeners = listeners.filter(entry => entry !== handler);
  },
  addListener: () => {},
  removeListener: () => {},
  onchange: null,
  dispatchEvent: () => false,
});

function setViewport(width) {
  viewportWidth = width;
}

function mountView() {
  return mount(CalendarView, {
    global: {
      stubs: { PageHeader: true, UiFeedback: true, FilterBar: true },
    },
  });
}

beforeEach(() => {
  listeners = [];
  localStorage.clear();
  apiMock.mockReset();
  apiMock.mockResolvedValue([]);
});

describe('CalendarView', () => {
  it('retire le selecteur de vue sous 640px', async () => {
    setViewport(375);
    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.find('.calendar-view-switch').exists()).toBe(false);
    expect(wrapper.find('.month-calendar-shell').exists()).toBe(false);
    expect(wrapper.find('.calendar-agenda').exists()).toBe(true);
    wrapper.unmount();
  });

  it('ignore une preference « mois » heritee du grand ecran en mode compact', async () => {
    localStorage.setItem('calendar.view', 'month');
    setViewport(375);
    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.find('.month-calendar-shell').exists()).toBe(false);
    expect(wrapper.find('.calendar-agenda').exists()).toBe(true);
    // La preference reste intacte pour le prochain passage sur grand ecran.
    expect(localStorage.getItem('calendar.view')).toBe('month');
    wrapper.unmount();
  });

  it('rend le selecteur et la grille mensuelle au-dessus de 640px', async () => {
    localStorage.setItem('calendar.view', 'month');
    setViewport(1280);
    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.find('.calendar-view-switch').exists()).toBe(true);
    expect(wrapper.find('.month-calendar-shell').exists()).toBe(true);
    expect(wrapper.findAll('.month-cell')).toHaveLength(42);
    wrapper.unmount();
  });

  it('bascule sur l’agenda quand la fenetre passe sous 640px', async () => {
    localStorage.setItem('calendar.view', 'month');
    setViewport(1280);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('.month-calendar-shell').exists()).toBe(true);

    setViewport(375);
    listeners.forEach(handler => handler({ matches: true }));
    await flushPromises();

    expect(wrapper.find('.calendar-view-switch').exists()).toBe(false);
    expect(wrapper.find('.month-calendar-shell').exists()).toBe(false);
    expect(wrapper.find('.calendar-agenda').exists()).toBe(true);
    wrapper.unmount();
  });
});
