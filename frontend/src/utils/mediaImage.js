/**
 * Fait passer une affiche par notre proxy quand elle vient d'un hôte que le navigateur
 * refuserait ou n'atteindrait pas : HTTP en clair sur une page HTTPS (mixed content
 * bloqué), ou HTTPS pointant vers une IP privée (le serveur Plex/*arr du LAN, injoignable
 * depuis l'extérieur).
 */
export function proxyUrl(url) {
  if (!url) return url;
  if (url.startsWith('http://') || (url.startsWith('https://') && /\/(192\.168\.|10\.|127\.)/.test(url))) {
    return `/api/image-proxy?url=${encodeURIComponent(url)}&width=500&quality=82&format=webp`;
  }
  return url;
}
