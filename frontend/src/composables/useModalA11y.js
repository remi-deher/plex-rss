// Piège de focus + fermeture Échap pour les modales/drawers (ConfirmModal, DrawerShell,
// ManualImportModal, modales inline des cartes de connexions). Sans ça, Tab pouvait
// sortir de la modale vers le contenu masqué derrière et Échap ne fermait rien
// (voir audit UI — accessibilité clavier).
import { nextTick, onBeforeUnmount, watch } from 'vue';

const FOCUSABLE_SELECTOR = [
  'a[href]', 'button:not([disabled])', 'textarea:not([disabled])',
  'input:not([disabled])', 'select:not([disabled])', '[tabindex]:not([tabindex="-1"])',
].join(', ');

function focusableChildren(panel) {
  return Array.from(panel.querySelectorAll(FOCUSABLE_SELECTOR)).filter((el) => el.offsetParent !== null);
}

/**
 * @param {import('vue').Ref<HTMLElement|null>} panelRef Ref sur l'élément racine de la modale (aside/div), doit porter tabindex="-1".
 * @param {import('vue').Ref<boolean>|null} isOpenRef Ref booléenne si le composant reste monté avec un v-if interne ; null si le composant n'est monté que pendant l'ouverture (le piège s'active alors dès le montage).
 * @param {() => void} onClose Appelé sur Échap.
 */
export function useModalA11y(panelRef, isOpenRef, onClose) {
  let previouslyFocused = null;

  function handleKeydown(e) {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== 'Tab' || !panelRef.value) return;
    const focusable = focusableChildren(panelRef.value);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  async function activate() {
    previouslyFocused = document.activeElement;
    document.addEventListener('keydown', handleKeydown, true);
    await nextTick();
    const panel = panelRef.value;
    if (!panel) return;
    const target = focusableChildren(panel)[0] || panel;
    target.focus({ preventScroll: true });
  }

  function deactivate() {
    document.removeEventListener('keydown', handleKeydown, true);
    if (previouslyFocused && typeof previouslyFocused.focus === 'function') {
      previouslyFocused.focus({ preventScroll: true });
    }
    previouslyFocused = null;
  }

  if (isOpenRef) {
    watch(isOpenRef, (open) => { if (open) activate(); else deactivate(); }, { immediate: true });
  } else {
    activate();
  }

  onBeforeUnmount(deactivate);
}
