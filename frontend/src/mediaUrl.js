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

const PLEX_ANDROID_PACKAGE = 'com.plexapp.android';
const PLEX_PLAY_STORE_URL = `https://play.google.com/store/apps/details?id=${PLEX_ANDROID_PACKAGE}`;
const PLEX_APP_STORE_URL = 'https://apps.apple.com/app/plex/id383457673';

/**
 * Detecte grossierement la plateforme pour adapter l'ouverture des liens Plex.
 */
export function detectPlatform() {
  if (typeof navigator === 'undefined') return 'desktop';
  const ua = navigator.userAgent || '';
  if (/android/i.test(ua)) return 'android';
  const isIOS = /iPad|iPhone|iPod/.test(ua)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1); // iPadOS se declare comme Mac
  if (isIOS) return 'ios';
  return 'desktop';
}

function buildAndroidIntentUrl(webUrl) {
  // Syntaxe Intent Chrome/Android : ouvre l'app si le lien https est associe (App Links),
  // sinon bascule automatiquement sur browser_fallback_url — pas besoin de timer JS.
  const withoutScheme = webUrl.replace(/^https?:\/\//, '');
  const fallback = encodeURIComponent(PLEX_PLAY_STORE_URL);
  return `intent://${withoutScheme}#Intent;scheme=https;package=${PLEX_ANDROID_PACKAGE};S.browser_fallback_url=${fallback};end`;
}

/**
 * Ouvre un lien Plex en s'adaptant a l'appareil :
 * - Desktop : ouvre app.plex.tv dans un nouvel onglet (comportement historique).
 * - Android : passe par un intent Chrome qui ouvre l'app Plex si installee (via les App
 *   Links associes a app.plex.tv), sinon bascule automatiquement vers le Play Store.
 * - iOS : navigue vers l'URL https (interceptee nativement par l'app via Universal Links
 *   si installee) puis, si la page reste visible passe un court delai (l'app n'a donc pas
 *   intercepte le lien), redirige vers l'App Store.
 */
export function openPlexLink(guid) {
  const webUrl = formatPlexWebUrl(guid);
  if (!webUrl) return;

  const platform = detectPlatform();

  if (platform === 'android') {
    window.location.href = buildAndroidIntentUrl(webUrl);
    return;
  }

  if (platform === 'ios') {
    let intercepted = false;
    const markIntercepted = () => { intercepted = true; };
    document.addEventListener('visibilitychange', markIntercepted, { once: true });
    window.addEventListener('pagehide', markIntercepted, { once: true });

    window.location.href = webUrl;

    setTimeout(() => {
      document.removeEventListener('visibilitychange', markIntercepted);
      if (!intercepted) {
        window.location.href = PLEX_APP_STORE_URL;
      }
    }, 1500);
    return;
  }

  window.open(webUrl, '_blank', 'noopener');
}
