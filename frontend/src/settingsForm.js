// Etat partage entre SettingsView.vue et tous ses onglets : un seul `form` reactive,
// un seul chargement/sauvegarde, pour que "Enregistrer" en haut de page couvre tous
// les champs quel que soit l'onglet visible au moment du clic.
//
// Singleton de module (pas une factory par composant) : chaque `import` de ce
// fichier reçoit exactement le même `form`/`error`/`message`, comme le ferait un
// store Pinia — plus léger ici vu la taille de l'état.
import { reactive, ref } from 'vue';
import { api } from '@/api';

export const secretFields = ['plex_token', 'seer_api_key', 'tmdb_api_key', 'smtp_password', 'telegram_bot_token', 'ntfy_token', 'gotify_token'];

export const form = reactive({
  plex_url: '', plex_token: '', plex_verify_ssl: true, plex_rss_url: '',
  seer_enabled: false, seer_url: '', seer_api_key: '', seer_mode: 'observer', seer_send_requests: false, seer_fallback_arr: false, seer_suppress_notifications: true,
  tmdb_api_key: '', tmdb_enabled: true,
  webhook_secret: '',
  email_enabled: false, smtp_host: '', smtp_port: 587, smtp_user: '', smtp_password: '', smtp_from: '', smtp_tls: true, admin_notification_email: '',
  email_on_request: true, email_on_available: true, email_on_failure: true, email_on_vf_available: true,
  discord_enabled: false, discord_webhook_url: '', discord_send_request: true, discord_send_available: true, discord_send_failure: true,
  telegram_enabled: false, telegram_bot_token: '', telegram_chat_id: '', telegram_send_request: true, telegram_send_available: true, telegram_send_failure: true,
  ntfy_enabled: false, ntfy_url: '', ntfy_topic: '', ntfy_token: '', ntfy_send_request: true, ntfy_send_available: true, ntfy_send_failure: true,
  gotify_enabled: false, gotify_url: '', gotify_token: '', gotify_send_request: true, gotify_send_available: true, gotify_send_failure: true,
  movie_notify_language: true, series_notify_language: true, series_notify_granularity: 'jalons',
  poll_interval_seconds: 300, watchlist_source_priority: 'api', watchlist_fallback_enabled: true, require_approval: false,
  vff_enabled: true, vff_libraries: '', vff_recheck_interval_minutes: 60, vff_auto_search: false,
  notification_log_retention_days: 30, poll_history_retention_days: 30, arr_poll_interval_seconds: 900, digest_enabled: false, digest_hour: 8,
  plex_sync_hour: 3,
  torrent_required_keywords: '', torrent_forbidden_keywords: '', torrent_min_size_gb: null, torrent_max_size_gb: null,
  torrent_ratio_limit: null, torrent_seed_time_limit_hours: null, torrent_auto_delete_files: false,
});

export const saving = ref(false);
export const error = ref('');
export const message = ref('');

// `form[secretField]` est toujours vide juste apres load() (voir ci-dessous) : un badge
// de statut qui se fie a la valeur du champ secret (ex: Plex, sans autre indicateur
// "actif") le verrait donc toujours comme non configure, meme quand il l'est reellement.
// Capture presence/absence AVANT le blanking, pour que l'UI puisse s'y fier a la place.
export const secretsPresent = reactive(Object.fromEntries(secretFields.map(k => [k, false])));

export function success(text) { message.value = text; error.value = ''; }
export function fail(err) { error.value = err.message || String(err); }

export async function load() {
  try {
    const data = await api('/api/settings');
    for (const key of Object.keys(form)) if (data[key] != null) form[key] = data[key];
    for (const key of secretFields) {
      secretsPresent[key] = Boolean(form[key]);
      form[key] = '';
    }
  } catch (e) {
    fail(e);
  }
}

export async function save() {
  saving.value = true;
  const payload = { ...form };
  for (const key of secretFields) if (!payload[key]) delete payload[key];
  try {
    await api('/api/settings', { method: 'PUT', body: JSON.stringify(payload) });
    success('Configuration enregistree.');
  } catch (e) {
    fail(e);
  } finally {
    saving.value = false;
  }
}

// Sauvegarde puis lance un test de connexion nomme (ex: '/api/test/plex-api') : le test
// doit voir les valeurs fraichement saisies, d'ou le save() prealable.
export async function testSaved(path) {
  await save();
  try {
    const data = await api(path, { method: 'POST' });
    success(data.message || 'Connexion valide.');
    return data;
  } catch (e) {
    fail(e);
    return null;
  }
}
