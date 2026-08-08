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

/** Libellés courts, pour les badges épinglés sur une affiche.
 *
 *  Sur une carte de bibliothèque en largeur téléphone, « Partiellement disponible »
 *  demande 161 px pour 150 px disponibles : le libellé complet y est tronqué (« …disponib… »),
 *  donc illisible. Seuls les statuts réellement trop longs ont une forme courte ; les
 *  autres retombent sur le libellé normal. */
export const REQUEST_STATUS_SHORT_LABELS = {
  partially_available: 'Partiel',
  orphan: 'Suivi *arr',
};

export function requestStatusShortLabel(value, fallback) {
  return REQUEST_STATUS_SHORT_LABELS[value] || requestStatusLabel(value, fallback);
}

/** Film / Série / Musique — types réels de `LibraryItem.media_type` (+ Plex
 *  `section.type`, qui utilise les mêmes valeurs `movie`/`show`, plus `artist` pour la
 *  musique). Tout le reste retombe sur « Film », comme avant l'ajout de la musique. */
const MEDIA_TYPE_LABELS = { show: 'Série', artist: 'Musique' };
const MEDIA_TYPE_PLURAL_LABELS = { show: 'Séries', artist: 'Musique' };

/** « Film » / « Série » / « Musique » — au singulier, pour une fiche ou une ligne de tableau. */
export function mediaTypeLabel(value) {
  return MEDIA_TYPE_LABELS[value] || 'Film';
}

/** « Films » / « Séries » / « Musique » — au pluriel, pour un filtre ou un en-tête de section. */
export function mediaTypePluralLabel(value) {
  return MEDIA_TYPE_PLURAL_LABELS[value] || 'Films';
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
