<template>
  <section class="panel span-two">
    <div class="panel-head">
      <h2>Prochaines sorties</h2>
      <RouterLink to="/calendar" class="panel-link">Voir le calendrier</RouterLink>
    </div>
    <div class="upcoming-grid">
      <div v-for="item in items" :key="item.id" class="upcoming-card">
        <div class="upcoming-poster">
          <img v-if="item.poster_url" :src="item.poster_url" :alt="`Affiche de ${item.title}`" loading="lazy" />
          <div v-else class="poster-fallback-inner"><Film /></div>
          <span class="upcoming-type-badge">{{ mediaTypeLabel(item.media_type) }}</span>
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
import { mediaTypeLabel } from '@/utils/labels';
import { formatReleaseDate as formatUpcomingDate } from '@/utils/format';
import { Film } from '@lucide/vue';

defineProps({ items: { type: Array, default: () => [] } });

</script>
