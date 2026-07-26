import { onUnmounted } from 'vue';

/**
 * Annule la requête précédente et ignore les réponses hors séquence.
 *
 * Trois vues (Bibliothèque, Téléchargements, Découvrir) recopiaient le même triplet
 * `activeController?.abort()` + `new AbortController()` + compteur `loadSequence`, avec
 * chaque fois le même `if (e.name !== 'AbortError')`. L'AbortController seul ne suffit
 * pas : une réponse peut arriver après l'abandon, ou deux chargements concurrents (frappe
 * au clavier puis changement de filtre) revenir dans le désordre. Le jeton de séquence
 * garantit que seule la dernière demande écrit dans l'état.
 *
 * @example
 * const request = useLatestRequest();
 * async function load() {
 *   const { signal, isCurrent } = request.begin();
 *   try {
 *     const data = await api('/api/library', { signal });
 *     if (isCurrent()) items.value = data;
 *   } catch (e) {
 *     if (!request.isAbort(e) && isCurrent()) error.value = e.message;
 *   }
 * }
 */
export function useLatestRequest() {
  let controller = null;
  let sequence = 0;

  function token() {
    const mine = ++sequence;
    return () => mine === sequence;
  }

  /** Nouveau chargement : abandonne le précédent et repart d'un signal neuf. */
  function begin() {
    controller?.abort();
    controller = new AbortController();
    return { signal: controller.signal, isCurrent: token() };
  }

  /**
   * Suite d'un chargement en cours (pagination « charger plus ») : garde le signal
   * existant — on ne veut pas annuler la page déjà demandée — mais prend un nouveau
   * jeton, pour qu'un `begin()` survenu entre-temps invalide bien cette réponse.
   */
  function extend() {
    controller ||= new AbortController();
    return { signal: controller.signal, isCurrent: token() };
  }

  /** Abandonne sans repartir (avant un debounce, ou au démontage). */
  function abort() {
    controller?.abort();
  }

  const isAbort = (error) => error?.name === 'AbortError';

  onUnmounted(abort);

  return { begin, extend, abort, isAbort };
}
