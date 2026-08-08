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

// Schema custom `plex://` enregistre par l'app iOS/Android — a la difference des Universal
// Links / App Links (https, qui necessitent une association de domaine verifiee cote Plex et
// se sont averes non interceptes en conditions reelles pour ce chemin sur iOS comme sur
// Android), le schema custom n'a besoin que de l'app installee pour repondre. On mime le
// chemin de l'URL web (memes provider/key) : au pire l'app s'ouvre sur son accueil plutot que
// sur le titre exact si ce chemin n'est pas reconnu tel quel.
function buildPlexAppSchemeUrl(guid) {
  const metaKey = parsePlexMetaKey(guid);
  if (!metaKey) return null;
  return `plex://provider/tv.plex.provider.discover/details?key=${encodeURIComponent(metaKey)}`;
}

function buildAndroidIntentUrl(appUrl) {
  // Enveloppe Intent Chrome/Android autour du schema plex:// (et non https://app.plex.tv,
  // dont l'App Link n'est pas reconnue) : ouvre l'app si son intent-filter matche ce schema,
  // sinon bascule automatiquement sur browser_fallback_url — pas besoin de timer JS ici,
  // contrairement a iOS qui n'a pas d'equivalent "fallback intégré au lien".
  const withoutScheme = appUrl.replace(/^plex:\/\//, '');
  const fallback = encodeURIComponent(PLEX_PLAY_STORE_URL);
  return `intent://${withoutScheme}#Intent;scheme=plex;package=${PLEX_ANDROID_PACKAGE};S.browser_fallback_url=${fallback};end`;
}

/**
 * Ouvre un lien Plex en s'adaptant a l'appareil. iOS et Android tentent tous deux le schema
 * custom `plex://` plutot que l'URL https app.plex.tv : les Universal/App Links pour ce chemin
 * ne sont interceptees par l'app sur aucune des deux plateformes en conditions reelles.
 * - Desktop : ouvre app.plex.tv dans un nouvel onglet (comportement historique).
 * - Android : enveloppe plex:// dans un intent Chrome qui bascule automatiquement vers le
 *   Play Store si l'app ne repond pas (pas de timer JS necessaire, gere par l'intent lui-meme).
 * - iOS : navigue vers plex:// puis, si la page reste visible apres un court delai (l'app n'a
 *   donc pas repondu), redirige vers l'App Store.
 */
export function openPlexLink(guid) {
  const webUrl = formatPlexWebUrl(guid);
  if (!webUrl) return;

  const platform = detectPlatform();
  const appUrl = platform === 'android' || platform === 'ios' ? buildPlexAppSchemeUrl(guid) : null;

  if (platform === 'android') {
    if (!appUrl) {
      window.open(webUrl, '_blank', 'noopener');
      return;
    }
    window.location.href = buildAndroidIntentUrl(appUrl);
    return;
  }

  if (platform === 'ios') {
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
