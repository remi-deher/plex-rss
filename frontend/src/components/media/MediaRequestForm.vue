<template>
  <section class="request-panel" :class="`is-${state}`">
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
          <button v-if="admin" class="primary" :disabled="busy" @click="$emit('retry')"><RotateCcw /> Relancer</button>
          <RouterLink v-if="detail.request_id" :to="`/media/request/${detail.request_id}`" class="secondary">Voir le détail <ChevronRight /></RouterLink>
        </template>
        <a v-else-if="state === 'available' && plexUrl" :href="plexUrl" target="_blank" rel="noopener" class="primary">
          <ExternalLink /> Ouvrir dans Plex
        </a>
        <template v-else-if="state !== 'requestable' && detail.request_id">
          <button v-if="canJoin" class="primary" :disabled="busy" @click="$emit('join')"><UserPlus /> Ajouter à mes demandes</button>
          <RouterLink :to="`/media/request/${detail.request_id}`" class="secondary">Suivre la demande <ChevronRight /></RouterLink>
        </template>
        <button v-else-if="state === 'requestable'" class="primary request-submit" :disabled="submitDisabled" @click="$emit('submit')">
          <PlusCircle />{{ busy ? 'Envoi…' : requestLabel }}
        </button>
        <span v-else class="request-available-label"><CheckCircle2 /> Disponible dans Plex</span>
      </div>
    </div>

    <div v-if="state === 'requested' || state === 'downloading'" class="request-progress" aria-label="Progression de la demande">
      <span v-for="step in progressSteps" :key="step.key" :class="['request-progress-step', step.state]">
        <Check v-if="step.state === 'done'" />
        <span v-else class="progress-dot"></span>
        {{ step.label }}
      </span>
    </div>

    <details v-if="state === 'requestable' && detail.media_type === 'show' && seasonNumbers.length" class="request-options">
      <summary>
        <span>Choisir les saisons</span>
        <small>{{ seasonSelectionLabel }}</small>
      </summary>
      <div class="season-choice-head">
        <label class="check"><input type="checkbox" :checked="allSeasonsSelected" @change="toggleAllSeasons"> Toutes les saisons</label>
      </div>
      <div class="season-choice-grid">
        <label v-for="season in seasonNumbers" :key="season" class="check">
          <input v-model="form.seasons" type="checkbox" :value="season"> Saison {{ season }}
        </label>
      </div>
    </details>

    <details v-if="state === 'requestable' && admin && (requesters.length || folders.length)" class="request-options admin-options">
      <summary>
        <span>Options administrateur</span>
        <small>Demandeur et dossier racine</small>
      </summary>
      <div class="admin-options-grid">
        <label v-if="requesters.length">Demandeur
          <select v-model="form.plex_user_id">
            <option v-for="user in requesters" :key="user.plex_user_id" :value="user.plex_user_id">{{ user.custom_name || user.display_name || user.plex_user_id }}</option>
          </select>
        </label>
        <label v-if="folders.length">Dossier racine
          <select v-model="form.root_folder">
            <option value="">Dossier par défaut</option>
            <option v-for="folder in folders" :key="folder.path || folder" :value="folder.path || folder">{{ folder.path || folder }}</option>
          </select>
        </label>
      </div>
    </details>
  </section>
</template>

<script setup>
import { computed } from 'vue';
import { AlertTriangle, Check, CheckCircle2, ChevronRight, Clock3, Download, ExternalLink, PlusCircle, RotateCcw, UserPlus } from '@lucide/vue';

const props = defineProps({
  detail: { type: Object, required: true },
  form: { type: Object, required: true },
  requesters: { type: Array, default: () => [] },
  folders: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
  admin: { type: Boolean, default: false },
  currentUserId: { type: String, default: '' },
});
defineEmits(['submit', 'join', 'retry']);

const seasonNumbers = computed(() => Array.from({ length: Number(props.detail?.number_of_seasons || 0) }, (_, index) => index + 1));
const allSeasonsSelected = computed(() => seasonNumbers.value.length > 0 && seasonNumbers.value.every(season => props.form.seasons.includes(season)));
const isAvailable = computed(() => Boolean(props.detail.available || props.detail.in_library));
const isDownloading = computed(() => Boolean(props.detail.is_downloading) || ['queued', 'downloading', 'importing'].includes(props.detail.operational_status));
const isFailed = computed(() => props.detail.request_status === 'failed' || props.detail.operational_status === 'failed');
const state = computed(() => isAvailable.value ? 'available' : isFailed.value ? 'failed' : isDownloading.value ? 'downloading' : props.detail.requested || props.detail.request_id ? 'requested' : 'requestable');
const canJoin = computed(() => Boolean(props.currentUserId) && !(props.detail.requester_ids || []).includes(props.currentUserId));
const plexUrl = computed(() => props.detail.plex_guid
  ? `https://app.plex.tv/desktop/#!/provider/tv.plex.provider.discover/details?key=${encodeURIComponent(props.detail.plex_guid)}`
  : '');
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
const submitDisabled = computed(() => props.busy || !props.form.plex_user_id || (props.detail.media_type === 'show' && !props.form.seasons.length));
const seasonSelectionLabel = computed(() => allSeasonsSelected.value
  ? 'Toutes les saisons'
  : `${props.form.seasons.length} saison${props.form.seasons.length > 1 ? 's' : ''} sélectionnée${props.form.seasons.length > 1 ? 's' : ''}`);

const currentProgressIndex = computed(() => {
  if (isDownloading.value) return 2;
  if (['sent_to_arr', 'submitted', 'awaiting_submission'].includes(props.detail.request_status)
    || ['submitted', 'awaiting_submission'].includes(props.detail.operational_status)) return 1;
  return 0;
});
const progressSteps = computed(() => [
  { key: 'requested', label: 'Demandé' },
  { key: 'submitted', label: 'Pris en charge' },
  { key: 'downloading', label: 'Téléchargement' },
  { key: 'available', label: 'Dans Plex' },
].map((step, index) => ({ ...step, state: index < currentProgressIndex.value ? 'done' : index === currentProgressIndex.value ? 'current' : 'upcoming' })));

function toggleAllSeasons(event) {
  props.form.seasons = event.target.checked ? [...seasonNumbers.value] : [];
}
</script>

<style scoped>
.request-panel {
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: linear-gradient(135deg, color-mix(in srgb, var(--surface) 94%, var(--accent)), var(--surface));
  box-shadow: 0 14px 40px rgba(0, 0, 0, .16);
}
.request-panel.is-available { border-color: rgba(34, 197, 94, .42); }
.request-panel.is-downloading { border-color: rgba(14, 165, 233, .46); }
.request-panel.is-failed { border-color: rgba(239, 68, 68, .46); }
.request-panel-main {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 16px;
  align-items: center;
  padding: 20px;
}
.request-panel-icon {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border-radius: 14px;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 15%, transparent);
}
.is-available .request-panel-icon { color: var(--green); background: rgba(34, 197, 94, .12); }
.is-downloading .request-panel-icon { color: #38bdf8; background: rgba(14, 165, 233, .12); }
.is-failed .request-panel-icon { color: var(--red); background: rgba(239, 68, 68, .12); }
.request-panel-icon svg { width: 25px; height: 25px; }
.request-panel-copy { min-width: 0; }
.request-panel-copy h2 { margin: 2px 0 5px; font-size: 1.15rem; }
.request-panel-copy p { margin: 0; color: var(--muted); line-height: 1.45; }
.request-panel-meta { display: flex; flex-wrap: wrap; gap: 6px 14px; margin-top: 9px; color: var(--muted); font-size: .76rem; }
.request-panel-meta span + span { position: relative; }
.request-panel-meta span + span::before { content: '•'; position: absolute; left: -9px; }
.request-panel-action { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 8px; }
.request-panel-action :is(a, button) { display: inline-flex; align-items: center; justify-content: center; gap: 7px; white-space: nowrap; text-decoration: none; }
.request-panel-action svg { width: 17px; height: 17px; }
.request-available-label { display: inline-flex; align-items: center; gap: 7px; color: var(--green); font-weight: 700; }
.request-progress {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  border-top: 1px solid var(--border);
  background: rgba(0, 0, 0, .08);
}
.request-progress-step { display: flex; align-items: center; justify-content: center; gap: 6px; padding: 12px 8px; color: var(--muted); font-size: .76rem; }
.request-progress-step svg { width: 14px; height: 14px; }
.request-progress-step.done { color: var(--green); }
.request-progress-step.current { color: var(--accent); font-weight: 700; }
.progress-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.request-options { border-top: 1px solid var(--border); }
.request-options summary { display: flex; justify-content: space-between; gap: 12px; padding: 13px 20px; cursor: pointer; font-weight: 700; list-style-position: inside; }
.request-options summary small { color: var(--muted); font-weight: 400; }
.season-choice-head { padding: 2px 20px 10px; }
.season-choice-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; padding: 0 20px 18px; }
.season-choice-grid .check, .season-choice-head .check { display: flex; align-items: center; gap: 7px; }
.admin-options-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; padding: 0 20px 18px; }
.admin-options-grid label { display: grid; gap: 6px; font-size: .8rem; font-weight: 600; }
@media (max-width: 720px) {
  .request-panel-main { grid-template-columns: auto minmax(0, 1fr); padding: 16px; }
  .request-panel-action { grid-column: 1 / -1; }
  .request-panel-action :is(a, button), .request-available-label { width: 100%; }
  .request-submit { min-height: 46px; }
  .request-progress { grid-template-columns: repeat(2, 1fr); }
  .request-progress-step { justify-content: flex-start; padding-left: 16px; }
  .admin-options-grid { grid-template-columns: 1fr; }
}
</style>
