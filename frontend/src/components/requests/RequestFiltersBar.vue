<template>
  <div class="filters-panel">
    <div class="filter-row">
      <input :value="query" class="search" type="search" placeholder="Rechercher un titre" @input="$emit('update:query',$event.target.value);$emit('search')">
      <div class="segmented">
        <button :class="{active:view==='grid'}" title="Grille" @click="$emit('update:view','grid')"><Grid2X2/></button>
        <button :class="{active:view==='list'}" title="Liste" @click="$emit('update:view','list')"><List/></button>
      </div>
    </div>

    <div class="filter-pills-scroll">
      <span class="filter-label">Statut:</span>
      <div class="multi-select" :class="{open:openMenu==='status'}">
        <button class="filter-pill dropdown-toggle" @click="toggle('status')">
          {{ statusFilters.length ? statusFilters.map(statusLabel).join(', ') : 'Tous les statuts' }}
          <ChevronDown/>
        </button>
        <div v-if="openMenu==='status'" class="multi-select-menu" @click.stop>
          <label v-for="value in STATUSES" :key="value" class="check">
            <input type="checkbox" :value="value" :checked="statusFilters.includes(value)" @change="toggleValue('update:statusFilters',statusFilters,value)"> {{ statusLabel(value) }}
          </label>
          <button v-if="statusFilters.length" class="text-button clear-selection" @click="$emit('update:statusFilters',[])">Effacer</button>
        </div>
      </div>

      <div class="divider"></div>
      <span class="filter-label">Type:</span>
      <div class="multi-select" :class="{open:openMenu==='type'}">
        <button class="filter-pill dropdown-toggle" @click="toggle('type')">
          {{ typeFilters.length ? typeFilters.map(typeLabel).join(', ') : 'Tous les types' }}
          <ChevronDown/>
        </button>
        <div v-if="openMenu==='type'" class="multi-select-menu" @click.stop>
          <label v-for="value in TYPES" :key="value" class="check">
            <input type="checkbox" :value="value" :checked="typeFilters.includes(value)" @change="toggleValue('update:typeFilters',typeFilters,value)"> {{ typeLabel(value) }}
          </label>
          <button v-if="typeFilters.length" class="text-button clear-selection" @click="$emit('update:typeFilters',[])">Effacer</button>
        </div>
      </div>

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
import { STATUSES, TYPES, statusLabel, typeLabel } from './requestHelpers';

const props = defineProps({
  query: { type: String, default: '' },
  view: { type: String, default: 'grid' },
  statusFilters: { type: Array, default: () => [] },
  typeFilters: { type: Array, default: () => [] },
  sourceFilters: { type: Array, default: () => [] },
  requesterFilters: { type: Array, default: () => [] },
  sources: { type: Array, default: () => [] },
  requesters: { type: Array, default: () => [] },
});
const emit = defineEmits(['update:query', 'update:view', 'update:statusFilters', 'update:typeFilters', 'update:sourceFilters', 'update:requesterFilters', 'search']);

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
