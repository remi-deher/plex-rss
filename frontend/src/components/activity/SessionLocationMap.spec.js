import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import SessionLocationMap from './SessionLocationMap.vue';

describe('SessionLocationMap', () => {
  it('affiche la localisation, l’IP et une carte différée', () => {
    const wrapper = mount(SessionLocationMap, { props: { session: {
      address: '82.64.10.20',
      geo_status: 'resolved',
      geo_city: 'Paris',
      geo_region: 'Île-de-France',
      geo_country: 'France',
      geo_country_code: 'FR',
      geo_lat: 48.8566,
      geo_lon: 2.3522,
    } } });

    expect(wrapper.text()).toContain('Paris, Île-de-France, FR');
    expect(wrapper.text()).toContain('82.64.10.20');
    expect(wrapper.get('iframe').attributes('loading')).toBe('lazy');
    expect(wrapper.get('iframe').attributes('src')).toContain('openstreetmap.org');
  });

  it('ne charge aucune carte pour une adresse anonymisée', () => {
    const wrapper = mount(SessionLocationMap, { props: { session: { geo_status: 'anonymized' } } });

    expect(wrapper.find('iframe').exists()).toBe(false);
    expect(wrapper.text()).toContain('Désactivez l’anonymisation');
  });

  it('affiche uniquement local comme lieu pour une IP privée', () => {
    const wrapper = mount(SessionLocationMap, { props: { session: {
      address: '192.168.1.25',
      geo_status: 'local',
      geo_country: 'local',
    } } });

    expect(wrapper.get('.location-head strong').text()).toBe('local');
    expect(wrapper.find('iframe').exists()).toBe(false);
  });
});
