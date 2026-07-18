<template>
  <div class="filters-panel">
    <div class="filter-row">
      <input :value="query" class="search" type="search" placeholder="Rechercher" @input="$emit('update:query',$event.target.value);$emit('search')">
      <div class="segmented">
        <button :class="{active:view==='grid'}" title="Grille" @click="$emit('update:view','grid')"><Grid2X2/></button>
        <button :class="{active:view==='list'}" title="Liste" @click="$emit('update:view','list')"><List/></button>
      </div>
    </div>

    <div class="filter-pills-scroll">
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
import { ChevronDown, Grid2X2, List } from '@lucide/vue';
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

const openMenu = ref(null);
function toggle(name) { openMenu.value = openMenu.value === name ? null : name; }
function handleOutsideClick(event) { if (!event.target.closest('.multi-select')) openMenu.value = null; }
onMounted(() => document.addEventListener('click', handleOutsideClick));
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
