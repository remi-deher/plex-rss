import { ref } from 'vue';
import { api } from '@/api';
import { loadSession } from '@/composables/useSession';

export function mediaRequestKey(item) {
  return `${item.media_type}:${item.tmdb_id || item.id}`;
}

/** Demande un média avec les réglages par défaut de Sonarr/Radarr, sans formulaire. */
export function useDirectMediaRequest({ onUpdated } = {}) {
  const requesting = ref([]);
  const requestError = ref('');
  const requestSuccess = ref('');

  async function requestMedia(item) {
    const key = mediaRequestKey(item);
    if (requesting.value.includes(key) || item.in_library || item.requested || item.request_id) return;
    requesting.value = [...requesting.value, key];
    requestError.value = '';
    requestSuccess.value = '';
    try {
      const session = await loadSession();
      const data = await api('/api/media/add', {
        method: 'POST',
        body: JSON.stringify({
          title: item.title || item.name,
          year: item.year || null,
          media_type: item.media_type,
          tmdb_id: item.tmdb_id || null,
          poster_url: item.poster_url || null,
          overview: item.overview || null,
          plex_user_id: session?.plex_user_id || null,
          auto_search: true,
        }),
      });
      const update = {
        requested: true,
        request_id: data.request_id || item.request_id || null,
        request_status: data.pending_approval ? 'pending_approval' : 'sent_to_arr',
        is_downloading: false,
      };
      Object.assign(item, update);
      onUpdated?.(item, update);
      requestSuccess.value = data.already_existed
        ? `${item.title || item.name} était déjà demandé.`
        : `Demande envoyée pour ${item.title || item.name}.`;
    } catch (error) {
      requestError.value = error.message || "Impossible d'envoyer la demande.";
    } finally {
      requesting.value = requesting.value.filter(entry => entry !== key);
    }
  }

  return { requesting, requestError, requestSuccess, requestMedia };
}
