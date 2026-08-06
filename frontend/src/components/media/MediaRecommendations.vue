<template>
  <section v-if="items.length" class="drawer-section">
    <h3>{{ title }}</h3>
    <div class="media-grid recommendation-grid">
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
.recommendation-grid { grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: var(--space-3); }
</style>
