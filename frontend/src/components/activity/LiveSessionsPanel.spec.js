import { mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import LiveSessionsPanel from './LiveSessionsPanel.vue';

const RouterLink = { props: ['to'], template: '<a :href="to"><slot /></a>' };

/** Session telle que la renvoie réellement /api/playback/live (voir `_serialize`). */
function session(overrides = {}) {
  return {
    session_id: 'abc',
    title: 'Épisode 1',
    grandparent_title: 'Foundation',
    user_name: 'Rémi',
    player: 'Télévision',
    state: 'playing',
    progress: 42,
    progress_ms: 42 * 60000,
    duration_ms: 100 * 60000,
    playback_method: 'transcode',
    video_decision: 'transcode',
    audio_decision: 'copy',
    quality: '4k',
    location: 'lan',
    bandwidth_kbps: 8000,
    address: '82.64.10.20',
    geo_status: 'resolved',
    geo_city: 'Paris',
    geo_country_code: 'FR',
    ...overrides,
  };
}

const render = (sessions, props = {}) =>
  mount(LiveSessionsPanel, { props: { sessions, ...props }, global: { stubs: { RouterLink } } });

describe('LiveSessionsPanel', () => {
  it('affiche une session Plex avec progression et méthode de lecture', () => {
    const wrapper = render([session()]);

    expect(wrapper.text()).toContain('Foundation · Épisode 1');
    expect(wrapper.get('.live-user').text()).toContain('Rémi');
    expect(wrapper.get('.live-title').text()).toContain('Télévision');
    expect(wrapper.text()).toContain('Transcodage');
    expect(wrapper.get('.progress-track i').attributes('style')).toContain('42%');
    expect(wrapper.get('.live-location').text()).toContain('Paris, FR');
    expect(wrapper.get('.live-art .media-artwork').classes()).toContain('medium');
  });

  it('affiche un état vide sans lecture', () => {
    expect(render([]).text()).toContain('Aucune lecture en cours');
  });
});

describe('LiveSessionsPanel — état de lecture', () => {
  it('distingue visuellement une lecture en pause', () => {
    // Régression : `state` était ignoré, une lecture en pause était strictement
    // indiscernable d'une lecture en cours.
    const enPause = render([session({ state: 'paused' })]);
    expect(enPause.find('.live-state').exists()).toBe(true);
    expect(enPause.get('.live-session').classes()).toContain('paused');
    expect(enPause.get('.progress-track i').classes()).toContain('paused');
    expect(enPause.text()).toContain('En pause');

    const enLecture = render([session()]);
    expect(enLecture.find('.live-state').exists()).toBe(false);
    expect(enLecture.get('.live-session').classes()).not.toContain('paused');
  });

  it('signale la mise en mémoire tampon', () => {
    const wrapper = render([session({ state: 'buffering' })]);
    expect(wrapper.get('.live-state').attributes('title')).toBe('Mise en mémoire tampon');
  });

  it('éteint la pastille « en direct » quand tout est en pause', () => {
    expect(render([session({ state: 'paused' })]).get('.eyebrow i').classes()).toContain('idle');
    expect(render([session()]).get('.eyebrow i').classes()).not.toContain('idle');
  });
});

describe('LiveSessionsPanel — bande passante, réseau et transcodage', () => {
  it('affiche la bande passante de chaque flux', () => {
    expect(render([session({ bandwidth_kbps: 8000 })]).get('.live-bandwidth').text()).toBe('8 Mb/s');
  });

  it('distingue un flux local d’un flux distant', () => {
    expect(render([session({ location: 'lan' })]).get('.live-quality').text()).toContain('Local');
    expect(render([session({ location: 'wan' })]).get('.live-quality').text()).toContain('Distant');
    // Valeur absente : pas de séparateur orphelin.
    expect(render([session({ location: null })]).get('.live-quality').text().trim()).toBe('4k');
  });

  it('indique pourquoi le lookup est absent quand les IP sont anonymisées', () => {
    const wrapper = render([session({ geo_status: 'anonymized', geo_city: null, geo_country_code: null })]);
    expect(wrapper.get('.live-location').text()).toContain('IP anonymisée');
  });

  it('explique la raison du transcodage en infobulle', () => {
    // Le badge dit *que* ça transcode ; l'infobulle dit *pourquoi*.
    const wrapper = render([session({ video_decision: 'transcode', audio_decision: 'copy' })]);
    expect(wrapper.get('.playback-badge').attributes('title')).toBe('Vidéo transcodée · Audio copiée');
  });

  it('résume la charge du serveur en en-tête', () => {
    const texte = render([
      session({ session_id: 'a', bandwidth_kbps: 8000 }),
      session({ session_id: 'b', bandwidth_kbps: 4000, playback_method: 'direct_play' }),
      session({ session_id: 'c', bandwidth_kbps: 2000, state: 'paused', playback_method: 'direct_play' }),
    ]).get('.live-summary').text();

    expect(texte).toContain('3 lectures');
    expect(texte).toContain('1 en pause');
    expect(texte).toContain('14 Mb/s');
    expect(texte).toContain('1 transcodage');
  });
});

describe('LiveSessionsPanel — progression interpolée', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('fait avancer la progression entre deux rafraîchissements serveur', async () => {
    // `progress_ms` ne change qu'à l'arrivée d'un évènement SSE : sans interpolation, la
    // barre reste figée et une lecture en cours a l'air arrêtée.
    const wrapper = render([session({ progress_ms: 0, duration_ms: 100_000, progress: 0 })]);
    expect(wrapper.get('.progress-track i').attributes('style')).toContain('width: 0%');

    await vi.advanceTimersByTimeAsync(30_000);
    expect(wrapper.get('.progress-track i').attributes('style')).toContain('width: 30%');
  });

  it('n’avance pas une lecture en pause', async () => {
    const wrapper = render([session({ state: 'paused', progress_ms: 10_000, duration_ms: 100_000 })]);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(wrapper.get('.progress-track i').attributes('style')).toContain('width: 10%');
  });

  it('ne dépasse jamais la durée du média', async () => {
    const wrapper = render([session({ progress_ms: 95_000, duration_ms: 100_000 })]);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(wrapper.get('.progress-track i').attributes('style')).toContain('width: 100%');
    expect(wrapper.text()).toContain('bientôt terminé');
  });

  it('repart de la valeur serveur à chaque rafraîchissement, sans dériver', async () => {
    const wrapper = render([session({ progress_ms: 0, duration_ms: 100_000 })]);
    await vi.advanceTimersByTimeAsync(50_000);
    expect(wrapper.get('.progress-track i').attributes('style')).toContain('width: 50%');

    // Le serveur annonce en réalité 10 s : l'affichage doit se recaler, pas cumuler.
    await wrapper.setProps({ sessions: [session({ progress_ms: 10_000, duration_ms: 100_000 })] });
    expect(wrapper.get('.progress-track i').attributes('style')).toContain('width: 10%');
  });

  it('affiche « durée inconnue » sans durée renseignée', () => {
    expect(render([session({ duration_ms: null, progress: 12 })]).text()).toContain('Durée inconnue');
  });
});
