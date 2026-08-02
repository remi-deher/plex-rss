<template>
  <section class="panel span-two">
    <div class="panel-head">
      <h2>Recemment disponibles dans la bibliotheque</h2>
    </div>
    <div class="recently-available-grid">
      <RouterLink v-for="item in items" :key="item.id" class="poster-card recent-link" :to="recentDetailPath(item)">
        <div class="poster-wrap">
          <img v-if="item.poster_url" :src="item.poster_url" :alt="`Affiche de ${item.title}`" loading="lazy" decoding="async" />
          <div v-else class="poster-fallback-inner"><Film /></div>
          <span class="media-type-badge" :class="item.media_type">{{ mediaTypeLabel(item.media_type) }}</span>
        </div>
        <strong>{{ item.title }}</strong>
        <span>{{ formatRelativeDate(item.available_at) }}</span>
      </RouterLink>
    </div>
    <p v-if="!items.length" class="empty">Aucun média disponible récemment.</p>
  </section>
</template>

<script setup>
import { mediaTypeLabel } from '@/utils/labels';
import { Film } from '@lucide/vue';
import { mediaDetailPath } from '@/mediaUrl';

defineProps({ items: { type: Array, default: () => [] } });

function recentDetailPath(item) {
  if (item.library_id) return mediaDetailPath({ library_id: item.library_id }, 'library');
  return mediaDetailPath({ request_id: item.request_id || item.id }, 'request');
}

function formatRelativeDate(v) {
  if (!v) return '-';
  const diff = Date.now() - new Date(v).getTime();
  const days = Math.floor(diff / (1000 * 60 * 60 * 24));
  if (days === 0) return "Aujourd'hui";
  if (days === 1) return "Hier";
  return `Il y a ${days} jours`;
}
</script>

<style scoped>
.recent-link { color: inherit; text-decoration: none; }
</style>
