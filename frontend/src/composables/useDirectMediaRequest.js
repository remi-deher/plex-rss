import { ref } from 'vue';
import { api } from '@/api';
import { canModerateSession, loadSession } from '@/composables/useSession';

export function mediaRequestKey(item) {
  return `${item.media_type}:${item.tmdb_id || item.id}`;
}

const folderCache = {};

async function loadRequesterOptions(mediaType) {
  const service = mediaType === 'show' ? 'sonarr' : 'radarr';
  folderCache[service] ||= api(`/api/${service}/folders`).catch(() => []);
  const [requesters, folders] = await Promise.all([
    api('/api/discover/requesters').catch(() => []),
    folderCache[service],
  ]);
  return { requesters, folders };
}

/** Demande un média avec les réglages par défaut de Sonarr/Radarr, sans formulaire —
 * sauf pour un administrateur ou modérateur, qui passe par une modale de configuration
 * (demandeur, dossier racine) avant l'envoi. */
export function useDirectMediaRequest({ onUpdated } = {}) {
  const requesting = ref([]);
  const requestError = ref('');
  const requestSuccess = ref('');
  const optionsDialog = ref({
    open: false, item: null, plexUserId: '', rootFolder: '', requesters: [], folders: [], busy: false,
  });

  async function sendRequest(item, { plexUserId, rootFolder } = {}) {
    const key = mediaRequestKey(item);
    requesting.value = [...requesting.value, key];
    requestError.value = '';
    requestSuccess.value = '';
    try {
      const session = plexUserId ? null : await loadSession();
      const data = await api('/api/media/add', {
        method: 'POST',
        body: JSON.stringify({
          title: item.title || item.name,
          year: item.year || null,
          media_type: item.media_type,
          tmdb_id: item.tmdb_id || null,
          poster_url: item.poster_url || null,
          overview: item.overview || null,
          plex_user_id: plexUserId || session?.plex_user_id || null,
          ...(rootFolder ? { root_folder: rootFolder } : {}),
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

  async function requestMedia(item) {
    const key = mediaRequestKey(item);
    if (requesting.value.includes(key) || optionsDialog.value.open || item.in_library || item.requested || item.request_id) return;

    const session = await loadSession();
    if (!canModerateSession(session)) {
      await sendRequest(item);
      return;
    }

    optionsDialog.value = {
      open: true, item, plexUserId: session?.plex_user_id || '', rootFolder: '',
      requesters: [], folders: [], busy: false,
    };
    try {
      const { requesters, folders } = await loadRequesterOptions(item.media_type);
      if (optionsDialog.value.item !== item) return;
      optionsDialog.value = {
        ...optionsDialog.value,
        requesters,
        folders,
        plexUserId: requesters.find(user => user.plex_user_id === optionsDialog.value.plexUserId)?.plex_user_id
          || optionsDialog.value.plexUserId || requesters[0]?.plex_user_id || '',
      };
    } catch (error) {
      requestError.value = error.message || "Impossible de charger les options de demande.";
    }
  }

  async function confirmOptions() {
    const { item, plexUserId, rootFolder } = optionsDialog.value;
    if (!item) return;
    optionsDialog.value = { ...optionsDialog.value, busy: true };
    await sendRequest(item, { plexUserId, rootFolder });
    optionsDialog.value = { ...optionsDialog.value, open: false, busy: false, item: null };
  }

  function cancelOptions() {
    optionsDialog.value = { ...optionsDialog.value, open: false, item: null };
  }

  return {
    requesting, requestError, requestSuccess, requestMedia,
    optionsDialog, confirmOptions, cancelOptions,
  };
}
