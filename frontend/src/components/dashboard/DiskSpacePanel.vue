<template>
  <section class="panel">
    <div class="panel-head">
      <h2>Espace disque disponible</h2>
    </div>

    <div v-if="categorized.common.length" class="volume-group">
      <h3 class="volume-group-title">Espace Commun</h3>
      <article v-for="volume in categorized.common" :key="volume.path" class="detail-row flex-column gap-6">
        <div class="inline-row justify-between w-100">
          <strong>{{ volume.path }}</strong>
          <span>{{ formatBytes(volume.free_bytes) }} libres sur {{ formatBytes(volume.total_bytes) }}</span>
        </div>
        <div class="progress-bar-wrap">
          <div class="progress-bar" :style="{ width: `${(volume.total_bytes - volume.free_bytes) / volume.total_bytes * 100}%` }"></div>
        </div>
      </article>
    </div>

    <div v-if="categorized.sonarr.length" class="volume-group">
      <h3 class="volume-group-title">Sonarr</h3>
      <article v-for="volume in categorized.sonarr" :key="volume.path" class="detail-row flex-column gap-6">
        <div class="inline-row justify-between w-100">
          <strong>{{ volume.path }}</strong>
          <span>{{ formatBytes(volume.free_bytes) }} libres sur {{ formatBytes(volume.total_bytes) }}</span>
        </div>
        <div class="progress-bar-wrap">
          <div class="progress-bar" :style="{ width: `${(volume.total_bytes - volume.free_bytes) / volume.total_bytes * 100}%` }"></div>
        </div>
      </article>
    </div>

    <div v-if="categorized.radarr.length" class="volume-group">
      <h3 class="volume-group-title">Radarr</h3>
      <article v-for="volume in categorized.radarr" :key="volume.path" class="detail-row flex-column gap-6">
        <div class="inline-row justify-between w-100">
          <strong>{{ volume.path }}</strong>
          <span>{{ formatBytes(volume.free_bytes) }} libres sur {{ formatBytes(volume.total_bytes) }}</span>
        </div>
        <div class="progress-bar-wrap">
          <div class="progress-bar" :style="{ width: `${(volume.total_bytes - volume.free_bytes) / volume.total_bytes * 100}%` }"></div>
        </div>
      </article>
    </div>

    <p v-if="!volumes.length" class="empty">Aucun disque detecte.</p>
  </section>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({ volumes: { type: Array, default: () => [] } });

const categorized = computed(() => {
  const result = { sonarr: [], radarr: [], common: [] };
  for (const vol of props.volumes) {
    const isSonarr = vol.sources.some(s => s.toLowerCase().includes('sonarr'));
    const isRadarr = vol.sources.some(s => s.toLowerCase().includes('radarr'));
    if (isSonarr && isRadarr) result.common.push(vol);
    else if (isSonarr) result.sonarr.push(vol);
    else if (isRadarr) result.radarr.push(vol);
  }
  return result;
});

function formatBytes(bytes) {
  if (!bytes) return '0 Go';
  const g = bytes / (1024 * 1024 * 1024);
  if (g > 1024) return (g / 1024).toFixed(1) + ' To';
  return g.toFixed(1) + ' Go';
}
</script>
