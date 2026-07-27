import { ref } from 'vue';

/**
 * Enrobe les mutations : confirmation, drapeau d'occupation, capture d'erreur, rechargement.
 *
 * Ce bloc était recopié une quinzaine de fois (6 fois dans la page Notifications, 5 dans la
 * fiche média, 4 dans Bibliothèque), toujours sous la même forme :
 *
 *     if (!await askConfirm({…})) return;
 *     busy.value = true;
 *     try { await api(…); await load(); }
 *     catch (e) { error.value = e.message; }
 *     finally { busy.value = false; }
 *
 * Trois oublis étaient possibles à chaque copie : ne pas remettre `busy` à false dans un
 * chemin d'erreur, oublier le `return` après un refus de confirmation, ou laisser une
 * erreur remonter sans l'afficher.
 *
 * @param {{
 *   askConfirm?: (options: object) => Promise<boolean>,
 *   onDone?: () => any,
 *   busy?: import('vue').Ref<boolean>,
 *   error?: import('vue').Ref<string>,
 * }} [options] `askConfirm` vient de useConfirm ; `onDone` est appelé après succès
 *   (typiquement `load`) ; `busy`/`error` permettent de réutiliser des refs existantes de
 *   la vue plutôt que celles créées ici.
 */
export function useAsyncAction({ askConfirm = null, onDone = null, busy = null, error = null } = {}) {
  const busyRef = busy || ref(false);
  const errorRef = error || ref('');

  /**
   * @param {() => Promise<any>} operation
   * @param {{confirm?: object, reload?: boolean}} [options] `confirm` déclenche une
   *   demande de confirmation avant d'agir ; `reload` (défaut vrai) appelle `onDone`.
   * @returns {Promise<{ok: boolean, result?: any, cancelled?: boolean}>}
   */
  async function run(operation, { confirm = null, reload = true } = {}) {
    if (confirm) {
      if (!askConfirm) throw new Error('useAsyncAction : `confirm` requiert `askConfirm`.');
      if (!await askConfirm(confirm)) return { ok: false, cancelled: true };
    }
    busyRef.value = true;
    errorRef.value = '';
    try {
      const result = await operation();
      if (reload && onDone) await onDone();
      return { ok: true, result };
    } catch (e) {
      errorRef.value = e.message || String(e);
      return { ok: false };
    } finally {
      busyRef.value = false;
    }
  }

  return { run, busy: busyRef, error: errorRef };
}
