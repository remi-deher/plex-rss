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

// Extrait la cle /library/metadata/xxx d'un GUID Plex (plex://movie/xxx, plex://show/xxx,
// deja une cle /library/metadata/xxx, ou un id brut). Retourne null pour une URL http(s) deja
// complete : ce cas est gere separement par les appelants.
function parsePlexMetaKey(guid) {
  if (!guid) return null;
  if (typeof guid !== 'string') return null;
  if (guid.startsWith('http://') || guid.startsWith('https://')) return null;

  if (guid.startsWith('plex://')) {
    const parts = guid.replace('plex://', '').split('/');
    const id = parts[parts.length - 1];
    return `/library/metadata/${id}`;
  }
  if (guid.startsWith('/')) return guid;
  return `/library/metadata/${guid}`;
}

/**
 * Formate un GUID Plex (ex. `plex://show/6972465963351c6b1a33d013` ou `/library/metadata/123`)
 * en une URL Web Plex valide pour app.plex.tv.
 */
export function formatPlexWebUrl(guid) {
  if (typeof guid === 'string' && (guid.startsWith('http://') || guid.startsWith('https://'))) return guid;
  const metaKey = parsePlexMetaKey(guid);
  if (!metaKey) return null;
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

// Schema custom `plex://` enregistre par l'app iOS/Android — a la difference des Universal
// Links (https), il n'a pas besoin d'association de domaine verifiee cote Plex pour ouvrir
// l'app, et Safari ignore silencieusement la navigation si l'app n'est pas installee (pas de
// page d'erreur). On mime le chemin de l'URL web (memes provider/key) : au pire l'app s'ouvre
// sur son accueil plutot que sur le titre exact si ce chemin n'est pas reconnu tel quel.
function buildPlexAppSchemeUrl(guid) {
  const metaKey = parsePlexMetaKey(guid);
  if (!metaKey) return null;
  return `plex://provider/tv.plex.provider.discover/details?key=${encodeURIComponent(metaKey)}`;
}

/**
 * Ouvre un lien Plex en s'adaptant a l'appareil :
 * - Desktop : ouvre app.plex.tv dans un nouvel onglet (comportement historique).
 * - Android : passe par un intent Chrome qui ouvre l'app Plex si installee (via les App
 *   Links associes a app.plex.tv), sinon bascule automatiquement vers le Play Store.
 * - iOS : tente le schema custom `plex://` (l'app doit etre installee pour repondre — testee
 *   en conditions reelles, les Universal Links https ne sont pas interceptes pour ce chemin),
 *   puis si la page reste visible apres un court delai (l'app n'a donc pas repondu), redirige
 *   vers l'App Store.
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
    const appUrl = buildPlexAppSchemeUrl(guid);
    if (!appUrl) {
      // GUID deja sous forme d'URL http(s) complete : pas de schema custom fiable a
      // construire, on se contente d'ouvrir la page web comme sur desktop.
      window.open(webUrl, '_blank', 'noopener');
      return;
    }

    let intercepted = false;
    const markIntercepted = () => { intercepted = true; };
    document.addEventListener('visibilitychange', markIntercepted, { once: true });
    window.addEventListener('pagehide', markIntercepted, { once: true });

    window.location.href = appUrl;

    setTimeout(() => {
      document.removeEventListener('visibilitychange', markIntercepted);
      if (!intercepted) {
        window.location.href = PLEX_APP_STORE_URL;
      }
    }, 1200);
    return;
  }

  window.open(webUrl, '_blank', 'noopener');
}
