import { onMounted, onUnmounted } from 'vue';

/**
 * Rappel périodique, arrêté au démontage du composant.
 *
 * Six sites recopiaient `setInterval(() => { if (!document.hidden) load() }, N)` puis son
 * `clearInterval` dans `onUnmounted` — et la page Bibliothèque oubliait le garde de
 * visibilité, rafraîchissant toutes les deux minutes un onglet en arrière-plan.
 *
 * @param {() => void} callback appelé à chaque tick.
 * @param {number} intervalMs période en millisecondes.
 * @param {{whenVisible?: boolean, immediate?: boolean}} [options]
 *   `whenVisible` (défaut `true`) saute les ticks quand l'onglet est masqué : à laisser
 *   activé pour tout rafraîchissement réseau, à désactiver pour une horloge locale (un
 *   compte à rebours doit rester juste au retour sur l'onglet).
 *   `immediate` déclenche un premier appel au montage, sans attendre la période.
 */
export function usePolling(callback, intervalMs, { whenVisible = true, immediate = false } = {}) {
  let timer;

  function tick() {
    if (whenVisible && document.hidden) return;
    callback();
  }

  onMounted(() => {
    if (immediate) tick();
    timer = setInterval(tick, intervalMs);
  });

  onUnmounted(() => clearInterval(timer));

  return { stop: () => clearInterval(timer) };
}
