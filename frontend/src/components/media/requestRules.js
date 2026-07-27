// Règles de lecture d'une demande — fonctions pures, partagées entre l'onglet Demandes et
// ses sous-composants.

/**
 * État de notification d'un co-demandeur pour l'évènement courant.
 * @returns {boolean|null} `true` notifié, `false` pas encore, `null` rien à notifier.
 */
export function notifiedStatus(row, uid) {
  const notified = row.requester_notifications?.[uid];
  if (!notified) return null;
  return row.status === 'available' ? notified.available : notified.request;
}

/** Au moins un co-demandeur attend encore sa notification. */
export function hasUnnotified(row) {
  return (row.requester_ids || []).some(uid => notifiedStatus(row, uid) === false);
}

/**
 * La demande peut-elle être clôturée manuellement ?
 * Une demande déjà disponible reste clôturable tant qu'elle est suivie pour une
 * amélioration VF — c'est justement la clôture qui arrête ce suivi.
 */
export function canClose(row) {
  return row.status !== 'available' || (row.has_vf !== true && !row.vf_tracking_disabled);
}

/** « 3/8 completes » — avancement par saison d'une série. */
export function seasonsSummary(seasons) {
  const available = seasons.filter(season => season.status === 'available').length;
  return `${available}/${seasons.length} completes`;
}
