<template>
  <div class="vf-summary" style="margin-top: 1.5rem;">
    <div v-if="!vfDetail || vfDetail.media_type !== 'show'" class="panel-head" style="margin-bottom: 0.5rem;">
      <div class="actions">
        <button
          class="secondary"
          :disabled="busy || !available"
          :title="available ? '' : 'Pas encore disponible dans Plex — reessayer une fois le media indexe'"
          @click="$emit('scan')"
        ><RefreshCw />Actualiser</button>
      </div>
    </div>

    <div v-if="vfDetail" style="margin-top: 0.5rem;">
      <div v-if="vfDetail.media_type === 'show'">
        <div class="actions" style="justify-content: flex-end; margin-bottom: 0.5rem;">
          <button
            class="icon-button"
            :disabled="busy || !available"
            :title="available ? 'Actualiser' : 'Pas encore disponible dans Plex — reessayer une fois le media indexe'"
            @click="$emit('scan')"
          ><RefreshCw/></button>
        </div>
        <details v-for="season in vfDetail.seasons || []" :key="season.season_number" class="detail-row" style="margin-bottom: 0.5rem; display: block; border: 1px solid var(--border-color); padding: 0.5rem; border-radius: 6px;">
          <summary style="cursor: pointer; display: flex; justify-content: space-between; align-items: center; list-style: none;">
            <strong>Saison {{ season.season_number }}{{ season.name && !/^(saison|season)\s*\d+$/i.test(season.name) ? ` — ${season.name}` : '' }}</strong>
            <div class="inline-row compact" style="gap: 4px;">
              <span class="badge available" v-if="season.counts.vf">VF: {{ season.counts.vf }}</span>
              <span class="badge" v-if="season.counts.vo">VO: {{ season.counts.vo }}</span>
              <span class="badge" v-if="season.counts.vf_secondary">VF(sec): {{ season.counts.vf_secondary }}</span>
              <span class="badge danger" v-if="season.counts.absent">Absent: {{ season.counts.absent }}</span>
              <button class="icon-button" @click.prevent="$emit('correction', 'season', season.season_number, null)" title="Corriger Saison"><MessageSquareWarning size="16" /></button>
            </div>
          </summary>
          <div style="padding-top: 0.5rem; padding-left: 0.5rem; border-left: 2px solid var(--border-color); margin-top: 0.5rem;">
            <div v-for="ep in season.episodes" :key="ep.episode" class="inline-row compact" style="margin-bottom: 6px; align-items: center;">
              <span style="min-width: 30px; font-weight: 500;">{{ ep.episode }}.</span>
              <span style="flex: 1; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">{{ ep.title || `Episode ${ep.episode}` }}</span>
              <button
                class="badge"
                :class="{'available': ep.status === 'vf' || ep.status === 'vf_secondary', 'danger': ep.status === 'absent', 'pending': ep.status === 'unknown'}"
                @click="ep.status !== 'unknown' && $emit('correction', 'episode', season.season_number, ep.episode)"
                style="cursor: pointer;"
                :title="ep.status === 'unknown' ? 'Chargement...' : 'Signaler une correction'"
              >
                {{ ep.status === 'unknown' ? '…' : ep.status.toUpperCase() }}
              </button>
            </div>
          </div>
        </details>
        <p v-if="!vfDetail.seasons?.length" class="empty">Aucun detail de saison disponible.</p>
        <p v-if="availabilityError" class="notice error-text">Disponibilite (Sonarr) indisponible pour l'instant.</p>
        <p v-if="vfStatusError" class="notice error-text">Statut VF/VO indisponible pour l'instant.</p>
      </div>
      <div v-else>
        <details class="season-details" style="margin-bottom: 0.5rem;" v-if="vfDetail.tracks?.length">
          <summary style="cursor: pointer; padding: 0.5rem; background: var(--surface-hover); border-radius: 8px; font-weight: 500; display: flex; justify-content: space-between; align-items: center;">
            <span>Audio ({{ vfDetail.tracks.length }})</span>
            <ChevronDown size="16" />
          </summary>
          <div style="padding-top: 0.5rem; padding-left: 0.5rem; border-left: 2px solid var(--border-color); margin-top: 0.5rem;">
            <article v-for="(track, index) in vfDetail.tracks" :key="'audio-'+index" class="detail-row" style="margin-bottom: 6px;">
              <div>
                <strong>{{ track.lang ? track.lang.toUpperCase() : 'Inconnu' }} <span v-if="track.is_default" style="font-weight: normal; font-size: 0.85em; opacity: 0.8;">(Par défaut)</span></strong>
                <span>{{ track.label || 'Audio' }}</span>
              </div>
              <span class="badge" :class="track.is_fr ? 'available' : ''">{{ track.lang ? track.lang.toUpperCase() : '??' }}</span>
            </article>
          </div>
        </details>
        <p v-if="!vfDetail.tracks?.length" class="empty" style="margin-bottom: 0.5rem;">Aucune piste audio detectee.</p>

        <details class="season-details" v-if="vfDetail.subtitles?.length">
          <summary style="cursor: pointer; padding: 0.5rem; background: var(--surface-hover); border-radius: 8px; font-weight: 500; display: flex; justify-content: space-between; align-items: center;">
            <span>Sous-titres ({{ vfDetail.subtitles.length }})</span>
            <ChevronDown size="16" />
          </summary>
          <div style="padding-top: 0.5rem; padding-left: 0.5rem; border-left: 2px solid var(--border-color); margin-top: 0.5rem;">
            <article v-for="(sub, index) in vfDetail.subtitles" :key="'sub-'+index" class="detail-row" style="margin-bottom: 6px;">
              <div>
                <strong>{{ sub.lang ? sub.lang.toUpperCase() : 'Inconnu' }} <span v-if="sub.is_default" style="font-weight: normal; font-size: 0.85em; opacity: 0.8;">(Par défaut)</span></strong>
                <span>{{ sub.label || 'Sous-titre' }}</span>
              </div>
              <span class="badge">{{ sub.lang ? sub.lang.toUpperCase() : '??' }}</span>
            </article>
          </div>
        </details>
      </div>
    </div>
    <p v-else-if="envelopeError" class="notice error-text">Échec du chargement des saisons/épisodes.</p>
    <p v-else class="empty">Chargement de l'analyse VF...</p>
  </div>
</template>

<script setup>
import { RefreshCw, MessageSquareWarning, ChevronDown } from "@lucide/vue";

defineProps({
  vfDetail: { type: Object, default: null },
  busy: { type: Boolean, default: false },
  available: { type: Boolean, default: true },
  envelopeError: { type: Boolean, default: false },
  availabilityError: { type: Boolean, default: false },
  vfStatusError: { type: Boolean, default: false },
});

defineEmits(['scan', 'correction']);
</script>
