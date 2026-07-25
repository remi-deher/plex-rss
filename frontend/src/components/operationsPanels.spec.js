import { mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import DownloadQueuePanel from './dashboard/DownloadQueuePanel.vue';
import LibraryCard from './library/LibraryCard.vue';

vi.mock('@/api', () => ({ api: vi.fn() }));

const routerPush = vi.fn();
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerPush }),
}));

const RouterLink = {
  props: ['to'],
  template: '<a :href="typeof to === \'string\' ? to : to?.path"><slot /></a>',
};

describe('panneaux opérationnels', () => {
  it('rend une entrée liée de téléchargement comme lien vers sa fiche', () => {
    const wrapper = mount(DownloadQueuePanel, {
      props: {
        queue: [{ queue_id: 4, instance_id: 2, title: 'Film', request_id: 12, status: 'downloading' }],
      },
      global: { stubs: { RouterLink } },
    });

    expect(wrapper.get('a.queue-row').attributes('href')).toBe('/media/request/12');
  });

  it('utilise une clé stable même sans identifiant générique', () => {
    const wrapper = mount(DownloadQueuePanel, {
      props: {
        queue: [
          { queue_id: 1, instance_id: 2, title: 'A' },
          { queue_id: 2, instance_id: 2, title: 'B' },
        ],
      },
      global: { stubs: { RouterLink } },
    });

    expect(wrapper.findAll('.detail-row')).toHaveLength(2);
  });

  it('ouvre une carte de bibliothèque avec Entrée ou Espace', async () => {
    const item = { id: 1, _kind: 'library', title: 'Film test', media_type: 'movie' };
    const wrapper = mount(LibraryCard, {
      props: { item },
      global: { stubs: { MediaPoster: { template: '<div><slot name="badges" /></div>' } } },
    });

    await wrapper.trigger('keydown', { key: ' ' });
    expect(wrapper.emitted('open')).toHaveLength(1);
    expect(wrapper.attributes('role')).toBe('link');
    expect(wrapper.attributes('aria-label')).toContain('Film test');
  });

  it('désactive les actions pendant une opération de masse', () => {
    const item = { id: 1, _kind: 'request', title: 'Film test', media_type: 'movie', status: 'failed', arr_id: 8 };
    const wrapper = mount(LibraryCard, {
      props: { item, isAdmin: true, busy: true },
      global: { stubs: { MediaPoster: { template: '<div><slot name="badges" /></div>' } } },
    });

    expect(wrapper.findAll('button').every(button => button.attributes('disabled') !== undefined)).toBe(true);
    expect(wrapper.get('input[type="checkbox"]').attributes('disabled')).toBeDefined();
  });
});
