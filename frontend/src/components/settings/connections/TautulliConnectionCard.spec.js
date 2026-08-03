import { mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it } from 'vitest';
import { form } from '@/settingsForm';
import TautulliConnectionCard from './TautulliConnectionCard.vue';

describe('TautulliConnectionCard', () => {
  beforeEach(() => {
    form.tautulli_enabled = true;
    form.live_activity_enabled = false;
  });

  it('rend la conséquence de la collecte désactivée immédiatement visible', () => {
    const wrapper = mount(TautulliConnectionCard);

    expect(wrapper.get('.collection-state').text()).toBe('Désactivée');
    expect(wrapper.get('.collection-toggle-copy').text()).toContain(
      'aucune lecture en cours ne sera collectée ni affichée',
    );
  });

  it('actualise le statut et son explication quand la collecte est activée', async () => {
    const wrapper = mount(TautulliConnectionCard);
    await wrapper.get('.collection-toggle input').setValue(true);

    expect(wrapper.get('.collection-toggle').classes()).toContain('active');
    expect(wrapper.get('.collection-state').text()).toBe('Activée');
    expect(wrapper.get('.collection-toggle-copy').text()).toContain(
      'apparaissent sur le tableau de bord et dans Activité Plex',
    );
  });
});
