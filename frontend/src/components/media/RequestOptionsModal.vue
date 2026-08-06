<template>
  <ModalShell
    v-if="open"
    :open="open"
    title="Options de la demande"
    :subtitle="mediaTitle"
    panel-class="request-options-modal"
    :busy="busy"
    @close="$emit('cancel')"
  >
    <p class="request-options-intro">
      {{ mediaType === 'show' ? 'Choisissez les saisons à ajouter avant de confirmer la demande.' : 'Confirmez l’ajout du film. La recherche démarrera automatiquement.' }}
    </p>
    <div class="request-options-grid">
      <label v-if="requesters.length">Demandeur
        <select :value="plexUserId" @change="$emit('update:plexUserId', $event.target.value)">
          <option v-for="user in requesters" :key="user.plex_user_id" :value="user.plex_user_id">{{ user.custom_name || user.display_name || user.plex_user_id }}</option>
        </select>
      </label>
      <label v-if="folders.length">Dossier racine
        <select :value="rootFolder" @change="$emit('update:rootFolder', $event.target.value)">
          <option value="">Dossier par défaut</option>
          <option v-for="folder in folders" :key="folder.path || folder" :value="folder.path || folder">{{ folder.path || folder }}</option>
        </select>
      </label>
    </div>
    <fieldset v-if="mediaType === 'show' && selectableSeasons.length" class="season-options">
      <legend>Saisons à demander</legend>
      <label class="season-toggle-all">
        <input type="checkbox" :checked="allSeasonsSelected" @change="toggleAllSeasons">
        Toutes les saisons
      </label>
      <div class="season-options-grid">
        <label v-for="season in selectableSeasons" :key="season">
          <input
            type="checkbox"
            :value="season"
            :checked="seasons.includes(season)"
            @change="toggleSeason(season, $event.target.checked)"
          >
          Saison {{ season }}
        </label>
      </div>
      <small>Les épisodes spéciaux (saison 0) ne sont pas sélectionnés par défaut.</small>
    </fieldset>
    <div class="form-actions">
      <button class="secondary" :disabled="busy" @click="$emit('cancel')">Annuler</button>
      <button class="primary" :disabled="busy || !plexUserId || (mediaType === 'show' && !seasons.length)" @click="$emit('confirm')">
        {{ busy ? 'Envoi…' : confirmLabel }}
      </button>
    </div>
  </ModalShell>
</template>

<script setup>
import { computed } from 'vue';
import ModalShell from '@/components/ui/ModalShell.vue';

const props = defineProps({
  open: { type: Boolean, default: false },
  mediaTitle: { type: String, default: '' },
  requesters: { type: Array, default: () => [] },
  folders: { type: Array, default: () => [] },
  plexUserId: { type: String, default: '' },
  rootFolder: { type: String, default: '' },
  busy: { type: Boolean, default: false },
  confirmLabel: { type: String, default: 'Envoyer la demande' },
  mediaType: { type: String, default: '' },
  seasons: { type: Array, default: () => [] },
  seasonNumbers: { type: Array, default: () => [] },
});
const emit = defineEmits(['update:plexUserId', 'update:rootFolder', 'update:seasons', 'confirm', 'cancel']);

const selectableSeasons = computed(() => props.seasonNumbers
  .map(Number)
  .filter(season => Number.isInteger(season) && season > 0));
const allSeasonsSelected = computed(() => selectableSeasons.value.length > 0
  && selectableSeasons.value.every(season => props.seasons.includes(season)));

function toggleAllSeasons(event) {
  emit('update:seasons', event.target.checked ? [...selectableSeasons.value] : []);
}
function toggleSeason(season, checked) {
  const selected = new Set(props.seasons);
  if (checked) selected.add(season); else selected.delete(season);
  emit('update:seasons', [...selected].filter(value => value > 0).sort((a, b) => a - b));
}
</script>

<style scoped>
:deep(.request-options-modal) { width: min(480px, calc(100% - 24px)); }
.request-options-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); }
.request-options-intro { margin: 0 0 var(--space-4); color: var(--muted); line-height: 1.5; }
.request-options-grid label { display: grid; gap: var(--space-2); font-size: var(--fs-sm); font-weight: 600; }
.season-options { display: grid; gap: var(--space-3); margin: var(--space-4) 0 0; padding: var(--space-4); border: 1px solid var(--border); border-radius: var(--radius-md); }
.season-options legend { padding: 0 var(--space-2); font-size: var(--fs-sm); font-weight: 700; }
.season-toggle-all, .season-options-grid label { display: flex; align-items: center; gap: var(--space-2); }
.season-options-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: var(--space-2); }
.season-options small { color: var(--muted); line-height: 1.4; }
.season-options input { accent-color: var(--accent); }
.form-actions { justify-content: flex-end; margin-top: 1.5rem; }
@media (max-width: 640px) {
  .request-options-grid { grid-template-columns: 1fr; }
}
</style>
