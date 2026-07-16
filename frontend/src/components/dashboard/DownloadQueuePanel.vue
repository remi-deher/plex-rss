<template>
  <section class="panel">
    <div class="panel-head">
      <h2>File de telechargement</h2>
      <RouterLink to="/downloads" class="panel-link">Tout voir</RouterLink>
    </div>
    <article v-for="item in queue" :key="item.id" class="detail-row">
      <div class="inline-row gap-10">
        <img v-if="item.poster_url" :src="item.poster_url" class="mini-poster" alt="" />
        <div>
          <strong>{{ item.title }}</strong>
          <span>{{ item.instance }} — {{ formatDownloadProgress(item) }}</span>
        </div>
      </div>
      <span class="badge dl-badge">
        <Download style="width:12px;height:12px" />
        {{ item.size_left_label || 'En cours' }}
      </span>
    </article>
    <p v-if="!queue.length && !loading" class="empty">Aucun telechargement en cours.</p>
    <p v-if="loading" class="empty"><LoaderCircle class="spin" style="width:16px;height:16px" /> Chargement...</p>
  </section>
</template>

<script setup>
import { Download, LoaderCircle } from '@lucide/vue';

defineProps({
  queue: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
});

function formatDownloadProgress(item) {
  if (item.status === 'completed') return 'Terminé';
  if (item.size_left != null && item.size != null && item.size > 0) {
    const pct = Math.round((1 - item.size_left / item.size) * 100);
    return `${pct}%`;
  }
  return item.status || 'En cours';
}
</script>
