<template>
  <section class="media-rail" :aria-labelledby="headingId" :aria-busy="loading">
    <header>
      <div>
        <span v-if="eyebrow" class="eyebrow">{{ eyebrow }}</span>
        <h2 :id="headingId">{{ title }}</h2>
      </div>
      <div class="rail-actions">
        <RouterLink v-if="moreTo" :to="moreTo">Voir tout</RouterLink>
        <button type="button" aria-label="Faire défiler vers la gauche" @click="scroll(-1)"><ChevronLeft /></button>
        <button type="button" aria-label="Faire défiler vers la droite" @click="scroll(1)"><ChevronRight /></button>
      </div>
    </header>
    <MediaRailSkeleton v-if="loading" />
    <UiFeedback v-else-if="error" type="error" :message="error" retry @retry="$emit('retry')" />
    <div
      v-else-if="items.length"
      ref="track"
      class="media-rail-track"
      role="region"
      tabindex="0"
      :aria-label="`${title}, ${items.length} médias`"
    >
      <MediaPosterCard
        v-for="item in items"
        :key="`${item.media_type}:${item.tmdb_id || item.id}`"
        :item="item"
        :to="itemPath(item)"
        :action-label="actionLabel(item)"
        :requestable="allowRequest && canRequest(item)"
        :request-busy="requesting.includes(itemKey(item))"
        @request="$emit('request', $event)"
      />
    </div>
    <p v-else class="empty">Aucun média à afficher.</p>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue';
import { ChevronLeft, ChevronRight } from '@lucide/vue';
import { mediaDetailPath } from '@/mediaUrl';
import MediaPosterCard from './MediaPosterCard.vue';
import MediaRailSkeleton from './MediaRailSkeleton.vue';

const props = defineProps({
  title: { type: String, required: true },
  eyebrow: { type: String, default: '' },
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  moreTo: { type: [String, Object], default: '' },
  allowRequest: { type: Boolean, default: false },
  requesting: { type: Array, default: () => [] },
});
defineEmits(['retry', 'request']);

const track = ref(null);
const headingId = computed(() => `rail-${props.title.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`);

function itemPath(item) {
  const kind = item.library_id ? 'library' : item.request_id ? 'request' : 'discover';
  return mediaDetailPath(item, kind);
}
function actionLabel(item) {
  if (item.in_library || item.library_id) return 'Voir la fiche';
  if (item.requested || item.request_id) return 'Suivre la demande';
  return 'Demander';
}
function itemKey(item) {
  return `${item.media_type}:${item.tmdb_id || item.id}`;
}
function canRequest(item) {
  return !item.in_library && !item.library_id && !item.requested && !item.request_id;
}
function scroll(direction) {
  track.value?.scrollBy({ left: direction * Math.max(track.value.clientWidth * .8, 280), behavior: 'smooth' });
}
</script>

<style scoped>
.media-rail { display: grid; gap: 12px; min-width: 0; }
.media-rail header { display: flex; align-items: end; justify-content: space-between; gap: 16px; }
.media-rail h2 { margin: 2px 0 0; font-size: 1.15rem; }
.rail-actions { display: flex; align-items: center; gap: 7px; }
.rail-actions > a { color: var(--muted); font-size: .8rem; text-decoration: none; }
.rail-actions button {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
  color: var(--text);
}
.rail-actions svg { width: 16px; }
.media-rail-track {
  display: grid;
  grid-auto-columns: clamp(132px, 16vw, 190px);
  grid-auto-flow: column;
  gap: 14px;
  padding: 2px 2px 10px;
  overflow-x: auto;
  scroll-behavior: smooth;
  scroll-snap-type: x proximity;
  scrollbar-width: thin;
}
.media-rail-track > * { scroll-snap-align: start; }
@media (max-width: 640px) {
  .rail-actions button { display: none; }
  .media-rail-track { grid-auto-columns: minmax(128px, 42vw); margin-right: -12px; }
}
</style>
