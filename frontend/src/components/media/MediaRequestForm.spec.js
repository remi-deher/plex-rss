import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';

import MediaRequestForm from './MediaRequestForm.vue';

const RouterLink = { props: ['to'], template: '<a :href="to"><slot /></a>' };

function render(detail, options = {}) {
  return mount(MediaRequestForm, {
    props: {
      detail,
      form: options.form || { plex_user_id: 'alice', root_folder: '', seasons: [] },
      requesters: options.requesters || [],
      folders: options.folders || [],
      admin: options.admin || false,
      currentUserId: options.currentUserId || 'alice',
    },
    global: { stubs: { RouterLink } },
  });
}

describe('MediaRequestForm', () => {
  it('présente une demande directe et replie le choix des saisons', async () => {
    const form = { plex_user_id: 'alice', root_folder: '', seasons: [1, 2, 3] };
    const wrapper = render({ media_type: 'show', number_of_seasons: 3, year: 2026 }, { form });

    expect(wrapper.text()).toContain('Demander la série');
    expect(wrapper.find('.request-options').attributes('open')).toBeUndefined();
    expect(wrapper.findAll('select')).toHaveLength(0);
    expect(wrapper.text()).toContain('Toutes les saisons');

    await wrapper.find('.request-submit').trigger('click');
    expect(wrapper.emitted('submit')).toHaveLength(1);
  });

  it('réserve le demandeur et le dossier racine aux options administrateur', () => {
    const wrapper = render(
      { media_type: 'movie' },
      {
        admin: true,
        requesters: [{ plex_user_id: 'alice', display_name: 'Alice' }],
        folders: [{ path: '/movies' }],
      },
    );

    expect(wrapper.text()).toContain('Administration');
    expect(wrapper.findAll('select')).toHaveLength(2);
  });

  it('permet de rejoindre puis suivre une demande existante', async () => {
    const wrapper = render({
      media_type: 'movie',
      requested: true,
      request_id: 42,
      request_status: 'sent_to_arr',
      requester_ids: ['bob'],
    });

    expect(wrapper.text()).toContain('Ajouter à mes demandes');
    expect(wrapper.text()).toContain('Suivre la demande');
    await wrapper.find('button.primary').trigger('click');
    expect(wrapper.emitted('join')).toHaveLength(1);
  });

  it('affiche un accès Plex lorsque le média est disponible', () => {
    const wrapper = render({ media_type: 'movie', in_library: true, plex_guid: 'plex://movie/abc' });
    const link = wrapper.find('a.primary');

    expect(wrapper.text()).toContain('Ce média est dans Plex');
    expect(link.text()).toContain('Ouvrir dans Plex');
    expect(link.attributes('href')).toContain('app.plex.tv');
    expect(link.attributes('href')).not.toContain('X-Plex-Token');
  });

  it('affiche la chronologie opérationnelle et le détail par saison', () => {
    const wrapper = render({
      media_type: 'show',
      requested: true,
      request_id: 42,
      operational_status: 'downloading',
      episodes_available_count: 6,
      episodes_total_count: 10,
      workflow_timeline: [
        { key: 'requested', label: 'Demandé', state: 'completed', occurred_at: '2026-08-03T10:00:00Z' },
        { key: 'downloading', label: 'Téléchargement en cours', state: 'current' },
        { key: 'completed', label: 'Disponible dans Plex', state: 'upcoming' },
      ],
      seasons: [
        { season_number: 1, episodes_available_count: 6, episodes_total_count: 10, status: 'partially_available' },
      ],
    }, { currentUserId: '' });

    expect(wrapper.text()).toContain('Téléchargement en cours');
    expect(wrapper.find('.request-progress-step.done').text()).toContain('Demandé');
    expect(wrapper.text()).toContain('6/10 épisodes disponibles');
    expect(wrapper.find('.season-progress-track span').attributes('style')).toContain('60%');
  });

  it('garde les actions techniques dans le bloc administration', () => {
    const wrapper = render({
      media_type: 'movie',
      requested: true,
      request_id: 42,
      request_status: 'failed',
    }, { admin: true });

    expect(wrapper.find('.request-panel-action').text()).not.toContain('Relancer');
    expect(wrapper.find('.admin-options').text()).toContain('Relancer');
  });

  it('rend une action mobile persistante sans confirmation modale', () => {
    const wrapper = render({ media_type: 'movie' });

    expect(wrapper.find('.mobile-request-bar').exists()).toBe(true);
    expect(wrapper.find('.mobile-request-bar button').text()).toContain('Demander ce film');
  });
});
