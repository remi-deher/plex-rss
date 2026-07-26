import { onUnmounted } from 'vue';

/**
 * Version débouncée d'une fonction, annulée au démontage.
 *
 * Quatre sites gardaient leur propre `let timer` + `clearTimeout`/`setTimeout` : la
 * recherche de Bibliothèque (250 ms), celles de Découvrir et Notifications (300 ms) et
 * l'aperçu des modèles d'email (500 ms). Sans l'annulation au démontage, quitter la page
 * pendant le délai déclenchait un appel sur un composant déjà démonté.
 *
 * @param {(...args: any[]) => void} callback
 * @param {number} delayMs
 * @returns {((...args: any[]) => void) & {cancel: () => void, flush: (...args: any[]) => void}}
 */
export function useDebounced(callback, delayMs) {
  let timer;

  const debounced = (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => callback(...args), delayMs);
  };

  debounced.cancel = () => clearTimeout(timer);
  /** Exécute tout de suite et annule le délai en attente. */
  debounced.flush = (...args) => {
    clearTimeout(timer);
    callback(...args);
  };

  onUnmounted(debounced.cancel);

  return debounced;
}
