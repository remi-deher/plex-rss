export const STATUSES = ['pending_approval', 'pending', 'sent_to_arr', 'available', 'failed', 'rejected'];
export const TYPES = ['movie', 'show'];

export function statusLabel(value) {
  return ({
    pending_approval: 'A approuver',
    pending: 'En attente',
    sent_to_arr: 'Transmise',
    available: 'Disponible',
    failed: 'Echec',
    rejected: 'Refusee',
  })[value] || value;
}

export function typeLabel(value) {
  return value === 'show' ? 'Series' : 'Films';
}

export function formatDate(value) {
  return value ? new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium' }).format(new Date(value)) : '-';
}

export function proxyUrl(url) {
  if (!url) return url;
  if (url.startsWith('http://') || (url.startsWith('https://') && /\/(192\.168\.|10\.|127\.)/.test(url))) {
    return `/api/image-proxy?url=${encodeURIComponent(url)}`;
  }
  return url;
}
