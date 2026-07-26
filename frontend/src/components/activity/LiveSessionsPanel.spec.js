import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import LiveSessionsPanel from './LiveSessionsPanel.vue';

const RouterLink = { props: ['to'], template: '<a :href="to"><slot /></a>' };

describe('LiveSessionsPanel', () => {
  it('affiche une session Plex avec progression et méthode de lecture', () => {
    const wrapper = mount(LiveSessionsPanel, {
      props: {
        sessions: [{
          session_id: 'abc',
          title: 'Épisode 1',
          grandparent_title: 'Foundation',
          user_name: 'Rémi',
          player: 'Télévision',
          progress: 42,
          playback_method: 'transcode',
          quality: '4k',
        }],
      },
      global: { stubs: { RouterLink } },
    });

    expect(wrapper.text()).toContain('Foundation · Épisode 1');
    expect(wrapper.text()).toContain('Rémi · Télévision');
    expect(wrapper.text()).toContain('Transcodage');
    expect(wrapper.get('.progress-track i').attributes('style')).toContain('42%');
  });

  it('affiche un état vide sans lecture', () => {
    const wrapper = mount(LiveSessionsPanel, {
      global: { stubs: { RouterLink } },
    });
    expect(wrapper.text()).toContain('Aucune lecture en cours');
  });
});
