<template>
  <div class="page discover-source-page">
    <RouterLink class="back-link" to="/discover">← Retour à la découverte</RouterLink>
    <PageHeader :title="sourceName" :description="sourceDescription" />

    <UiFeedback v-if="requestError" type="error" :message="requestError" dismissible @dismiss="requestError=''" />
    <UiFeedback v-if="requestSuccess" type="success" :message="requestSuccess" dismissible @dismiss="requestSuccess=''" />

    <div class="segmented source-types" aria-label="Type de média">
      <button
        v-for="entry in availableMediaTypes"
        :key="entry.value"
        :class="{ active: mediaType === entry.value }"
        :aria-pressed="mediaType === entry.value"
        @click="setMediaType(entry.value)"
      >{{ entry.label }}</button>
    </div>

    <UiFeedback v-if="error" type="error" :message="error" retry @retry="load" />
    <UiFeedback v-else-if="loading" type="loading" message="Chargement du catalogue…" />
    <template v-else>
      <section class="media-grid source-grid" :aria-busy="loadingMore">
        <MediaPosterCard
          v-for="item in items"
          :key="mediaRequestKey(item)"
          :item="item"
          :to="detailPath(item)"
          :action-label="cardActionLabel(item)"
          :requestable="canRequest(item)"
          :request-busy="requesting.includes(mediaRequestKey(item))"
          @request="requestMedia"
        />
      </section>
      <p v-if="!items.length" class="empty">Aucun média trouvé pour cette sélection.</p>
      <LoadMore :has-more="hasMore" :loading="loadingMore" label="Charger plus de médias" @load="loadMore" />
    </template>

    <RequestOptionsModal
      :open="optionsDialog.open"
      :media-title="optionsDialog.item ? (optionsDialog.item.title || optionsDialog.item.name) : ''"
      :requesters="optionsDialog.requesters"
      :folders="optionsDialog.folders"
      :plex-user-id="optionsDialog.plexUserId"
      :root-folder="optionsDialog.rootFolder"
      :busy="optionsDialog.busy"
      @update:plex-user-id="v => optionsDialog.plexUserId = v"
      @update:root-folder="v => optionsDialog.rootFolder = v"
      @cancel="cancelOptions"
      @confirm="confirmOptions"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { api } from '@/api';
import LoadMore from '@/components/ui/LoadMore.vue';
import MediaPosterCard from '@/components/discover/MediaPosterCard.vue';
import RequestOptionsModal from '@/components/media/RequestOptionsModal.vue';
import { mediaDetailPath } from '@/mediaUrl';
import { mediaRequestKey, useDirectMediaRequest } from '@/composables/useDirectMediaRequest';

const route = useRoute();
const items = ref([]);
const mediaType = ref(route.params.kind === 'network' ? 'show' : 'all');
const loading = ref(false);
const loadingMore = ref(false);
const error = ref('');
const page = ref(1);
const totalPages = ref(1);
const sourceName = computed(() => String(route.query.name || 'Découverte'));
const sourceDescription = computed(() => ({
  provider: `Films et séries disponibles sur ${sourceName.value}`,
  network: `Séries diffusées par ${sourceName.value}`,
  company: `Productions et coproductions de ${sourceName.value}`,
})[route.params.kind] || 'Sélection de médias');
const availableMediaTypes = computed(() => route.params.kind === 'network'
  ? [{ value: 'show', label: 'Séries' }]
  : [{ value: 'all', label: 'Tout' }, { value: 'movie', label: 'Films' }, { value: 'show', label: 'Séries' }]);
const hasMore = computed(() => page.value < totalPages.value);
const { requesting, requestError, requestSuccess, requestMedia, optionsDialog, confirmOptions, cancelOptions } = useDirectMediaRequest({
  onUpdated: (changed, update) => {
    for (const item of items.value) {
      if (mediaRequestKey(item) === mediaRequestKey(changed)) Object.assign(item, update);
    }
  },
});

function detailPath(item) {
  const kind = item.library_id ? 'library' : item.request_id ? 'request' : 'discover';
  return mediaDetailPath(item, kind);
}
function cardActionLabel(item) {
  if (item.in_library || item.library_id) return 'Voir la fiche';
  if (item.requested || item.request_id) return 'Suivre la demande';
  return 'Demander';
}
function canRequest(item) {
  return !item.in_library && !item.library_id && !item.requested && !item.request_id;
}
async function setMediaType(value) {
  mediaType.value = value;
  await load();
}
async function load({ append = false } = {}) {
  const targetPage = append ? page.value + 1 : 1;
  if (append) loadingMore.value = true;
  else loading.value = true;
  error.value = '';
  try {
    const payload = await api(`/api/discover/source/${route.params.kind}/${route.params.id}?media_type=${mediaType.value}&page=${targetPage}`);
    const incoming = payload.items || [];
    if (append) {
      const known = new Set(items.value.map(mediaRequestKey));
      items.value = [...items.value, ...incoming.filter(item => !known.has(mediaRequestKey(item)))];
    } else {
      items.value = incoming;
    }
    page.value = payload.page || targetPage;
    totalPages.value = payload.total_pages || 1;
  } catch (loadError) {
    error.value = loadError.message;
    if (!append) items.value = [];
  } finally {
    loading.value = false;
    loadingMore.value = false;
  }
}
function loadMore() {
  if (!loadingMore.value && hasMore.value) load({ append: true });
}

watch(() => [route.params.kind, route.params.id], () => {
  mediaType.value = route.params.kind === 'network' ? 'show' : 'all';
  load();
});
onMounted(load);
</script>

<style scoped>
.discover-source-page { gap: var(--space-4); }
.back-link { justify-self: start; color: var(--muted); font-size: var(--fs-sm); text-decoration: none; }
.source-types { justify-self: start; }
.source-grid { align-items: start; }
.load-more { display: flex; justify-content: center; padding: 20px; }
</style>
