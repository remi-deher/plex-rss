<template>
  <section v-if="saga?.items?.length" class="drawer-section">
    <h3>Saga{{ saga.name ? ` — ${saga.name}` : '' }}</h3>
    <UiFeedback v-if="requestError" type="error" :message="requestError" dismissible @dismiss="requestError=''" />
    <UiFeedback v-if="requestSuccess" type="success" :message="requestSuccess" dismissible @dismiss="requestSuccess=''" />
    <div class="saga-rail">
      <MediaPosterCard
        v-for="item in saga.items"
        :key="mediaRequestKey(item)"
        :item="item"
        :to="detailPath(item)"
        :action-label="cardActionLabel(item)"
        :requestable="canRequest(item)"
        :request-busy="requesting.includes(mediaRequestKey(item))"
        @request="requestMedia"
      />
    </div>
  </section>
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
</template>

<script setup>
import MediaPosterCard from '@/components/discover/MediaPosterCard.vue';
import RequestOptionsModal from './RequestOptionsModal.vue';
import { mediaRequestKey, useDirectMediaRequest } from '@/composables/useDirectMediaRequest';
import { mediaDetailPath } from '@/mediaUrl';

defineProps({
  saga: { type: Object, default: null },
});

const { requesting, requestError, requestSuccess, requestMedia, optionsDialog, confirmOptions, cancelOptions } = useDirectMediaRequest();

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
</script>

<style scoped>
.saga-rail { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(140px, 160px); gap: var(--space-3); padding: 2px 2px 10px; overflow-x: auto; scroll-snap-type: x proximity; }
.saga-rail > * { scroll-snap-align: start; }
@media (max-width: 640px) { .saga-rail { grid-auto-columns: 130px; } }
</style>
