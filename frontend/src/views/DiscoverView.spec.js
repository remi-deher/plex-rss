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

function mountView({ home = false, url = '', attachTo } = {}) {
  window.history.replaceState({}, '', url || (home ? '/discover' : '/discover/explore'));
  return mount(DiscoverView, {
    attachTo,
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
    window.history.replaceState({}, '', '/discover/explore');
    localStorage.clear();
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

  it('conserve le focus du champ partagé lors du passage de l’accueil à Explorer', async () => {
    apiMock.mockImplementation(path => path.includes('/genres') ? Promise.resolve([]) : Promise.resolve(page([])));
    const wrapper = mountView({ home: true, attachTo: document.body });
    await flushPromises();
    const input = wrapper.get('input[type="search"]');

    input.element.focus();
    await input.setValue('dune');

    expect(wrapper.findAll('input[type="search"]')).toHaveLength(1);
    expect(document.activeElement).toBe(input.element);
    wrapper.unmount();
  });

  it('rend les cartes comme de vrais liens accessibles', async () => {
    apiMock.mockImplementation(path => path.includes('/genres') ? Promise.resolve([]) : Promise.resolve(page([media(1, 'Film test')])));
    const wrapper = mountView();
    await flushPromises();

    const card = wrapper.get('.discover-card a.discover-poster-link');
    expect(card.attributes('href')).toContain('/media/discover/1');
    expect(card.attributes('aria-label')).toContain('Film test');
    expect(wrapper.get('img').attributes('alt')).toBe('Affiche de Film test');
  });

  it('charge indépendamment le hero, les rangées et les diffuseurs de l’accueil', async () => {
    apiMock.mockImplementation(path => {
      if (path.includes('sections=hero,trending')) {
        return Promise.resolve({ sections: { hero: { item: media(1, 'À la une') }, trending: { items: [media(1)] } } });
      }
      if (path.includes('/home?sections=')) {
        const name = path.split('sections=')[1];
        return Promise.resolve({ sections: { [name]: { items: name === 'popular_movies' ? [media(2, 'Populaire')] : [] } } });
      }
      if (path.includes('/sources')) {
        return Promise.resolve({ region: 'FR', items: [{ id: 8, kind: 'provider', name: 'Netflix' }] });
      }
      return Promise.resolve(page([]));
    });

    const wrapper = mountView({ home: true });
    await flushPromises();

    expect(wrapper.text()).toContain('À la une');
    expect(wrapper.text()).toContain('Populaire');
    expect(wrapper.text()).toContain('Diffuseurs & studios');
    expect(wrapper.text()).toContain('Netflix');
  });

  it('demande directement un média sans langue, profil ni dossier', async () => {
    apiMock.mockImplementation((path, options) => {
      if (path.includes('/genres')) return Promise.resolve([]);
      if (path === '/api/session') return Promise.resolve({ plex_user_id: 'user-1' });
      if (path === '/api/media/add') return Promise.resolve({ request_id: 9, pending_approval: false });
      return Promise.resolve(page([media(1, 'Film test')]));
    });
    const wrapper = mountView();
    await flushPromises();

    await wrapper.get('button[aria-label="Demander Film test"]').trigger('click');
    await flushPromises();

    const [, options] = apiMock.mock.calls.find(([path]) => path === '/api/media/add');
    const body = JSON.parse(options.body);
    expect(body.plex_user_id).toBe('user-1');
    expect(body.auto_search).toBe(true);
    expect(body).not.toHaveProperty('quality_profile_id');
    expect(body).not.toHaveProperty('root_folder');
    expect(body).not.toHaveProperty('seasons');
    expect(wrapper.text()).toContain('Demandé');
  });

  it('restaure les filtres Explorer depuis une URL partageable', async () => {
    apiMock.mockImplementation(path => {
      if (path.includes('/genres')) return Promise.resolve([]);
      if (path.includes('/sources')) return Promise.resolve({ region: 'FR', items: [{ id: 8, kind: 'provider', name: 'Netflix' }] });
      if (path.includes('/source/provider/8')) return Promise.resolve(page([media(8, 'Netflix movie')]));
      return Promise.resolve(page([]));
    });

    const wrapper = mountView({ url: '/discover/explore?type=movie&availability=new&source=provider%3A8' });
    await flushPromises();

    expect(wrapper.text()).toContain('Netflix movie');
    expect(wrapper.get('select[aria-label="Diffuseur ou studio"]').element.value).toBe('provider:8');
    expect(apiMock.mock.calls.some(([path]) => path.includes('/source/provider/8?media_type=movie'))).toBe(true);
    expect(window.location.pathname).toBe('/discover/explore');
    expect(window.location.search).toContain('availability=new');
  });

  it('affiche les recommandations personnalisées sans bloquer les autres rangées', async () => {
    apiMock.mockImplementation(path => {
      if (path.includes('/personalized')) {
        return Promise.resolve({
          available: true,
          seeds: [media(1, 'Dune')],
          sections: {
            recommended: { items: [media(2, 'Arrival')] },
            preferred_genres: { items: [] },
            unwatched_popular: { items: [] },
            followed_series: { items: [] },
          },
        });
      }
      if (path.includes('sections=hero,trending')) return Promise.resolve({ sections: { hero: { item: media(3) }, trending: { items: [] } } });
      if (path.includes('/home?sections=')) {
        const name = path.split('sections=')[1];
        return Promise.resolve({ sections: { [name]: { items: [] } } });
      }
      if (path.includes('/sources')) return Promise.resolve({ region: 'FR', items: [] });
      return Promise.resolve(page([]));
    });

    const wrapper = mountView({ home: true });
    await flushPromises();

    expect(wrapper.text()).toContain('Pour vous');
    expect(wrapper.text()).toContain('Inspiré par Dune');
    expect(wrapper.text()).toContain('Arrival');
  });
});
