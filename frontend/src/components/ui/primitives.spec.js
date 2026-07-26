import { mount } from '@vue/test-utils';
import { h } from 'vue';
import { describe, expect, it } from 'vitest';

import LoadMore from './LoadMore.vue';
import MetricCard from './MetricCard.vue';
import MetricGrid from './MetricGrid.vue';
import PanelCard from './PanelCard.vue';
import TabNav from './TabNav.vue';
import ToggleSwitch from './ToggleSwitch.vue';

const RouterLinkStub = {
  props: ['to'],
  setup(props, { slots }) {
    return () => h('a', { href: typeof props.to === 'string' ? props.to : '#' }, slots.default?.());
  },
};
const global = { stubs: { RouterLink: RouterLinkStub } };
const Icon = { setup: () => () => h('svg') };

describe('MetricCard', () => {
  // Deux markups existaient : à plat (Bibliothèque, Téléchargements) et avec icône
  // enveloppant le texte dans un div (Tableau de bord, Activité). La CSS des grilles
  // parentes cible ces structures précises, donc le composant doit les reproduire.
  it('rend la forme à plat sans icône', () => {
    const wrapper = mount(MetricCard, { props: { label: 'En VF', value: 42, detail: '3 ajoutés' }, global });
    const card = wrapper.find('article.metric-card');
    // Forme à plat : les trois éléments sont enfants directs de la carte, sans div.
    expect(card.find('div').exists()).toBe(false);
    expect(card.find('span').text()).toBe('En VF');
    expect(card.find('strong').text()).toBe('42');
    expect(card.find('small').text()).toBe('3 ajoutés');
  });

  it('enveloppe le texte dans un div quand une icône est fournie', () => {
    const wrapper = mount(MetricCard, { props: { label: 'Bloqués', value: 2, icon: Icon }, global });
    const card = wrapper.find('article.metric-card');
    expect(card.find('svg.metric-icon').exists()).toBe(true);
    const inner = card.find('div');
    expect(inner.exists()).toBe(true);
    expect(inner.find('span').text()).toBe('Bloqués');
    expect(inner.find('strong').text()).toBe('2');
  });

  it('omet le détail quand il est vide, et affiche une valeur de repli', () => {
    const wrapper = mount(MetricCard, { props: { label: 'X' }, global });
    expect(wrapper.find('small').exists()).toBe(false);
    expect(wrapper.find('strong').text()).toBe('—');
  });

  it('devient un lien quand `to` est fourni', () => {
    const wrapper = mount(MetricCard, { props: { label: 'À approuver', value: 3, to: '/library' }, global });
    expect(wrapper.find('article').exists()).toBe(false);
    const link = wrapper.find('a');
    expect(link.attributes('href')).toBe('/library');
    expect(link.classes()).toEqual(expect.arrayContaining(['metric-card', 'metric-card-link']));
  });

  it('applique la classe de variante', () => {
    const wrapper = mount(MetricCard, { props: { label: 'X', cardClass: 'activity-metric-card accent' }, global });
    expect(wrapper.find('article').classes()).toEqual(
      expect.arrayContaining(['metric-card', 'activity-metric-card', 'accent']),
    );
  });
});

describe('MetricGrid', () => {
  it('porte la classe de variante et expose son libellé accessible', () => {
    const wrapper = mount(MetricGrid, {
      props: { gridClass: 'dashboard-metrics', ariaLabel: 'Résumé' },
      slots: { default: '<article/>' },
    });
    const grid = wrapper.find('section.metric-grid');
    expect(grid.classes()).toContain('dashboard-metrics');
    expect(grid.attributes('aria-label')).toBe('Résumé');
  });
});

describe('PanelCard', () => {
  it('rend le markup attendu par la CSS globale', () => {
    const wrapper = mount(PanelCard, {
      props: { title: 'Utilisateurs actifs', eyebrow: 'Usage', description: 'Sur 30 jours' },
      slots: { default: '<p class="body">x</p>', action: '<a>Gérer</a>' },
    });
    const panel = wrapper.find('section.panel');
    const head = panel.find('.panel-head');
    expect(head.find('.eyebrow').text()).toBe('Usage');
    expect(head.find('h2').text()).toBe('Utilisateurs actifs');
    expect(head.find('p').text()).toBe('Sur 30 jours');
    expect(head.find('a').text()).toBe('Gérer');
    expect(panel.find('.body').exists()).toBe(true);
  });

  it('omet entièrement l’en-tête quand il n’y a rien à y mettre', () => {
    const wrapper = mount(PanelCard, { slots: { default: '<p/>' } });
    expect(wrapper.find('.panel-head').exists()).toBe(false);
  });

  // `empty` est une chaîne : le parent passe le message, pas un booléen.
  it('n’affiche l’état vide que si un message est fourni', () => {
    expect(mount(PanelCard, { props: { title: 'T' } }).find('.empty').exists()).toBe(false);
    const filled = mount(PanelCard, { props: { title: 'T', empty: 'Aucune activité.' } });
    expect(filled.find('.empty').text()).toBe('Aucune activité.');
  });
});

describe('TabNav', () => {
  const tabs = [
    { value: 'queue', label: 'File active', count: 3, badgeClass: 'error-badge' },
    { value: 'history', label: 'Historique' },
  ];

  it('marque l’onglet courant et expose les rôles ARIA', () => {
    const wrapper = mount(TabNav, { props: { tabs, modelValue: 'queue', ariaLabel: 'Téléchargements' } });
    expect(wrapper.find('nav.detail-tabs').attributes('aria-label')).toBe('Téléchargements');
    expect(wrapper.find('nav').attributes('role')).toBe('tablist');
    const [active, other] = wrapper.findAll('button[role="tab"]');
    expect(active.attributes('aria-selected')).toBe('true');
    expect(active.classes()).toContain('active');
    expect(other.attributes('aria-selected')).toBe('false');
  });

  it('affiche le compteur seulement là où il y en a un', () => {
    const wrapper = mount(TabNav, { props: { tabs, modelValue: 'queue' } });
    const badges = wrapper.findAll('.tab-badge');
    expect(badges).toHaveLength(1);
    expect(badges[0].text()).toBe('3');
    expect(badges[0].classes()).toContain('error-badge');
  });

  it('émet la nouvelle valeur au clic', async () => {
    const wrapper = mount(TabNav, { props: { tabs, modelValue: 'queue' } });
    await wrapper.findAll('button')[1].trigger('click');
    expect(wrapper.emitted('update:modelValue')).toEqual([['history']]);
  });
});

describe('LoadMore', () => {
  it('ne s’affiche que s’il reste des pages', () => {
    expect(mount(LoadMore, { props: { hasMore: false } }).find('button').exists()).toBe(false);
    expect(mount(LoadMore, { props: { hasMore: true } }).find('button').exists()).toBe(true);
  });

  it('désactive le bouton et change le libellé pendant le chargement', () => {
    const wrapper = mount(LoadMore, { props: { hasMore: true, loading: true, loadingLabel: 'Chargement…' } });
    const button = wrapper.find('button');
    expect(button.attributes('disabled')).toBeDefined();
    expect(button.text()).toBe('Chargement…');
    expect(wrapper.find('svg.spin').exists()).toBe(true);
  });

  it('émet load au clic', async () => {
    const wrapper = mount(LoadMore, { props: { hasMore: true, label: 'Charger plus de médias' } });
    expect(wrapper.find('button').text()).toBe('Charger plus de médias');
    await wrapper.find('button').trigger('click');
    expect(wrapper.emitted('load')).toHaveLength(1);
  });
});

describe('ToggleSwitch', () => {
  it('expose un interrupteur accessible reflétant son état', () => {
    const wrapper = mount(ToggleSwitch, { props: { modelValue: true, label: 'Réactiver' } });
    const input = wrapper.find('input');
    expect(input.attributes('role')).toBe('switch');
    expect(input.attributes('aria-checked')).toBe('true');
    expect(input.element.checked).toBe(true);
    expect(wrapper.find('label').classes()).toContain('is-on');
    // Le libellé est du vrai texte, pas un `content:` CSS : lisible par un lecteur d'écran.
    expect(wrapper.find('.ui-switch-label').text()).toBe('Réactiver');
    expect(input.attributes('aria-label')).toBe('Réactiver');
  });

  it('émet la nouvelle valeur au changement', async () => {
    const wrapper = mount(ToggleSwitch, { props: { modelValue: false } });
    await wrapper.find('input').setValue(true);
    expect(wrapper.emitted('update:modelValue')).toEqual([[true]]);
  });

  it('se laisse désactiver pendant une écriture en cours', () => {
    const wrapper = mount(ToggleSwitch, { props: { modelValue: false, disabled: true } });
    expect(wrapper.find('input').attributes('disabled')).toBeDefined();
  });
});
