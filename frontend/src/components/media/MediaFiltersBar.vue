<template>
  <div class="filters-panel">
    <!-- Ligne de recherche contenant le bouton Filtres et les boutons Grille / Liste -->
    <div class="search-input-container">
      <input
        :value="query"
        class="search-input"
        type="search"
        placeholder="Rechercher un média..."
        @input="$emit('update:query', $event.target.value); $emit('search')"
      />

      <!-- Bouton d'ouverture de la Modale de Filtres -->
      <button
        class="filter-modal-trigger"
        type="button"
        title="Ouvrir les filtres"
        @click="openFilterModal"
      >
        <SlidersHorizontal />
        <span>Filtres</span>
        <strong v-if="activeFilterCount" class="filter-badge">{{ activeFilterCount }}</strong>
      </button>

      <!-- Toggle Mode d'affichage (Grille / Liste) -->
      <div class="view-toggle-segmented" role="tablist" aria-label="Mode d'affichage">
        <button :class="{ active: view === 'grid' }" title="Grille" type="button" @click="$emit('update:view', 'grid')">
          <Grid2X2 />
        </button>
        <button :class="{ active: view === 'list' }" title="Liste" type="button" @click="$emit('update:view', 'list')">
          <List />
        </button>
      </div>
    </div>

    <!-- Subnavbar de type de média (Tout / Séries / Films / Musiques) -->
    <div class="subnav-row">
      <div class="segmented type-segmented" role="tablist" aria-label="Type de média">
        <button :class="{ active: !typeFilters.length }" title="Tout" type="button" @click="$emit('update:typeFilters', [])">
          <Layers /><span>Tout</span>
        </button>
        <button :class="{ active: typeFilters.includes('show') }" title="Séries" type="button" @click="$emit('update:typeFilters', ['show'])">
          <Tv /><span>Séries</span>
        </button>
        <button :class="{ active: typeFilters.includes('movie') }" title="Films" type="button" @click="$emit('update:typeFilters', ['movie'])">
          <Film /><span>Films</span>
        </button>
        <button :class="{ active: isMusicOnly }" title="Musiques" type="button" @click="$emit('update:typeFilters', ['artist', 'album'])">
          <Music2 /><span>Musiques</span>
        </button>
      </div>

      <!-- Sous-vue Musique : Artistes vs Albums -->
      <div v-if="isMusicOnly" class="segmented music-sub-segmented">
        <button :class="{ active: isAllMusicSelected }" type="button" @click="$emit('update:typeFilters', ['artist', 'album'])">
          Toute la musique
        </button>
        <button :class="{ active: isArtistOnlySelected }" type="button" @click="$emit('update:typeFilters', ['artist'])">
          Artistes
        </button>
        <button :class="{ active: isAlbumOnlySelected }" type="button" @click="$emit('update:typeFilters', ['album'])">
          Albums
        </button>
      </div>
    </div>

    <!-- Modale de gestion des filtres -->
    <ModalShell
      v-if="isModalOpen"
      title="Filtres de recherche"
      subtitle="Sélectionnez vos critères puis cliquez sur Appliquer"
      @close="closeFilterModal"
    >
      <!-- Formulaire Modale pour la Musique -->
      <div v-if="isMusicOnly" class="filter-modal-form">
        <div class="form-group">
          <label class="form-label" for="filter-music-sort">Ordre d'affichage</label>
          <select id="filter-music-sort" class="form-select" v-model="draftSort">
            <option value="">Par défaut (Ajouts récents)</option>
            <option value="title_asc">Nom d'artiste / Titre (A-Z)</option>
            <option value="title_desc">Nom d'artiste / Titre (Z-A)</option>
            <option value="year_desc">Année de sortie (Récent -> Ancien)</option>
          </select>
        </div>

        <div class="form-group">
          <label class="form-label" for="filter-music-decade">Époque / Décennie</label>
          <select id="filter-music-decade" class="form-select" v-model="draftDecade">
            <option value="">Toutes les époques</option>
            <option value="2020s">2020 et plus</option>
            <option value="2010s">Années 2010</option>
            <option value="2000s">Années 2000</option>
            <option value="90s">Années 90</option>
            <option value="80s">Années 80</option>
            <option value="70s">Années 70 et avant</option>
          </select>
        </div>
      </div>

      <!-- Formulaire Modale standard (Films / Séries / Tout) -->
      <div v-else class="filter-modal-form">
        <!-- Statut -->
        <div class="form-group">
          <label class="form-label" for="filter-status-select">Statut</label>
          <select id="filter-status-select" class="form-select" :value="draftStatusSingle" @change="onDraftStatusChange">
            <option value="">Tous les statuts</option>
            <option value="in_progress">En cours</option>
            <option value="library">Dans Plex</option>
            <option value="orphan">Suivi Sonarr/Radarr</option>
            <option value="pending_approval">À approuver</option>
            <option value="pending">En attente</option>
            <option value="sent_to_arr">Transmise</option>
            <option value="partially_available">Partiellement disponible</option>
            <option value="failed">Échec</option>
            <option value="rejected">Refusée</option>
          </select>
        </div>

        <!-- Audio -->
        <div class="form-group">
          <label class="form-label" for="filter-audio-select">Piste Audio</label>
          <select id="filter-audio-select" class="form-select" v-model="draftVf">
            <option value="">Toutes les langues</option>
            <option value="vf">VF uniquement</option>
            <option value="vo">VO uniquement</option>
            <option value="unchecked">Non analysée</option>
          </select>
        </div>

        <!-- Source -->
        <div v-if="sources.length" class="form-group">
          <label class="form-label" for="filter-source-select">Source</label>
          <select id="filter-source-select" class="form-select" :value="draftSourceFilters[0] || ''" @change="onDraftSourceChange">
            <option value="">Toutes les sources</option>
            <option v-for="s in sources" :key="s" :value="s">{{ s }}</option>
          </select>
        </div>

        <!-- Demandeur -->
        <div v-if="requesters.length > 1" class="form-group">
          <label class="form-label" for="filter-requester-select">Demandeur</label>
          <select id="filter-requester-select" class="form-select" :value="draftRequesterFilters[0] || ''" @change="onDraftRequesterChange">
            <option value="">Tous les demandeurs</option>
            <option v-for="r in requesters" :key="r.id" :value="r.id">{{ r.label }}</option>
          </select>
        </div>
      </div>

      <template #actions>
        <button class="text-button reset-btn" type="button" @click="resetDraftFilters">
          Réinitialiser
        </button>
        <button class="secondary" type="button" @click="closeFilterModal">
          Annuler
        </button>
        <button class="primary" type="button" @click="applyFilters">
          Appliquer
        </button>
      </template>
    </ModalShell>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue';
import { Film, Grid2X2, Layers, List, Music2, SlidersHorizontal, Tv } from '@lucide/vue';
import ModalShell from '@/components/ui/ModalShell.vue';

const props = defineProps({
  query: { type: String, default: '' },
  view: { type: String, default: 'grid' },
  statusFilters: { type: Array, default: () => [] },
  typeFilters: { type: Array, default: () => [] },
  vf: { type: String, default: '' },
  sourceFilters: { type: Array, default: () => [] },
  requesterFilters: { type: Array, default: () => [] },
  decade: { type: String, default: '' },
  sort: { type: String, default: '' },
  sources: { type: Array, default: () => [] },
  requesters: { type: Array, default: () => [] },
});
const emit = defineEmits([
  'update:query', 'update:view', 'update:statusFilters', 'update:typeFilters', 'update:vf',
  'update:sourceFilters', 'update:requesterFilters', 'update:decade', 'update:sort', 'search',
]);

const isMusicOnly = computed(() => props.typeFilters.some(t => t === 'artist' || t === 'album'));

const isAllMusicSelected = computed(() => props.typeFilters.includes('artist') && props.typeFilters.includes('album'));
const isArtistOnlySelected = computed(() => props.typeFilters.length === 1 && props.typeFilters.includes('artist'));
const isAlbumOnlySelected = computed(() => props.typeFilters.length === 1 && props.typeFilters.includes('album'));

const isModalOpen = ref(false);
const draftStatusFilters = ref([]);
const draftVf = ref('');
const draftSourceFilters = ref([]);
const draftRequesterFilters = ref([]);
const draftDecade = ref('');
const draftSort = ref('');

const IN_PROGRESS_STATUSES = ['pending_approval', 'pending', 'sent_to_arr', 'partially_available'];

function openFilterModal() {
  draftStatusFilters.value = [...props.statusFilters];
  draftVf.value = props.vf;
  draftSourceFilters.value = [...props.sourceFilters];
  draftRequesterFilters.value = [...props.requesterFilters];
  draftDecade.value = props.decade;
  draftSort.value = props.sort;
  isModalOpen.value = true;
}

function closeFilterModal() {
  isModalOpen.value = false;
}

const draftStatusSingle = computed(() => {
  const current = [...draftStatusFilters.value].sort();
  const inProgressSorted = [...IN_PROGRESS_STATUSES].sort();
  const isInProgress = current.length === inProgressSorted.length && current.every((v, i) => v === inProgressSorted[i]);
  if (isInProgress) return 'in_progress';
  if (!draftStatusFilters.value.length) return '';
  return draftStatusFilters.value[0] || '';
});

function onDraftStatusChange(e) {
  const val = e.target.value;
  if (!val) draftStatusFilters.value = [];
  else if (val === 'in_progress') draftStatusFilters.value = [...IN_PROGRESS_STATUSES];
  else draftStatusFilters.value = [val];
}

function onDraftSourceChange(e) {
  const val = e.target.value;
  draftSourceFilters.value = val ? [val] : [];
}

function onDraftRequesterChange(e) {
  const val = e.target.value;
  draftRequesterFilters.value = val ? [val] : [];
}

function resetDraftFilters() {
  draftStatusFilters.value = [];
  draftVf.value = '';
  draftSourceFilters.value = [];
  draftRequesterFilters.value = [];
  draftDecade.value = '';
  draftSort.value = '';
}

function applyFilters() {
  emit('update:statusFilters', [...draftStatusFilters.value]);
  emit('update:vf', draftVf.value);
  emit('update:sourceFilters', [...draftSourceFilters.value]);
  emit('update:requesterFilters', [...draftRequesterFilters.value]);
  emit('update:decade', draftDecade.value);
  emit('update:sort', draftSort.value);
  closeFilterModal();
}

const activeFilterCount = computed(() => {
  if (isMusicOnly.value) {
    return (props.decade ? 1 : 0) + (props.sort ? 1 : 0);
  }
  return props.statusFilters.length + (props.vf ? 1 : 0)
    + props.sourceFilters.length + props.requesterFilters.length;
});
</script>

<style scoped>
.filters-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.search-input-container {
  display: flex;
  align-items: center;
  position: relative;
  width: 100%;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 3px 4px 3px 12px;
  transition: border-color 0.2s ease;
}

.search-input-container:focus-within {
  border-color: var(--accent);
}

.search-input {
  flex: 1;
  min-width: 0;
  height: 38px;
  border: 0;
  background: transparent;
  color: var(--text);
  font-size: var(--fs-sm);
  outline: none;
}

.filter-modal-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 10px;
  margin-right: 4px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.05);
  color: #ffffff;
  font-size: var(--fs-xs);
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.filter-modal-trigger:hover {
  background: rgba(255, 255, 255, 0.1);
}

.filter-modal-trigger svg {
  width: 14px;
  height: 14px;
}

.filter-badge {
  display: inline-grid;
  place-items: center;
  min-width: 18px;
  height: 18px;
  padding: 0 4px;
  border-radius: var(--radius-pill);
  background: var(--accent);
  color: #17130a;
  font-size: 11px;
  font-weight: 700;
}

.view-toggle-segmented {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: var(--radius-sm);
}

.view-toggle-segmented button {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: var(--radius-xs, 4px);
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  transition: all 0.15s ease;
}

.view-toggle-segmented button svg {
  width: 16px;
  height: 16px;
}

.view-toggle-segmented button:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.05);
}

.view-toggle-segmented button.active {
  color: #ffffff;
  background: var(--accent);
}

.subnav-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.type-segmented,
.music-sub-segmented {
  max-width: 100%;
  overflow-x: auto;
  scrollbar-width: none; /* Firefox */
}

.type-segmented::-webkit-scrollbar,
.music-sub-segmented::-webkit-scrollbar {
  display: none; /* Chrome/Safari */
}

.type-segmented button,
.music-sub-segmented button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  font-size: var(--fs-sm);
  font-weight: 600;
  color: #ffffff !important;
  white-space: nowrap;
}

.type-segmented button svg,
.music-sub-segmented button svg,
.type-segmented button span,
.music-sub-segmented button span {
  color: #ffffff !important;
}

.type-segmented button:hover,
.type-segmented button:focus,
.type-segmented button:active,
.type-segmented button.active,
.music-sub-segmented button:hover,
.music-sub-segmented button:focus,
.music-sub-segmented button:active,
.music-sub-segmented button.active {
  color: #ffffff !important;
}

.type-segmented button.active,
.music-sub-segmented button.active {
  background: var(--accent);
}

.filter-modal-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4, 16px);
  padding: var(--space-3, 12px) 0;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-1, 6px);
}

.form-label {
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--muted);
}

.form-select {
  height: 38px;
  padding: 0 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: #ffffff;
  font-size: var(--fs-sm);
  outline: none;
}

.form-select:focus {
  border-color: var(--accent);
}

.reset-btn {
  margin-right: auto;
  color: var(--muted);
  font-size: var(--fs-xs);
}

.reset-btn:hover {
  color: #ffffff;
}

/* ===== Responsive Mobile Adjustments ===== */
@media (max-width: 640px) {
  .filters-panel {
    gap: 8px;
  }

  .search-input-container {
    padding: 2px 4px 2px 8px;
  }

  .search-input {
    height: 36px;
    font-size: var(--fs-xs);
  }

  .filter-modal-trigger {
    height: 30px;
    padding: 0 8px;
    font-size: 11px;
    gap: 4px;
  }

  .type-segmented button,
  .music-sub-segmented button {
    min-height: 32px;
    padding: 0 10px;
    font-size: var(--fs-xs);
    gap: 4px;
  }

  .type-segmented button svg,
  .music-sub-segmented button svg {
    width: 12px;
    height: 12px;
  }
}

@media (max-width: 440px) {
  .filter-modal-trigger span {
    display: none;
  }

  .type-segmented button span,
  .music-sub-segmented button span {
    font-size: 11px;
  }
}
</style>
