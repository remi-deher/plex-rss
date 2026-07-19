<template>
  <section class="panel span-two">
    <div class="panel-head">
      <h2>Etat des scans</h2>
      <div class="actions">
        <button class="secondary" :disabled="vffScan.status==='running'" @click="$emit('scan-vff')">Scan VF</button>
        <button class="secondary" :disabled="plexSync.status==='running'" @click="$emit('sync-plex')">Sync Plex</button>
      </div>
    </div>

    <div class="detail-row flex-column gap-6" style="margin-bottom:8px">
      <div class="inline-row justify-between w-100">
        <strong>Analyse VF</strong>
        <span class="badge" :class="vffScan.status==='running'?'pending':vffScan.status==='failed'?'failed':'available'">
          {{ vffScan.status==='running'?'En cours':vffScan.status==='failed'?'Erreur':'Inactif' }}
        </span>
      </div>
      <div v-if="vffScan.status==='running'" class="progress-bar-wrap">
        <div class="progress-bar animated" :style="{width: vffScan.total_items>0 ? `${Math.round(vffScan.items_scanned/vffScan.total_items*100)}%` : '5%'}"></div>
      </div>
      <span v-if="vffScan.status==='running'" style="font-size:12px;opacity:.6">
        {{ vffScan.items_scanned }} / {{ vffScan.total_items || '?' }} items
      </span>
      <span v-else-if="vffScan.finished_at" style="font-size:12px;opacity:.6">Termine le {{ formatDate(vffScan.finished_at) }}</span>
    </div>

    <div class="detail-row flex-column gap-6">
      <div class="inline-row justify-between w-100">
        <strong>Synchronisation Plex</strong>
        <span class="badge" :class="plexSync.status==='running'?'pending':plexSync.status==='failed'?'failed':'available'">
          {{ plexSync.status==='running'?'En cours':plexSync.status==='failed'?'Erreur':'Inactif' }}
        </span>
      </div>
      <div v-if="plexSync.status==='running'" class="progress-bar-wrap">
        <div class="progress-bar animated" :style="{width: plexSync.total_items>0 ? `${Math.round(plexSync.items_synced/plexSync.total_items*100)}%` : '5%'}"></div>
      </div>
      <span v-if="plexSync.status==='running'" style="font-size:12px;opacity:.6">
        {{ plexSync.items_synced }} / {{ plexSync.total_items || '?' }} items
      </span>
      <span v-else-if="plexSync.finished_at" style="font-size:12px;opacity:.6">Termine le {{ formatDate(plexSync.finished_at) }}</span>
    </div>

    <div v-if="vffCounts.vf_available!=null" class="inline-row gap-10" style="margin-top:8px;flex-wrap:wrap">
      <span class="badge available">VF : {{ vffCounts.vf_available }}</span>
      <span class="badge pending">VO en attente : {{ vffCounts.vo_pending }}</span>
      <span class="badge">Non analysé : {{ vffCounts.unchecked }}</span>
    </div>
  </section>
</template>

<script setup>
defineProps({
  vffScan: { type: Object, default: () => ({ status: 'idle' }) },
  plexSync: { type: Object, default: () => ({ status: 'idle' }) },
  vffCounts: { type: Object, default: () => ({}) },
});
defineEmits(['scan-vff', 'sync-plex']);

function formatDate(v) {
  return v ? new Intl.DateTimeFormat('fr-FR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(v)) : '-';
}
</script>
