<template>
  <div class="settings-grid">
    <div class="settings-cards span-two">
      <SettingsCard title="Acquisitions de series" :subtitle="acquisitionSubtitle" :icon="ListRestart" :status="acquisitions.counts.blocked_imports ? 'error' : acquisitions.counts.active_batches ? 'neutral' : 'active'" :collapsible="false">
        <template #actions>
          <button class="icon-button" title="Actualiser" aria-label="Actualiser" @click.stop="loadAcquisitions"><RefreshCw/></button>
        </template>
        <div class="acquisition-counters">
          <span class="badge">{{ acquisitions.counts.active_batches }} lot(s)</span>
          <span class="badge">{{ acquisitions.counts.active_queue }} element(s) actif(s)</span>
          <span class="badge" :class="{ danger: acquisitions.counts.blocked_imports }">{{ acquisitions.counts.blocked_imports }} import(s) bloque(s)</span>
        </div>
        <article v-for="batch in acquisitions.items" :key="batch.id" class="acquisition-batch">
          <div class="acquisition-head">
            <div>
              <strong>{{ batch.title }}</strong>
              <span>{{ batchStatus(batch.status) }} · {{ sourceLabel(batch.source) }}</span>
            </div>
            <span class="badge">{{ scopeLabel(batch) }}</span>
          </div>
          <small>
            Ouvert {{ formatDate(batch.opened_at) }}
            <template v-if="batch.last_plex_change_at"> · dernier changement Plex {{ formatDate(batch.last_plex_change_at) }}</template>
          </small>
          <div v-if="batch.pending_events.length" class="acquisition-events">
            {{ batch.pending_events.length }} jalon(s) Plex en attente du recapitulatif.
          </div>
          <div v-for="row in batch.queue" :key="row.id" class="queue-observation" :class="{ blocked: row.state === 'import_blocked' }">
            <div>
              <strong>{{ episodeLabel(row) }}</strong>
              <span>{{ queueStateLabel(row.state) }} · {{ Math.round(row.progress || 0) }} %</span>
              <small v-if="row.error">{{ row.error }}</small>
            </div>
            <span v-if="row.state === 'import_blocked'" class="badge danger">Intervention Sonarr</span>
          </div>
        </article>
        <p v-if="!acquisitions.items.length" class="empty">Aucune acquisition de serie en cours.</p>
      </SettingsCard>
    </div>
  </div>
</template>
<script setup>
import { formatDateTimeShort as formatDate } from '@/utils/format';
import { computed, onMounted, ref } from 'vue';
import { ListRestart, RefreshCw } from '@lucide/vue';
import { api } from '@/api';
import SettingsCard from './SettingsCard.vue';

const acquisitions = ref({ items: [], counts: { active_batches: 0, active_queue: 0, blocked_imports: 0 } });
const acquisitionSubtitle = computed(() => acquisitions.value.counts.blocked_imports ? 'Intervention requise dans Sonarr' : acquisitions.value.counts.active_batches ? 'Telechargements et stabilisation en cours' : 'Aucun lot actif');

async function loadAcquisitions(){acquisitions.value=await api('/api/acquisition-batches')}

function batchStatus(status){return status==='stabilizing'?'Stabilisation Plex':'Activite Sonarr'}
function sourceLabel(source){return ({api:'API',rss:'Watchlist Plex',watchlist:'Watchlist Plex'})[source]||source||'Source inconnue'}
function scopeLabel(batch){return batch.expected_scope==='all_seasons'?`${batch.expected_seasons.length} saison(s) attendue(s)`:`${batch.expected_seasons.length} saison(s) surveillee(s)`}
function queueStateLabel(state){return ({queued:'En attente',downloading:'Telechargement',importing:'Import',awaiting_import:'Import en attente',import_blocked:'Import bloque'})[state]||state}
function episodeLabel(row){const season=row.season_number!=null?`S${String(row.season_number).padStart(2,'0')}`:'';const episode=row.episode_number!=null?`E${String(row.episode_number).padStart(2,'0')}`:'';return [season+episode,row.title].filter(Boolean).join(' · ')||'Element Sonarr'}

onMounted(loadAcquisitions);
</script>
<style scoped>
.acquisition-counters,.acquisition-events{display:flex;gap: var(--space-2);flex-wrap:wrap}.acquisition-batch{border-top:1px solid var(--border);padding:14px 0;display:grid;gap: var(--space-2)}.acquisition-head,.queue-observation{display:flex;justify-content:space-between;gap: var(--space-3);align-items:flex-start}.acquisition-head div,.queue-observation div{display:grid;gap: var(--space-1)}.queue-observation{padding:10px;border-radius:var(--radius-sm);background:var(--surface-2)}.queue-observation.blocked{border:1px solid var(--danger)}.badge.danger{background:color-mix(in srgb,var(--danger) 18%,transparent);color:var(--danger)}
</style>
