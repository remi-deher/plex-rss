/**
 * Fait passer une affiche par notre proxy quand elle vient d'un hôte que le navigateur
 * refuserait ou n'atteindrait pas : HTTP en clair sur une page HTTPS (mixed content
 * bloqué), ou HTTPS pointant vers une adresse privée (le serveur Plex/*arr du LAN,
 * injoignable depuis l'extérieur).
 *
 * Tout le reste part en direct : une affiche TMDB servie par image.tmdb.org est chargée
 * par le navigateur sur le CDN, en parallèle et sans traverser notre process Python.
 *
 * L'ancien test travaillait sur la chaîne brute (`/\/(192\.168\.|10\.|127\.)/`), ce qui
 * proxifiait à tort toute URL publique dont le chemin commençait par un segment comme
 * `/10.jpg`, et manquait la plage privée 172.16-31.x ainsi que les noms d'hôtes locaux.
 */

// Plages privées RFC 1918 + loopback + lien-local.
const PRIVATE_IPV4 = /^(10\.|127\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.)/;
const LOCAL_SUFFIX = /\.(local|lan|home|internal|localdomain)$/i;

function isPrivateHost(hostname) {
  if (!hostname) return false;
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, '');
  if (host === 'localhost' || PRIVATE_IPV4.test(host)) return true;
  // IPv6 loopback et plage unique-local (fc00::/7).
  if (host === '::1' || host.startsWith('fc') || host.startsWith('fd')) return true;
  if (LOCAL_SUFFIX.test(host)) return true;
  // Nom d'hôte nu (« plex », « nas ») : résolvable seulement sur le réseau local.
  return !host.includes('.');
}

export function proxyUrl(url) {
  if (!url) return url;
  let parsed;
  try {
    parsed = new URL(url, window.location.origin);
  } catch {
    return url;
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return url;
  // Déjà servie par l'app elle-même : rien à proxifier.
  if (parsed.origin === window.location.origin) return url;

  const mixedContent = parsed.protocol === 'http:' && window.location.protocol === 'https:';
  if (!mixedContent && !isPrivateHost(parsed.hostname)) return url;

  return `/api/image-proxy?url=${encodeURIComponent(url)}&width=500&quality=82&format=webp`;
}
