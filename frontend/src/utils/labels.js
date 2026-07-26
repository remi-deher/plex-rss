// Libellés fr-FR des énumérations du backend, en un seul exemplaire.
//
// Le libellé d'un statut de demande existait en quatre copies divergentes : la même
// valeur `failed` s'affichait « Echec » dans la liste Bibliothèque, « Échec » dans
// Découvrir et « Erreur » dans l'onglet Demandes. Les formes retenues ici sont les
// formes accentuées correctes ; les variantes sans accent ('Echec', 'Refusee',
// 'A approuver', 'Serie') étaient un reste de l'ancienne interface.

/** Statuts réels de `MediaRequest.status`. */
export const REQUEST_STATUSES = [
  'pending_approval',
  'pending',
  'sent_to_arr',
  'partially_available',
  'available',
  'failed',
  'rejected',
];

/** Pseudo-statuts propres à la page Bibliothèque fusionnée : un média déjà dans Plex,
 *  ou suivi par Sonarr/Radarr sans demande associée. Pas des `MediaRequest.status`. */
export const KIND_STATUSES = ['library', 'orphan'];

export const REQUEST_STATUS_LABELS = {
  library: 'Dans Plex',
  orphan: 'Suivi Sonarr/Radarr',
  pending_approval: 'À approuver',
  pending: 'En attente',
  sent_to_arr: 'Transmise',
  partially_available: 'Partiellement disponible',
  available: 'Disponible',
  failed: 'Échec',
  rejected: 'Refusée',
};

/**
 * Libellé d'un statut de demande.
 * @param {string} value statut brut renvoyé par l'API
 * @param {string} [fallback] valeur affichée si le statut est inconnu ; par défaut le
 *   statut brut lui-même (utile pour repérer un statut backend non encore traduit).
 */
export function requestStatusLabel(value, fallback) {
  return REQUEST_STATUS_LABELS[value] || fallback || value;
}

/** « Film » / « Série » — au singulier, pour une fiche ou une ligne de tableau. */
export function mediaTypeLabel(value) {
  return value === 'show' ? 'Série' : 'Film';
}

/** « Films » / « Séries » — au pluriel, pour un filtre ou un en-tête de section. */
export function mediaTypePluralLabel(value) {
  return value === 'show' ? 'Séries' : 'Films';
}

export const PLAYBACK_METHOD_LABELS = {
  direct_play: 'Lecture directe',
  direct_stream: 'Direct Stream',
  transcode: 'Transcodage',
};

const PLAYBACK_METHOD_LABELS_COMPACT = {
  direct_play: 'Direct Play',
  direct_stream: 'Direct Stream',
  transcode: 'Transcode',
};

/**
 * Libellé d'un mode de lecture Plex.
 * @param {string} method direct_play / direct_stream / transcode
 * @param {{compact?: boolean, fallback?: string}} [options] `compact` pour les badges
 *   étroits, `fallback` pour le mode inconnu (« Lecture » sur un badge, « Inconnu »
 *   dans une répartition statistique).
 */
export function playbackMethodLabel(method, { compact = false, fallback = 'Lecture' } = {}) {
  const table = compact ? PLAYBACK_METHOD_LABELS_COMPACT : PLAYBACK_METHOD_LABELS;
  return table[method] || fallback;
}
