// Construit l'URL de la page de detail media (/media/:kind/:id) a partir d'un item
// heterogene provenant de Bibliotheque, Demandes, Calendrier ou Decouvrir — chacun a
// historiquement sa propre forme d'objet (voir les anciens modes du drawer).
export function mediaDetailPath(item, kindHint) {
  const kind = kindHint || item._kind;
  if (kind === 'request' || item.request_id) {
    return `/media/request/${item.request_id || item.id}`;
  }
  if (kind === 'library' || item.library_id) {
    return `/media/library/${item.library_id || item.id}`;
  }
  // Decouvrir (pas encore suivi) : necessite le type de media + un identifiant TMDB/TVDB.
  // `id_type` precise quel type d'identifiant est encode dans le segment :id, pour que
  // la page sache s'il faut interroger /api/discover/detail avec tmdb_id ou tvdb_id.
  const params = new URLSearchParams();
  if (item.media_type) params.set('media_type', item.media_type);
  let id = item.id;
  if (item.tmdb_id) {
    id = item.tmdb_id;
  } else if (item.tvdb_id) {
    id = item.tvdb_id;
    params.set('id_type', 'tvdb');
  }
  const qs = params.toString();
  return `/media/discover/${id}${qs ? `?${qs}` : ''}`;
}
