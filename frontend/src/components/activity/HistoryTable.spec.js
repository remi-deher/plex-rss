import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import HistoryTable from './HistoryTable.vue';

describe('HistoryTable', () => {
  it('affiche une grande affiche, l’adresse IP et son lieu sur des lignes séparées', () => {
    const wrapper = mount(HistoryTable, { props: { items: [{
      source: 'tautulli',
      session_id: '42',
      title: 'Film',
      user_name: 'Rémi',
      player: 'Apple TV',
      address: '82.64.10.20',
      geo_status: 'resolved',
      geo_city: 'Paris',
      geo_region: 'Île-de-France',
      geo_country_code: 'FR',
      watched_ms: 3_600_000,
      started_at: '2026-08-03T20:00:00',
    }] } });

    expect(wrapper.get('.media-artwork').classes()).toContain('history');
    expect(wrapper.get('.history-client').text()).toContain('82.64.10.20');
    expect(wrapper.get('.history-place').text()).toBe('Paris, Île-de-France, FR');
  });

  it('affiche simplement local pour une adresse privée', () => {
    const wrapper = mount(HistoryTable, { props: { items: [{
      source: 'plex',
      session_id: 'local',
      title: 'Film local',
      address: '192.168.1.25',
      geo_status: 'local',
    }] } });

    expect(wrapper.get('.history-place').text()).toBe('local');
  });
});
