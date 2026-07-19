import { ref } from 'vue';

export function useConfirm() {
  const dialog = ref({ open: false, title: '', message: '', confirmLabel: 'Confirmer', danger: false });
  let resolver = null;

  function askConfirm(options = {}) {
    dialog.value = { open: true, title: 'Confirmer l’action', message: '', confirmLabel: 'Confirmer', danger: false, ...options };
    return new Promise((resolve) => { resolver = resolve; });
  }

  function resolveConfirm(value) {
    dialog.value = { ...dialog.value, open: false };
    if (resolver) resolver(value);
    resolver = null;
  }

  return { dialog, askConfirm, resolveConfirm };
}
