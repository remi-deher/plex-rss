// Construit l'URL de la page de detail media (/media/:kind/:id) a partir d'un item
// heterogene provenant de Bibliotheque, Demandes, Calendrier ou Decouvrir.
export function mediaDetailPath(item, kindHint, options = {}) {
  const kind = kindHint || item._kind;
  const base = options.discover ? '/discover/media' : '/media';
  if (kind === 'request' || item.request_id) {
    return `${base}/request/${item.request_id || item.id}`;
  }
  if (kind === 'library' || item.library_id) {
    return `${base}/library/${item.library_id || item.id}`;
  }
  // Decouvrir (pas encore suivi)
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
  return `${base}/discover/${id}${qs ? `?${qs}` : ''}`;
}

/**
 * Formate un GUID Plex (ex. `plex://show/6972465963351c6b1a33d013` ou `/library/metadata/123`)
 * en une URL Web Plex valide pour app.plex.tv.
 */
export function formatPlexWebUrl(guid) {
  if (!guid) return null;
  if (typeof guid !== 'string') return null;
  if (guid.startsWith('http://') || guid.startsWith('https://')) return guid;

  // Extrait l'ID unique si sous la forme plex://movie/xxx ou plex://show/xxx
  let metaKey = guid;
  if (guid.startsWith('plex://')) {
    const parts = guid.replace('plex://', '').split('/');
    const id = parts[parts.length - 1];
    metaKey = `/library/metadata/${id}`;
  } else if (!guid.startsWith('/')) {
    metaKey = `/library/metadata/${guid}`;
  }

  return `https://app.plex.tv/desktop/#!/provider/tv.plex.provider.discover/details?key=${encodeURIComponent(metaKey)}`;
}
