<template>
  <section v-if="items.length" class="drawer-section">
    <h3>{{ title }}</h3>
    <div class="recommendation-rail">
      <MediaPosterCard
        v-for="item in items.slice(0, 12)"
        :key="`${item.media_type}:${item.tmdb_id}`"
        :item="item"
        :to="detailPath(item)"
        action-label="Voir la fiche"
      />
    </div>
  </section>
</template>

<script setup>
import MediaPosterCard from '@/components/discover/MediaPosterCard.vue';
import { mediaDetailPath } from '@/mediaUrl';

defineProps({
  items: { type: Array, default: () => [] },
  title: { type: String, default: 'Recommandations' },
});
defineEmits(['open']);
function detailPath(item) { return mediaDetailPath(item, item.library_id ? 'library' : item.request_id ? 'request' : 'discover', { discover: true }); }
</script>

<style scoped>
.recommendation-rail { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(140px, 160px); gap: var(--space-3); padding: 2px 2px 10px; overflow-x: auto; scroll-snap-type: x proximity; }
.recommendation-rail > * { scroll-snap-align: start; }
@media (max-width: 640px) { .recommendation-rail { grid-auto-columns: 130px; } }
</style>
