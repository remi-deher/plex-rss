<template>
  <section class="panel">
    <div class="panel-head">
      <h2>Demandes les plus populaires</h2>
    </div>
    <article v-for="item in items" :key="item.id" class="detail-row">
      <div class="inline-row gap-10">
        <img v-if="item.poster_url" :src="item.poster_url" class="mini-poster" alt="" />
        <div v-else class="mini-poster"><Film style="width: 14px; height: 20px; margin: 8px 5px;" /></div>
        <div>
          <strong>{{ item.title }}</strong>
          <span>{{ item.media_type === 'movie' ? 'Film' : 'Série' }}</span>
        </div>
      </div>
      <span class="badge available">{{ item.count }} demandeurs</span>
    </article>
    <p v-if="!items.length" class="empty">Aucune demande multiple.</p>
  </section>
</template>

<script setup>
import { Film } from '@lucide/vue';

defineProps({ items: { type: Array, default: () => [] } });
</script>
