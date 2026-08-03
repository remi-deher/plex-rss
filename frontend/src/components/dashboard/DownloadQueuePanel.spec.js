import { describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';

import DownloadQueuePanel from './DownloadQueuePanel.vue';

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }));

const RouterLink = {
  props: ['to'],
  template: '<a :href="typeof to === \'string\' ? to : to?.path"><slot /></a>',
};

/** Élément tel que le renvoie réellement /api/arr/queue. */
function queueItem(overrides = {}) {
  return {
    queue_id: 575526434,
    instance_id: 2,
    instance: 'Radarr',
    arr_type: 'radarr',
    title: 'Bring It On',
    status: 'downloading',
    progress: 36.2,
    size: 8833426966,
    sizeleft: 5634303510,
    timeleft: '00:18:05',
    download_client: 'qBittorrent',
    library_id: 1392,
    request_id: null,
    error: null,
    tracked_state: 'downloading',
    ...overrides,
  };
}

function render(queue, props = {}) {
  return mount(DownloadQueuePanel, {
    props: { queue, ...props },
    global: { stubs: { RouterLink } },
  });
}

describe('DownloadQueuePanel', () => {
  it('affiche la progression réelle renvoyée par l’API', () => {
    // Régression : le panneau lisait `item.size_left`, alors que l'API renvoie
    // `sizeleft` / `progress`. Le calcul échouait donc toujours et le composant
    // retombait sur `item.status`, affichant le libellé brut anglais « downloading ».
    const wrapper = render([queueItem()]);

    const bar = wrapper.get('.queue-progress i');
    expect(bar.attributes('style')).toContain('width: 36%');
    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('36');
    expect(wrapper.text()).not.toContain('downloading');
  });

  it('calcule la progression depuis les tailles quand `progress` est absent', () => {
    const wrapper = render([queueItem({ progress: null, size: 1000, sizeleft: 250 })]);
    expect(wrapper.get('.queue-progress i').attributes('style')).toContain('width: 75%');
  });

  it('affiche un statut en français plutôt que le libellé brut de *arr', () => {
    // Régression : le badge affichait `item.size_left_label`, champ inexistant, donc
    // invariablement son repli « En cours » — quel que soit l'état réel de l'élément.
    expect(render([queueItem()]).get('.badge').text()).toBe('En cours');
    expect(render([queueItem({ status: 'paused' })]).get('.badge').text()).toBe('En pause');
    expect(render([queueItem({ progress: 100 })]).get('.badge').text()).toBe('Terminé');
    expect(render([queueItem({ error: 'Import échoué' })]).get('.badge').text()).toBe('Erreur');
  });

  it('signale un fichier téléchargé que *arr n’arrive pas à importer', () => {
    const wrapper = render([queueItem({ tracked_state: 'importPending' })]);
    expect(wrapper.get('.badge').text()).toBe('À importer');
    expect(wrapper.text()).toContain('import impossible');
  });

  it('signale un téléchargement qu’aucune demande ne réclame', () => {
    const wrapper = render([queueItem({ request_id: null, library_id: null })]);
    expect(wrapper.get('.badge').text()).toBe('Non rattaché');
    expect(wrapper.text()).toContain('aucune demande associée');
  });

  it('annonce l’erreur en priorité quand l’élément est aussi non rattaché', () => {
    // Sinon le badge (« Non rattaché ») contredit la barre de progression, rouge.
    const wrapper = render([
      queueItem({ request_id: null, library_id: null, error: 'Archive illisible' }),
    ]);
    expect(wrapper.get('.badge').text()).toBe('Erreur');
    expect(wrapper.get('.queue-progress i').classes()).toContain('is-error');
  });

  it('affiche client, reste à télécharger et temps restant', () => {
    const text = render([queueItem()]).text();
    expect(text).toContain('qBittorrent');
    expect(text).toContain('restants');
    expect(text).toContain('18 min');
  });

  it('remplace le débit par la cause quand une intervention est nécessaire', () => {
    // Le débit n'a aucun intérêt sur un élément bloqué : c'est la cause qu'on veut lire.
    const wrapper = render([queueItem({ error: 'Aucun fichier trouvé dans l’archive' })]);
    expect(wrapper.get('.queue-meta').text()).toBe('Aucun fichier trouvé dans l’archive');
    expect(wrapper.text()).not.toContain('qBittorrent');
  });

  it('convertit le temps restant en libellé lisible', () => {
    expect(render([queueItem({ timeleft: '02:30:00' })]).text()).toContain('2 h 30');
    expect(render([queueItem({ timeleft: '00:00:20' })]).text()).toContain('moins d’une minute');
    // Valeur absente ou illisible : pas d'« undefined » affiché.
    expect(render([queueItem({ timeleft: null })]).text()).not.toContain('undefined');
  });

  it('borne la progression entre 0 et 100', () => {
    expect(render([queueItem({ progress: 140 })]).get('.queue-progress i').attributes('style')).toContain('width: 100%');
    expect(render([queueItem({ progress: -5 })]).get('.queue-progress i').attributes('style')).toContain('width: 0%');
  });

  it('lie la ligne à la fiche du média quand elle en a une', () => {
    const wrapper = render([queueItem({ library_id: 1392 })]);
    expect(wrapper.get('a.queue-row').attributes('href')).toBe('/media/library/1392');
  });

  it('rend une ligne non cliquable quand aucune fiche ne correspond', () => {
    const wrapper = render([queueItem({ library_id: null, request_id: null, linked_request_id: null })]);
    expect(wrapper.find('a.queue-row').exists()).toBe(false);
    expect(wrapper.find('article.queue-row').exists()).toBe(true);
  });

  it('affiche l’état vide et l’état de chargement', () => {
    expect(render([]).text()).toContain('Aucun téléchargement en cours');
    expect(render([], { loading: true }).text()).toContain('Chargement');
  });
});

describe('DownloadQueuePanel — priorité et synthèse', () => {
  it('remonte les éléments nécessitant une intervention avant les autres', () => {
    // Le tableau de bord passait `queue.slice(0, 5)` : la troncature précédait tout tri,
    // donc un téléchargement bloqué pouvait être absent du panneau — précisément ce qu'on
    // vient y chercher.
    const queue = [
      ...Array.from({ length: 5 }, (_, i) => queueItem({ queue_id: i + 10, title: `Sain ${i}` })),
      queueItem({ queue_id: 99, title: 'Bloqué', error: 'Torrent mort' }),
    ];
    const wrapper = render(queue);

    const titres = wrapper.findAll('.queue-heading strong').map(n => n.text());
    expect(titres[0]).toBe('Bloqué');
    expect(titres).toHaveLength(5);
  });

  it('n’affiche que `limit` lignes et annonce le reste', () => {
    const queue = Array.from({ length: 8 }, (_, i) => queueItem({ queue_id: i, title: `T${i}` }));
    const wrapper = render(queue, { limit: 3 });

    expect(wrapper.findAll('.queue-row')).toHaveLength(3);
    expect(wrapper.get('.queue-more').text()).toContain('5 autres en file');
  });

  it('résume toute la file, pas seulement les lignes visibles', () => {
    const queue = [
      queueItem({ queue_id: 1, sizeleft: 1073741824 }),
      queueItem({ queue_id: 2, sizeleft: 1073741824 }),
      queueItem({ queue_id: 3, status: 'paused', sizeleft: 0 }),
      queueItem({ queue_id: 4, error: 'Échec', sizeleft: 0 }),
      queueItem({ queue_id: 5, tracked_state: 'importPending', sizeleft: 0 }),
      queueItem({ queue_id: 6, sizeleft: 0 }),
    ];
    const texte = render(queue, { limit: 2 }).text();

    expect(texte).toContain('3 en cours');
    expect(texte).toContain('1 en pause');
    expect(texte).toContain('1 à importer');
    expect(texte).toContain('1 bloqué');
    expect(texte).toContain('2 Go restants');
  });

  it('n’affiche aucune synthèse quand la file est vide', () => {
    expect(render([]).find('.panel-head p').exists()).toBe(false);
  });
});
