<template>
  <section class="panel span-two">
    <div class="panel-head">
      <h2>Prochaines sorties</h2>
      <RouterLink to="/calendar" class="panel-link">Voir le calendrier</RouterLink>
    </div>
    <div class="upcoming-grid">
      <div v-for="item in items" :key="item.id" class="upcoming-card">
        <div class="upcoming-poster">
          <img v-if="item.poster_url" :src="item.poster_url" alt="" loading="lazy" />
          <div v-else class="poster-fallback-inner"><Film /></div>
          <span class="upcoming-type-badge">{{ item.media_type === 'show' ? 'Série' : 'Film' }}</span>
        </div>
        <div class="upcoming-info">
          <strong>{{ item.title }}</strong>
          <span class="upcoming-label">{{ item.label }}</span>
          <span class="upcoming-date">{{ formatUpcomingDate(item.release_date) }}</span>
        </div>
      </div>
    </div>
    <p v-if="!items.length" class="empty">Aucune sortie à venir.</p>
  </section>
</template>

<script setup>
import { Film } from '@lucide/vue';

defineProps({ items: { type: Array, default: () => [] } });

function formatUpcomingDate(v) {
  if (!v) return '-';
  return new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(v));
}
</script>
