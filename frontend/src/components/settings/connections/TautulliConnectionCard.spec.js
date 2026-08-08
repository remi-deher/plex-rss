import { mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it } from 'vitest';
import { form } from '@/settingsForm';
import TautulliConnectionCard from './TautulliConnectionCard.vue';

// La carte a deux bascules .collection-toggle (anonymisation IP, activité en
// direct) : on retrouve celle voulue par son texte plutot que par un selecteur
// generique qui matcherait la premiere venue.
function liveActivityToggle(wrapper) {
  return wrapper.findAll('.collection-toggle').find(t => t.text().includes('Activité Plex en direct'));
}

describe('TautulliConnectionCard', () => {
  beforeEach(() => {
    form.tautulli_enabled = true;
    form.live_activity_enabled = false;
    form.activity_anonymize_ips = false;
  });

  it('rend la conséquence de la collecte désactivée immédiatement visible', () => {
    const wrapper = mount(TautulliConnectionCard);
    const toggle = liveActivityToggle(wrapper);

    expect(toggle.get('.collection-state').text()).toBe('Désactivée');
    expect(toggle.get('.collection-toggle-copy').text()).toContain(
      'aucune lecture en cours ne sera collectée ni affichée',
    );
  });

  it('actualise le statut et son explication quand la collecte est activée', async () => {
    const wrapper = mount(TautulliConnectionCard);
    await liveActivityToggle(wrapper).get('input').setValue(true);
    const toggle = liveActivityToggle(wrapper);

    expect(toggle.classes()).toContain('active');
    expect(toggle.get('.collection-state').text()).toBe('Activée');
    expect(toggle.get('.collection-toggle-copy').text()).toContain(
      'apparaissent sur le tableau de bord et dans Activité Plex',
    );
  });

  it('explique la troncature IP plutot que de sous-entendre un masquage complet', async () => {
    const wrapper = mount(TautulliConnectionCard);
    const toggle = () => wrapper.findAll('.collection-toggle').find(t => t.text().includes('Anonymiser les adresses IP'));

    expect(toggle().get('.collection-toggle-copy').text()).toContain("l'adresse IP complète");

    await toggle().get('input').setValue(true);
    expect(toggle().get('.collection-toggle-copy').text()).toContain('192.168.1.0');
  });
});
