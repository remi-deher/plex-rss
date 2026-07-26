import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';

import ConfirmModal from '@/components/ConfirmModal.vue';
import ModalShell from './ModalShell.vue';

describe('ModalShell', () => {
  it('reproduit le markup attendu par la CSS globale (.drawer-backdrop > .modal-panel)', () => {
    const wrapper = mount(ModalShell, {
      props: { title: 'Ajouter une instance', panelClass: 'arr-instance-modal' },
      slots: { default: '<p class="body">contenu</p>', actions: '<button>Enregistrer</button>' },
    });
    const backdrop = wrapper.find('.drawer-backdrop');
    expect(backdrop.exists()).toBe(true);

    const panel = backdrop.find('aside.modal-panel');
    expect(panel.exists()).toBe(true);
    expect(panel.classes()).toContain('arr-instance-modal');
    expect(panel.attributes('role')).toBe('dialog');
    expect(panel.attributes('aria-modal')).toBe('true');
    expect(panel.attributes('tabindex')).toBe('-1');
    // Le libellé accessible retombe sur le titre visible quand aria-label n'est pas fourni.
    expect(panel.attributes('aria-label')).toBe('Ajouter une instance');

    expect(panel.find('.panel-head h2').text()).toBe('Ajouter une instance');
    expect(panel.find('.body').exists()).toBe(true);
    expect(panel.find('.actions button').text()).toBe('Enregistrer');
  });

  it('n’affiche le sous-titre et le message d’erreur que s’ils sont fournis', () => {
    const bare = mount(ModalShell, { props: { title: 'T' } });
    expect(bare.find('.panel-head p').exists()).toBe(false);
    expect(bare.find('.notice.error-text').exists()).toBe(false);
    // Sans slot `actions`, pas de conteneur d'actions vide.
    expect(bare.find('.actions').exists()).toBe(false);

    const filled = mount(ModalShell, { props: { title: 'T', subtitle: 'S', error: 'Boum' } });
    expect(filled.find('.panel-head p').text()).toBe('S');
    expect(filled.find('.notice.error-text').text()).toBe('Boum');
  });

  it('émet close au clic sur le backdrop et sur la croix, mais pas pendant une opération', async () => {
    const wrapper = mount(ModalShell, { props: { title: 'T' } });
    await wrapper.find('.drawer-backdrop').trigger('click');
    expect(wrapper.emitted('close')).toHaveLength(1);
    await wrapper.find('.panel-head button').trigger('click');
    expect(wrapper.emitted('close')).toHaveLength(2);

    // `busy` neutralise la fermeture pour éviter d'abandonner une écriture en cours.
    const busy = mount(ModalShell, { props: { title: 'T', busy: true } });
    await busy.find('.drawer-backdrop').trigger('click');
    await busy.find('.panel-head button').trigger('click');
    expect(busy.emitted('close')).toBeUndefined();
  });

  it('ne rend rien quand open est faux', () => {
    const wrapper = mount(ModalShell, { props: { title: 'T', open: false } });
    expect(wrapper.find('.drawer-backdrop').exists()).toBe(false);
  });
});

describe('ConfirmModal bâti sur ModalShell', () => {
  it('garde son panneau, son titre, son message et ses deux actions', () => {
    const wrapper = mount(ConfirmModal, {
      props: { open: true, title: 'Supprimer ?', message: 'Définitif.', confirmLabel: 'Supprimer', danger: true },
    });
    const panel = wrapper.find('aside.modal-panel');
    expect(panel.classes()).toContain('confirm-modal');
    expect(panel.find('.panel-head h2').text()).toBe('Supprimer ?');
    expect(panel.find('.panel-head p').text()).toBe('Définitif.');

    const buttons = panel.findAll('.form-actions button');
    expect(buttons.map(b => b.text())).toEqual(['Annuler', 'Supprimer']);
    expect(buttons[1].classes()).toContain('danger-button');
  });

  it('émet cancel et confirm, et affiche l’état en cours', async () => {
    const wrapper = mount(ConfirmModal, { props: { open: true, title: 'T' } });
    const [cancel, confirm] = wrapper.findAll('.form-actions button');
    await cancel.trigger('click');
    expect(wrapper.emitted('cancel')).toHaveLength(1);
    await confirm.trigger('click');
    expect(wrapper.emitted('confirm')).toHaveLength(1);

    await wrapper.setProps({ busy: true });
    expect(wrapper.findAll('.form-actions button')[1].text()).toBe('Traitement…');
  });

  it('ne rend rien tant que open est faux', () => {
    const wrapper = mount(ConfirmModal, { props: { open: false, title: 'T' } });
    expect(wrapper.find('.drawer-backdrop').exists()).toBe(false);
  });
});
