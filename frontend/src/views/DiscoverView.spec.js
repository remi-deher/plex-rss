import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import DiscoverView from './DiscoverView.vue';

const apiMock = vi.fn();
vi.mock('@/api', () => ({ api: (...args) => apiMock(...args) }));

const page = (items, current = 1, total = 1) => ({
  items,
  page: current,
  total_pages: total,
  total_results: items.length + (total - current) * 20,
});

function media(id, title = `Média ${id}`) {
  return { tmdb_id: id, media_type: 'movie', title, year: 2025, vote: 7, poster_url: `/poster-${id}.jpg` };
}

function mountView() {
  return mount(DiscoverView, {
    global: {
      stubs: {
        PageHeader: true,
        UiFeedback: true,
        RouterLink: {
          props: ['to'],
          template: '<a :href="to"><slot /></a>',
        },
      },
    },
  });
}

describe('DiscoverView', () => {
  beforeEach(() => {
    apiMock.mockReset();
    window.matchMedia = vi.fn(() => ({ matches: false }));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('charge progressivement les pages suivantes sans doublon', async () => {
    apiMock.mockImplementation(path => {
      if (path.includes('/genres')) return Promise.resolve([]);
      if (path.includes('page=2')) return Promise.resolve(page([media(2), media(3)], 2, 2));
      return Promise.resolve(page([media(1), media(2)], 1, 2));
    });
    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.findAll('.discover-card')).toHaveLength(2);
    await wrapper.get('.load-more button').trigger('click');
    await flushPromises();

    expect(wrapper.findAll('.discover-card')).toHaveLength(3);
    expect(wrapper.find('.load-more').exists()).toBe(false);
  });

  it('applique le type de média aux recherches et aux catalogues', async () => {
    apiMock.mockImplementation(path => path.includes('/genres') ? Promise.resolve([]) : Promise.resolve(page([])));
    const wrapper = mountView();
    await flushPromises();

    const films = wrapper.findAll('.segmented button').find(button => button.text() === 'Films');
    await films.trigger('click');
    await flushPromises();

    expect(apiMock.mock.calls.some(([path]) => path.includes('/trending?media_type=movie'))).toBe(true);
  });

  it('ignore une réponse de recherche arrivée après une requête plus récente', async () => {
    vi.useFakeTimers();
    let resolveOld;
    let resolveNew;
    apiMock.mockImplementation(path => {
      if (path.includes('/genres')) return Promise.resolve([]);
      if (!path.includes('/search')) return Promise.resolve(page([]));
      if (path.includes('ancien')) return new Promise(resolve => { resolveOld = resolve; });
      return new Promise(resolve => { resolveNew = resolve; });
    });
    const wrapper = mountView();
    await flushPromises();
    const input = wrapper.get('input[type="search"]');

    await input.setValue('ancien');
    await vi.advanceTimersByTimeAsync(300);
    await input.setValue('nouveau');
    await vi.advanceTimersByTimeAsync(300);

    resolveNew(page([media(2, 'Nouveau')]));
    await flushPromises();
    resolveOld(page([media(1, 'Ancien')]));
    await flushPromises();

    expect(wrapper.text()).toContain('Nouveau');
    expect(wrapper.text()).not.toContain('Ancien');
  });

  it('rend les cartes comme de vrais liens accessibles', async () => {
    apiMock.mockImplementation(path => path.includes('/genres') ? Promise.resolve([]) : Promise.resolve(page([media(1, 'Film test')])));
    const wrapper = mountView();
    await flushPromises();

    const card = wrapper.get('a.discover-card');
    expect(card.attributes('href')).toContain('/media/discover/1');
    expect(card.attributes('aria-label')).toContain('Film test');
    expect(wrapper.get('img').attributes('alt')).toBe('Affiche de Film test');
  });
});
