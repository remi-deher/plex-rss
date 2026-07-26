import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import RecentlyAvailablePanel from './RecentlyAvailablePanel.vue';

const RouterLink = {
  props: ['to'],
  template: '<a :href="to"><slot /></a>',
};

describe('RecentlyAvailablePanel', () => {
  it('utilise l’identifiant de bibliothèque quand la demande est liée', () => {
    const wrapper = mount(RecentlyAvailablePanel, {
      props: {
        items: [{ id: 12, request_id: 12, library_id: 98, title: 'Film lié', media_type: 'movie' }],
      },
      global: { stubs: { RouterLink } },
    });

    expect(wrapper.get('a.recent-link').attributes('href')).toBe('/media/library/98');
  });

  it('revient à la fiche de demande quand aucun élément de bibliothèque n’est lié', () => {
    const wrapper = mount(RecentlyAvailablePanel, {
      props: {
        items: [{ id: 13, request_id: 13, library_id: null, title: 'Série non liée', media_type: 'show' }],
      },
      global: { stubs: { RouterLink } },
    });

    expect(wrapper.get('a.recent-link').attributes('href')).toBe('/media/request/13');
  });
});
