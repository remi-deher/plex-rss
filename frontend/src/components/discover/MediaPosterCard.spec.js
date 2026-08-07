import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import MediaPosterCard from './MediaPosterCard.vue';

function mountCard(item = {}) {
  return mount(MediaPosterCard, {
    props: {
      item: { tmdb_id: 42, media_type: 'movie', title: 'Film test', year: 2026, poster_url: '/poster.jpg', ...item },
      to: '/media/discover/42',
      actionLabel: 'Demander',
    },
    global: {
      stubs: {
        RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' },
      },
    },
  });
}

describe('MediaPosterCard', () => {
  it('rend une carte accessible et son action', () => {
    const wrapper = mountCard();

    expect(wrapper.get('.discover-poster-link').attributes('aria-label')).toContain('Film test');
    expect(wrapper.get('img').attributes('alt')).toBe('Affiche de Film test');
    expect(wrapper.get('.discover-card-overlay').text()).not.toContain('Film test');
    expect(wrapper.get('.discover-card-overlay').text()).toContain('2026');
    expect(wrapper.find('.discover-info-link').exists()).toBe(false);
    expect(wrapper.text()).toContain('Demander');
  });

  it('ne rend jamais les marqueurs VF ou VO de la donnée source', () => {
    const wrapper = mountCard({ in_library: true, has_vf: false });

    expect(wrapper.text()).toContain('Dans Plex');
    expect(wrapper.text()).not.toContain('VF');
    expect(wrapper.text()).not.toContain('VO');
  });

  it('émet une demande depuis un bouton distinct du lien de fiche', async () => {
    const wrapper = mount(MediaPosterCard, {
      props: {
        item: { tmdb_id: 42, media_type: 'movie', title: 'Film test' },
        to: '/media/discover/42',
        actionLabel: 'Demander',
        requestable: true,
      },
      global: { stubs: { RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' } } },
    });

    await wrapper.get('button[aria-label="Demander Film test"]').trigger('click');

    expect(wrapper.emitted('request')).toHaveLength(1);
  });
});
