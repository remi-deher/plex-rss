/**
 * Cache SWR (stale-while-revalidate) cote client, partage par les vues principales.
 *
 * Chaque vue stocke son etat dans des `ref()` locaux detruits au demontage : revenir sur
 * une page deja visitee repartait donc d'un ecran vide + refetch complet, meme quand le
 * snapshot serveur etait encore chaud dans Redis. On conserve ici la derniere charge utile
 * connue pour repeindre immediatement, la revalidation reseau suivant derriere (c'est ce
 * que fait `swr` chez Seerr).
 *
 * Persistance en `sessionStorage` et non `localStorage` : la donnee est propre a
 * l'utilisateur connecte, et sessionStorage meurt avec l'onglet tout en survivant a un F5.
 * Un changement de compte dans le meme onglet est couvert en plus par `syncCacheOwner`.
 */

const memory = new Map();
const STORAGE_PREFIX = 'plexarr:swr:';
const OWNER_KEY = 'plexarr:swr-owner';

function storage() {
  // Safari en navigation privee et certains navigateurs durcis font lever l'acces meme
  // en lecture : le cache memoire reste alors seul actif, ce qui est suffisant.
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/**
 * Entree brute du cache : `{ data, savedAt }`, ou `null` si absente/trop vieille.
 * `maxAgeMs` borne l'anciennete de ce qu'on accepte de repeindre — une vue ne doit jamais
 * afficher un etat vieux de plusieurs jours, meme "en attendant la revalidation".
 */
export function readCacheEntry(key, { maxAgeMs = Infinity } = {}) {
  let entry = memory.get(key);
  if (!entry) {
    const raw = storage()?.getItem(STORAGE_PREFIX + key);
    if (raw) {
      try {
        entry = JSON.parse(raw);
        memory.set(key, entry);
      } catch {
        dropCache(key);
      }
    }
  }
  if (!entry || typeof entry.savedAt !== 'number') return null;
  if (Date.now() - entry.savedAt > maxAgeMs) {
    dropCache(key);
    return null;
  }
  return entry;
}

/** Charge utile seule — raccourci quand l'age d'origine n'a pas besoin d'etre affiche. */
export function readCache(key, options) {
  return readCacheEntry(key, options)?.data ?? null;
}

export function writeCache(key, data, { persist = true } = {}) {
  const entry = { savedAt: Date.now(), data };
  memory.set(key, entry);
  if (!persist) return;
  try {
    storage()?.setItem(STORAGE_PREFIX + key, JSON.stringify(entry));
  } catch {
    // Quota depasse ou stockage indisponible : le cache memoire couvre deja la navigation
    // interne, seule la survie au F5 est perdue.
  }
}

export function dropCache(key) {
  memory.delete(key);
  try {
    storage()?.removeItem(STORAGE_PREFIX + key);
  } catch {
    /* Stockage indisponible. */
  }
}

/** Vide tout le cache — deconnexion, ou changement de compte detecte. */
export function clearCache() {
  memory.clear();
  const store = storage();
  if (!store) return;
  try {
    for (const key of Object.keys(store)) {
      if (key.startsWith(STORAGE_PREFIX)) store.removeItem(key);
    }
  } catch {
    /* Stockage indisponible. */
  }
}

/**
 * Purge le cache si l'utilisateur connecte n'est plus celui pour qui il a ete rempli.
 *
 * La deconnexion passe par une navigation pleine page vers /logout, qui ne vide pas
 * sessionStorage : sans ce garde, se reconnecter avec un autre compte dans le meme onglet
 * repeindrait brievement les donnees du precedent (poste partage).
 */
export function syncCacheOwner(session) {
  const owner = session ? String(session.id ?? session.plex_user_id ?? session.username ?? '') : '';
  const store = storage();
  let previous = null;
  try {
    previous = store?.getItem(OWNER_KEY) ?? null;
  } catch {
    return;
  }
  if (previous !== null && previous !== owner) clearCache();
  try {
    if (owner) store?.setItem(OWNER_KEY, owner);
    else store?.removeItem(OWNER_KEY);
  } catch {
    /* Stockage indisponible. */
  }
}
