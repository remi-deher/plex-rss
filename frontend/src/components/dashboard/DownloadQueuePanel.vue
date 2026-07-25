<template>
  <section class="panel">
    <div class="panel-head">
      <h2>File de telechargement</h2>
      <RouterLink to="/downloads" class="panel-link">Tout voir</RouterLink>
    </div>
    <component :is="detailPath(item)?'RouterLink':'article'" v-for="item in queue" :key="item.id||item.queue_id||`${item.instance_id}:${item.title}`" :to="detailPath(item)" class="detail-row queue-row">
      <div class="inline-row gap-10">
        <img v-if="item.poster_url" :src="item.poster_url" class="mini-poster" :alt="`Affiche de ${item.title}`" />
        <div>
          <strong>{{ item.title }}</strong>
          <span>{{ item.instance }} — {{ formatDownloadProgress(item) }}</span>
        </div>
      </div>
      <span class="badge dl-badge">
        <Download style="width:12px;height:12px" />
        {{ item.size_left_label || 'En cours' }}
      </span>
    </component>
    <p v-if="!queue.length && !loading" class="empty">Aucun telechargement en cours.</p>
    <p v-if="loading" class="empty"><LoaderCircle class="spin" style="width:16px;height:16px" /> Chargement...</p>
  </section>
</template>

<script setup>
import { Download, LoaderCircle } from '@lucide/vue';
import { mediaDetailPath } from '@/mediaUrl';

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

function detailPath(item) {
  if (item.library_id) return mediaDetailPath({ library_id: item.library_id }, 'library');
  const requestId = item.request_id || item.linked_request_id;
  return requestId ? mediaDetailPath({ request_id: requestId }, 'request') : null;
}
</script>

<style scoped>
.queue-row { color: inherit; text-decoration: none; }
</style>
