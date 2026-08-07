<template>
  <section v-if="state !== 'requestable'" class="request-panel" :class="`is-${state}`">
    <div class="request-panel-main">
      <div class="request-panel-icon" aria-hidden="true">
        <CheckCircle2 v-if="state === 'available'" />
        <AlertTriangle v-else-if="state === 'failed'" />
        <Download v-else-if="state === 'downloading'" />
        <Clock3 v-else-if="state === 'requested'" />
        <PlusCircle v-else />
      </div>

      <div class="request-panel-copy">
        <span class="eyebrow">{{ eyebrow }}</span>
        <h2>{{ title }}</h2>
        <p>{{ description }}</p>
        <div class="request-panel-meta">
          <span v-if="detail.year">{{ detail.year }}</span>
          <span v-if="detail.media_type === 'show' && detail.number_of_seasons">
            {{ detail.number_of_seasons }} saison{{ detail.number_of_seasons > 1 ? 's' : '' }}
          </span>
          <span v-if="detail.status">{{ detail.status }}</span>
        </div>
      </div>

      <div class="request-panel-action">
        <template v-if="state === 'failed'">
          <RouterLink v-if="detail.request_id" :to="`/media/request/${detail.request_id}`" class="secondary">Voir le détail <ChevronRight /></RouterLink>
        </template>
        <a v-else-if="state === 'available' && plexUrl" :href="plexUrl" target="_blank" rel="noopener" class="primary">
          <ExternalLink /> Ouvrir dans Plex
        </a>
        <template v-else-if="state !== 'requestable' && detail.request_id">
          <button v-if="canJoin" class="primary" :disabled="busy" @click="$emit('join')"><UserPlus /> Ajouter à mes demandes</button>
          <RouterLink :to="`/media/request/${detail.request_id}`" class="secondary">Suivre la demande <ChevronRight /></RouterLink>
        </template>
        <span v-else class="request-available-label"><CheckCircle2 /> Disponible dans Plex</span>
      </div>
    </div>

    <p v-if="detail.just_requested" class="request-inline-confirm" role="status">
      <CheckCircle2 /> Demande envoyée. Le suivi est maintenant actif.
    </p>

    <div v-if="detail.workflow_timeline?.length || state === 'requested' || state === 'downloading'" class="request-progress" aria-label="Progression de la demande">
      <span v-for="step in timelineSteps" :key="step.key" :class="['request-progress-step', step.state]">
        <Check v-if="step.state === 'done'" />
        <AlertTriangle v-else-if="step.state === 'error'" />
        <span v-else class="progress-dot"></span>
        <span>{{ step.label }}<small v-if="step.occurred_at">{{ formatStepDate(step.occurred_at) }}</small></span>
      </span>
    </div>

    <details v-if="state !== 'requestable' && detail.media_type === 'show' && hasSeasonProgress" class="request-options season-progress">
      <summary>
        <span>Disponibilité par saison</span>
        <small>{{ episodeProgressLabel }}</small>
      </summary>
      <div v-if="detail.seasons?.length" class="season-progress-list">
        <div v-for="season in detail.seasons" :key="season.season_number" class="season-progress-row">
          <span>Saison {{ season.season_number }}</span>
          <div class="season-progress-track"><span :style="{ width: `${seasonPercent(season)}%` }"></span></div>
          <strong>{{ season.episodes_available_count || 0 }}/{{ season.episodes_total_count || 0 }}</strong>
        </div>
      </div>
      <p v-else class="season-progress-empty">Le détail par saison sera disponible après la première synchronisation Sonarr.</p>
    </details>

    <details v-if="admin && detail.request_id" class="request-options admin-options">
      <summary>
        <span>Administration</span>
        <small>Options et actions techniques</small>
      </summary>
      <div class="admin-action-row">
        <button v-if="detail.request_status === 'pending_approval'" class="primary" :disabled="busy" @click="$emit('approve')"><Check /> Approuver</button>
        <button v-if="state === 'failed'" class="secondary" :disabled="busy" @click="$emit('retry')"><RotateCcw /> Relancer</button>
        <RouterLink :to="`/media/request/${detail.request_id}`" class="secondary">Administration complète <ChevronRight /></RouterLink>
      </div>
    </details>
  </section>

  <div v-if="state === 'requestable'" class="request-cta">
    <button class="primary request-submit" :disabled="busy" @click="handleRequestClick"><PlusCircle />{{ busy ? 'Envoi…' : requestLabel }}</button>
  </div>

  <RequestOptionsModal
    :open="showOptions"
    :media-title="detail.title"
    :requesters="requesters"
    :folders="folders"
    :plex-user-id="form.plex_user_id"
    :root-folder="form.root_folder"
    :busy="busy"
    :confirm-label="requestLabel"
    :media-type="detail.media_type"
    :seasons="form.seasons"
    :season-numbers="seasonNumbers"
    @update:plex-user-id="v => form.plex_user_id = v"
    @update:root-folder="v => form.root_folder = v"
    @update:seasons="v => form.seasons = v"
    @cancel="showOptions = false"
    @confirm="() => { showOptions = false; $emit('submit'); }"
  />
</template>

<script setup>
import { computed, ref } from 'vue';
import { AlertTriangle, Check, CheckCircle2, ChevronRight, Clock3, Download, ExternalLink, PlusCircle, RotateCcw, UserPlus } from '@lucide/vue';
import { formatPlexWebUrl } from '@/mediaUrl';
import RequestOptionsModal from './RequestOptionsModal.vue';

const props = defineProps({
  detail: { type: Object, required: true },
  form: { type: Object, required: true },
  requesters: { type: Array, default: () => [] },
  folders: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
  admin: { type: Boolean, default: false },
  currentUserId: { type: String, default: '' },
});
defineEmits(['submit', 'join', 'retry', 'approve']);

const showOptions = ref(false);
function handleRequestClick() {
  showOptions.value = true;
}

const seasonNumbers = computed(() => Array.from({ length: Number(props.detail?.number_of_seasons || 0) }, (_, index) => index + 1));
const isAvailable = computed(() => Boolean(props.detail.available || props.detail.in_library));
const isDownloading = computed(() => Boolean(props.detail.is_downloading) || ['queued', 'downloading', 'importing'].includes(props.detail.operational_status));
const isFailed = computed(() => props.detail.request_status === 'failed' || props.detail.operational_status === 'failed');
const state = computed(() => isAvailable.value ? 'available' : isFailed.value ? 'failed' : isDownloading.value ? 'downloading' : props.detail.requested || props.detail.request_id ? 'requested' : 'requestable');
const canJoin = computed(() => Boolean(props.currentUserId) && !(props.detail.requester_ids || []).includes(props.currentUserId));
const plexUrl = computed(() => formatPlexWebUrl(props.detail?.plex_guid));
const requestLabel = computed(() => props.detail.media_type === 'show' ? 'Demander la série' : 'Demander ce film');
const eyebrow = computed(() => ({
  available: 'Disponible',
  downloading: 'En cours',
  failed: 'Intervention nécessaire',
  requested: 'Demande enregistrée',
  requestable: 'Demande',
})[state.value]);
const title = computed(() => ({
  available: 'Ce média est dans Plex',
  downloading: 'Le téléchargement est en cours',
  failed: 'La demande a rencontré une erreur',
  requested: props.detail.operational_status_label || (props.detail.request_status === 'pending_approval' ? "En attente d'approbation" : 'La demande est prise en charge'),
  requestable: requestLabel.value,
})[state.value]);
const description = computed(() => {
  if (state.value === 'available') return 'Il est prêt à être regardé depuis votre bibliothèque Plex.';
  if (props.detail.waiting_reason) return props.detail.waiting_reason;
  if (state.value === 'failed') return 'Une intervention est nécessaire avant de reprendre le traitement.';
  if (state.value === 'downloading') return 'Sonarr ou Radarr récupère actuellement les fichiers.';
  if (state.value === 'requested') return props.detail.request_status === 'pending_approval'
    ? "Un administrateur doit encore l'approuver."
    : 'Sonarr ou Radarr recherche automatiquement une version adaptée.';
  return props.detail.media_type === 'show'
    ? 'Toutes les saisons seront demandées avec les réglages configurés.'
    : 'La recherche démarrera automatiquement avec les réglages configurés.';
});
const hasSeasonProgress = computed(() => Boolean(props.detail.seasons?.length)
  || props.detail.episodes_total_count != null
  || props.detail.episodes_available_count != null);
const episodeProgressLabel = computed(() => {
  const available = Number(props.detail.episodes_available_count || 0);
  const total = Number(props.detail.episodes_total_count || 0);
  return total ? `${available}/${total} épisodes disponibles` : 'Synchronisation en cours';
});

const currentProgressIndex = computed(() => {
  if (isDownloading.value) return 2;
  if (['sent_to_arr', 'submitted', 'awaiting_submission'].includes(props.detail.request_status)
    || ['submitted', 'awaiting_submission'].includes(props.detail.operational_status)) return 1;
  return 0;
});
const fallbackTimeline = computed(() => [
  { key: 'requested', label: 'Demandé' },
  { key: 'submitted', label: 'Pris en charge' },
  { key: 'downloading', label: 'Téléchargement' },
  { key: 'available', label: 'Dans Plex' },
].map((step, index) => ({ ...step, state: index < currentProgressIndex.value ? 'done' : index === currentProgressIndex.value ? 'current' : 'upcoming' })));
const timelineSteps = computed(() => props.detail.workflow_timeline?.length
  ? props.detail.workflow_timeline.map(step => ({
      ...step,
      state: step.state === 'completed' ? 'done' : step.state,
    }))
  : fallbackTimeline.value);

function seasonPercent(season) {
  const total = Number(season.episodes_total_count || 0);
  return total ? Math.min(100, Math.round((Number(season.episodes_available_count || 0) / total) * 100)) : 0;
}
function formatStepDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' });
}
</script>

<style scoped>
.request-panel {
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, color-mix(in srgb, var(--surface) 94%, var(--accent)), var(--surface));
  box-shadow: 0 14px 40px rgba(0, 0, 0, .16);
}
.request-panel.is-available { border-color: rgba(34, 197, 94, .42); }
.request-panel.is-downloading { border-color: rgba(14, 165, 233, .46); }
.request-panel.is-failed { border-color: rgba(239, 68, 68, .46); }
.request-panel-main {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: var(--space-4);
  align-items: center;
  padding: 20px;
}
.request-panel-icon {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  color: var(--muted);
  background: color-mix(in srgb, var(--accent) 15%, transparent);
}
.is-available .request-panel-icon { color: var(--green-text); background: rgba(34, 197, 94, .12); }
.is-downloading .request-panel-icon { color: #38bdf8; background: rgba(14, 165, 233, .12); }
.is-failed .request-panel-icon { color: var(--red-text); background: rgba(239, 68, 68, .12); }
.request-panel-icon svg { width: 25px; height: 25px; }
.request-panel-copy { min-width: 0; }
.request-panel-copy h2 { margin: 2px 0 5px; font-size: var(--fs-lg); }
.request-panel-copy p { margin: 0; color: var(--muted); line-height: 1.45; }
.request-panel-meta { display: flex; flex-wrap: wrap; gap: var(--space-2) var(--space-4); margin-top: 9px; color: var(--muted); font-size: var(--fs-sm); }
.request-panel-meta span + span { position: relative; }
.request-panel-meta span + span::before { content: '•'; position: absolute; left: -9px; }
.request-panel-action { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: var(--space-2); }
.request-panel-action :is(a, button) { display: inline-flex; align-items: center; justify-content: center; gap: var(--space-2); white-space: nowrap; text-decoration: none; }
.request-panel-action svg { width: 17px; height: 17px; }
.request-available-label { display: inline-flex; align-items: center; gap: var(--space-2); color: var(--green-text); font-weight: 700; }
.request-inline-confirm { display: flex; align-items: center; gap: var(--space-2); margin: 0; padding: 11px 20px; border-top: 1px solid rgba(34, 197, 94, .25); color: var(--green-text); background: rgba(34, 197, 94, .08); font-weight: 700; }
.request-inline-confirm svg { width: 18px; height: 18px; }
.request-progress {
  display: flex;
  overflow-x: auto;
  border-top: 1px solid var(--border);
  background: rgba(0, 0, 0, .08);
}
.request-progress-step { display: flex; flex: 1 0 130px; align-items: center; justify-content: center; gap: var(--space-2); padding: 12px 8px; color: var(--muted); font-size: var(--fs-sm); text-align: center; }
.request-progress-step svg { width: 14px; height: 14px; }
.request-progress-step > span:not(.progress-dot) { display: grid; gap: var(--space-1); }
.request-progress-step small { font-size: var(--fs-xs); font-weight: 400; opacity: .72; }
.request-progress-step.done { color: var(--green-text); }
.request-progress-step.current { color: var(--accent); font-weight: 700; }
.request-progress-step.error { color: var(--red-text); font-weight: 700; }
.progress-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.request-options { border-top: 1px solid var(--border); }
.request-options summary { display: flex; justify-content: space-between; gap: var(--space-3); padding: 13px 20px; cursor: pointer; font-weight: 700; list-style-position: inside; }
.request-options summary small { color: var(--muted); font-weight: 400; }
.admin-action-row { display: flex; flex-wrap: wrap; gap: var(--space-2); padding: 0 20px 18px; }
.admin-action-row :is(a, button) { display: inline-flex; align-items: center; gap: var(--space-2); text-decoration: none; }
.season-progress-list { display: grid; gap: var(--space-3); padding: 0 20px 18px; }
.season-progress-row { display: grid; grid-template-columns: 85px minmax(80px, 1fr) 45px; gap: var(--space-3); align-items: center; font-size: var(--fs-sm); }
.season-progress-row strong { text-align: right; }
.season-progress-track { height: 7px; overflow: hidden; border-radius: var(--radius-pill); background: var(--surface-2); }
.season-progress-track span { display: block; height: 100%; border-radius: inherit; background: var(--green); }
.season-progress-empty { margin: 0; padding: 0 20px 18px; color: var(--muted); font-size: var(--fs-sm); }
.request-cta { display: flex; justify-content: flex-start; }
.request-cta button { min-height: 44px; }
@media (max-width: 720px) {
  .request-panel-main { grid-template-columns: auto minmax(0, 1fr); padding: 16px; }
  .request-panel-action { grid-column: 1 / -1; }
  .request-panel-action :is(a, button), .request-available-label { width: 100%; }
  .request-progress-step { justify-content: flex-start; padding-left: 16px; }
  .request-cta {
    position: fixed;
    z-index: 44;
    right: max(10px, var(--safe-right));
    bottom: calc(var(--mobile-nav-h) + var(--safe-bottom) + 10px);
    left: max(10px, var(--safe-left));
    display: block;
    padding: 8px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--surface-glass);
    box-shadow: 0 12px 34px rgba(0, 0, 0, .42);
    backdrop-filter: blur(16px);
  }
  .request-cta button { width: 100%; min-height: 46px; }
}
</style>
