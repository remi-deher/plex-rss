// jsdom ne calcule jamais de layout : `el.offsetParent` reste toujours `null`, ce que
// useModalA11y utilise pour ignorer les elements caches. On le simule explicitement sur
// les elements qu'on veut traiter comme visibles, sans quoi focusableChildren() renverrait
// systematiquement un tableau vide et le piege de focus semblerait ne jamais fonctionner.
import { defineComponent, h, nextTick, ref } from 'vue';
import { mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import { useModalA11y } from './useModalA11y';

function markVisible(el) {
  Object.defineProperty(el, 'offsetParent', { get: () => document.body, configurable: true });
  return el;
}

function mountModal({ onClose = vi.fn(), isOpen = null } = {}) {
  const isOpenRef = isOpen;
  const Comp = defineComponent({
    setup() {
      const panelRef = ref(null);
      useModalA11y(panelRef, isOpenRef, onClose);
      return () =>
        h('div', { ref: panelRef, tabindex: '-1' }, [
          h('button', { id: 'first' }, 'Annuler'),
          h('button', { id: 'last' }, 'Confirmer'),
        ]);
    },
  });
  const wrapper = mount(Comp, { attachTo: document.body });
  const first = wrapper.find('#first').element;
  const last = wrapper.find('#last').element;
  markVisible(wrapper.element);
  markVisible(first);
  markVisible(last);
  return { wrapper, onClose, first, last };
}

function pressKey(key, opts = {}) {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...opts });
  document.dispatchEvent(event);
  return event;
}

describe('useModalA11y', () => {
  it('appelle onClose sur Echap', async () => {
    const { wrapper, onClose } = mountModal();
    await nextTick();

    pressKey('Escape');

    expect(onClose).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it('stoppe la propagation d\'Echap (ne doit pas remonter a un handler global de la page)', async () => {
    const { wrapper } = mountModal();
    await nextTick();

    const outerHandler = vi.fn();
    window.addEventListener('keydown', outerHandler);
    pressKey('Escape');
    window.removeEventListener('keydown', outerHandler);

    expect(outerHandler).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('boucle Tab du dernier element vers le premier', async () => {
    const { wrapper, last, first } = mountModal();
    await nextTick();
    last.focus();
    expect(document.activeElement).toBe(last);

    const event = pressKey('Tab');

    expect(document.activeElement).toBe(first);
    expect(event.defaultPrevented).toBe(true);
    wrapper.unmount();
  });

  it('boucle Shift+Tab du premier element vers le dernier', async () => {
    const { wrapper, last, first } = mountModal();
    await nextTick();
    first.focus();
    expect(document.activeElement).toBe(first);

    const event = pressKey('Tab', { shiftKey: true });

    expect(document.activeElement).toBe(last);
    expect(event.defaultPrevented).toBe(true);
    wrapper.unmount();
  });

  it('restaure le focus precedent a la fermeture (isOpenRef -> false)', async () => {
    const trigger = document.createElement('button');
    document.body.appendChild(trigger);
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    const isOpenRef = ref(true);
    const { wrapper } = mountModal({ isOpen: isOpenRef });
    await nextTick();
    expect(document.activeElement).not.toBe(trigger);

    isOpenRef.value = false;
    await nextTick();

    expect(document.activeElement).toBe(trigger);
    wrapper.unmount();
    trigger.remove();
  });

  it('focus automatiquement le premier element interactif a l\'ouverture', async () => {
    const { wrapper, first } = mountModal();
    await nextTick();

    expect(document.activeElement).toBe(first);
    wrapper.unmount();
  });
});
