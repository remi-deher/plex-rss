import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import MediaStatusBadge from './MediaStatusBadge.vue';

const render = item => mount(MediaStatusBadge, { props: { item } });

describe('MediaStatusBadge', () => {
  it('affiche uniquement la présence Plex même si des données de langue existent', () => {
    const wrapper = render({ in_library: true, has_vf: true, vf_granularity: 'complete' });

    expect(wrapper.text()).toBe('Dans Plex');
    expect(wrapper.text()).not.toContain('VF');
    expect(wrapper.findAll('.discover-status-badge')).toHaveLength(1);
  });

  it('priorise une disponibilité partielle sur le statut demandé', () => {
    const wrapper = render({ requested: true, request_status: 'partially_available' });

    expect(wrapper.text()).toBe('Partiellement disponible');
  });

  it('affiche le téléchargement avant le statut demandé générique', () => {
    const wrapper = render({ requested: true, request_status: 'sent_to_arr', is_downloading: true });

    expect(wrapper.text()).toBe('En téléchargement');
  });

  it('ne présente aucun badge pour un média à demander', () => {
    const wrapper = render({ requested: false, in_library: false });

    expect(wrapper.find('.discover-status-badge').exists()).toBe(false);
  });
});
