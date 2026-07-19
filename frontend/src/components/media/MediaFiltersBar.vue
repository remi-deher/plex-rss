<template>
  <div class="filters-panel">
    <div class="filter-row">
      <input :value="query" class="search" type="search" placeholder="Rechercher" @input="$emit('update:query',$event.target.value);$emit('search')">
      <div class="segmented">
        <button :class="{active:view==='grid'}" title="Grille" @click="$emit('update:view','grid')"><Grid2X2/></button>
        <button :class="{active:view==='list'}" title="Liste" @click="$emit('update:view','list')"><List/></button>
      </div>
      <button class="compact-filter-toggle secondary" type="button" :aria-expanded="expanded" @click="toggleExpanded">
        <SlidersHorizontal/>
        <span>{{ expanded ? 'Replier' : 'Filtres' }}</span>
        <strong v-if="activeFilterCount">{{ activeFilterCount }}</strong>
        <ChevronUp v-if="expanded"/><ChevronDown v-else/>
      </button>
    </div>

    <div v-show="expanded" class="filter-pills-scroll">
      <span class="filter-label">Type:</span>
      <button class="filter-pill" :class="{active:!typeFilters.length}" @click="$emit('update:typeFilters',[])">Tout</button>
      <button class="filter-pill" :class="{active:typeFilters.includes('movie')}" @click="$emit('update:typeFilters',['movie'])">Films</button>
      <button class="filter-pill" :class="{active:typeFilters.includes('show')}" @click="$emit('update:typeFilters',['show'])">Séries</button>

      <div class="divider"></div>
      <span class="filter-label">Statut:</span>
      <button class="filter-pill" :class="{active:isInProgressFilter}" @click="$emit('update:statusFilters',IN_PROGRESS_STATUSES)">En cours</button>
      <button class="filter-pill" :class="{active:!statusFilters.length}" @click="$emit('update:statusFilters',[])">Tout</button>
      <div class="multi-select" :class="{open:openMenu==='status'}">
        <button class="filter-pill dropdown-toggle" @click="toggle('status')">
          {{ statusFilters.length && !isInProgressFilter ? statusFilters.map(statusLabel).join(', ') : 'Statuts precis' }}
          <ChevronDown/>
        </button>
        <div v-if="openMenu==='status'" class="multi-select-menu" @click.stop>
          <label v-for="value in ALL_STATUSES" :key="value" class="check">
            <input type="checkbox" :value="value" :checked="statusFilters.includes(value)" @change="toggleValue('update:statusFilters',statusFilters,value)"> {{ statusLabel(value) }}
          </label>
          <button v-if="statusFilters.length" class="text-button clear-selection" @click="$emit('update:statusFilters',[])">Effacer</button>
        </div>
      </div>

      <div class="divider"></div>
      <span class="filter-label">Audio:</span>
      <button class="filter-pill" :class="{active:vf===''}" @click="$emit('update:vf','')">Toutes</button>
      <button class="filter-pill" :class="{active:vf==='vf'}" @click="$emit('update:vf','vf')">VF</button>
      <button class="filter-pill" :class="{active:vf==='vo'}" @click="$emit('update:vf','vo')">VO</button>
      <button class="filter-pill" :class="{active:vf==='unchecked'}" @click="$emit('update:vf','unchecked')">Non analysée</button>

      <template v-if="sources.length">
        <div class="divider"></div>
        <span class="filter-label">Source:</span>
        <div class="multi-select" :class="{open:openMenu==='source'}">
          <button class="filter-pill dropdown-toggle" @click="toggle('source')">
            {{ sourceFilters.length ? sourceFilters.join(', ') : 'Toutes les sources' }}
            <ChevronDown/>
          </button>
          <div v-if="openMenu==='source'" class="multi-select-menu" @click.stop>
            <label v-for="value in sources" :key="value" class="check">
              <input type="checkbox" :value="value" :checked="sourceFilters.includes(value)" @change="toggleValue('update:sourceFilters',sourceFilters,value)"> {{ value }}
            </label>
            <button v-if="sourceFilters.length" class="text-button clear-selection" @click="$emit('update:sourceFilters',[])">Effacer</button>
          </div>
        </div>
      </template>

      <template v-if="requesters.length > 1">
        <div class="divider"></div>
        <span class="filter-label">Demandeur:</span>
        <div class="multi-select" :class="{open:openMenu==='requester'}">
          <button class="filter-pill dropdown-toggle" @click="toggle('requester')">
            {{ requesterFilters.length ? requesterLabels : 'Tous les demandeurs' }}
            <ChevronDown/>
          </button>
          <div v-if="openMenu==='requester'" class="multi-select-menu" @click.stop>
            <label v-for="r in requesters" :key="r.id" class="check">
              <input type="checkbox" :value="r.id" :checked="requesterFilters.includes(r.id)" @change="toggleValue('update:requesterFilters',requesterFilters,r.id)"> {{ r.label }}
            </label>
            <button v-if="requesterFilters.length" class="text-button clear-selection" @click="$emit('update:requesterFilters',[])">Effacer</button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { ChevronDown, ChevronUp, Grid2X2, List, SlidersHorizontal } from '@lucide/vue';
import { STATUSES, statusLabel } from './mediaListHelpers';

const props = defineProps({
  query: { type: String, default: '' },
  view: { type: String, default: 'grid' },
  statusFilters: { type: Array, default: () => [] },
  typeFilters: { type: Array, default: () => [] },
  vf: { type: String, default: '' },
  sourceFilters: { type: Array, default: () => [] },
  requesterFilters: { type: Array, default: () => [] },
  sources: { type: Array, default: () => [] },
  requesters: { type: Array, default: () => [] },
});
const emit = defineEmits([
  'update:query', 'update:view', 'update:statusFilters', 'update:typeFilters', 'update:vf',
  'update:sourceFilters', 'update:requesterFilters', 'search',
]);

// 'available' n'est plus selectionnable ici : une demande "disponible" est desormais
// classee sous 'library' (voir LibraryView.vue matchesStatusFilter) meme sans
// LibraryItem -- la garder ici l'aurait rendue selectionnable mais toujours vide.
const ALL_STATUSES = ['library', ...STATUSES.filter(s => s !== 'available'), 'orphan'];
const IN_PROGRESS_STATUSES = ['pending_approval', 'pending', 'sent_to_arr', 'partially_available'];
const isInProgressFilter = computed(() => {
  const current = [...props.statusFilters].sort();
  return current.length === IN_PROGRESS_STATUSES.length
    && current.every((v, i) => v === [...IN_PROGRESS_STATUSES].sort()[i]);
});
const activeFilterCount = computed(() =>
  props.statusFilters.length + props.typeFilters.length + (props.vf ? 1 : 0)
  + props.sourceFilters.length + props.requesterFilters.length
);

const openMenu = ref(null);
const expanded = ref(true);
function toggle(name) { openMenu.value = openMenu.value === name ? null : name; }
function toggleExpanded() {
  expanded.value = !expanded.value;
  if (!expanded.value) openMenu.value = null;
  localStorage.setItem('library.filtersExpanded', String(expanded.value));
}
function handleOutsideClick(event) { if (!event.target.closest('.multi-select')) openMenu.value = null; }
onMounted(() => {
  const saved = localStorage.getItem('library.filtersExpanded');
  expanded.value = saved === null ? !window.matchMedia('(max-width:640px)').matches : saved === 'true';
  document.addEventListener('click', handleOutsideClick);
});
onUnmounted(() => document.removeEventListener('click', handleOutsideClick));

const requesterLabels = computed(() => {
  const byId = new Map(props.requesters.map(r => [r.id, r.label]));
  return props.requesterFilters.map(id => byId.get(id) || id).join(', ');
});

function toggleValue(event, list, value) {
  const next = list.includes(value) ? list.filter(x => x !== value) : [...list, value];
  emit(event, next);
}
</script>

<style scoped>
.compact-filter-toggle{display:inline-flex;align-items:center;gap:7px;flex:none;min-height:38px;padding:0 10px}.compact-filter-toggle svg{width:15px;height:15px}.compact-filter-toggle strong{display:inline-grid;place-items:center;min-width:20px;height:20px;padding:0 5px;border-radius:999px;background:var(--accent);color:#17130a;font-size:10px}.compact-filter-toggle span{font-size:12px}
@media(max-width:640px){.filter-row{display:flex}.filter-row .search{flex:1 0 100%;width:100%;min-width:0}.filter-row .segmented{margin-right:auto}.compact-filter-toggle{margin-left:auto;min-height:44px}.filter-pills-scroll{max-height:44px}.filters-panel:has(.filter-pills-scroll[style*="display: none"]){padding-bottom:10px}}
</style>
