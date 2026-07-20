<template>
  <section class="panel span-two">
    <div class="panel-head">
      <h2>Recemment disponibles dans la bibliotheque</h2>
    </div>
    <div class="recently-available-grid">
      <div v-for="item in items" :key="item.id" class="poster-card">
        <div class="poster-wrap">
          <img v-if="item.poster_url" :src="item.poster_url" alt="Poster" />
          <div v-else class="poster-fallback-inner"><Film /></div>
          <span class="media-type-badge" :class="item.media_type">{{ item.media_type === 'movie' ? 'Film' : 'Série' }}</span>
        </div>
        <strong>{{ item.title }}</strong>
        <span>{{ formatRelativeDate(item.available_at) }}</span>
      </div>
    </div>
    <p v-if="!items.length" class="empty">Aucun média disponible récemment.</p>
  </section>
</template>

<script setup>
import { Film } from '@lucide/vue';

defineProps({ items: { type: Array, default: () => [] } });

function formatRelativeDate(v) {
  if (!v) return '-';
  const diff = Date.now() - new Date(v).getTime();
  const days = Math.floor(diff / (1000 * 60 * 60 * 24));
  if (days === 0) return "Aujourd'hui";
  if (days === 1) return "Hier";
  return `Il y a ${days} jours`;
}
</script>
