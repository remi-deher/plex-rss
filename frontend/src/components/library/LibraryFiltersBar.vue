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
      <button class="filter-pill" :class="{active:type===''}" @click="$emit('update:type','')">Tout</button>
      <button class="filter-pill" :class="{active:type==='movie'}" @click="$emit('update:type','movie')">Films</button>
      <button class="filter-pill" :class="{active:type==='show'}" @click="$emit('update:type','show')">Séries</button>

      <div class="divider"></div>
      <span class="filter-label">Statut:</span>
      <button class="filter-pill" :class="{active:status===''}" @click="$emit('update:status','')">Tout</button>
      <button class="filter-pill" :class="{active:status==='library'}" @click="$emit('update:status','library')">Dans Plex</button>
      <button class="filter-pill" :class="{active:status==='request'}" @click="$emit('update:status','request')">En cours</button>
      <button class="filter-pill" :class="{active:status==='partial'}" @click="$emit('update:status','partial')">Partiellement disponible</button>

      <div class="divider"></div>
      <span class="filter-label">Audio:</span>
      <button class="filter-pill" :class="{active:vf===''}" @click="$emit('update:vf','')">Toutes</button>
      <button class="filter-pill" :class="{active:vf==='vf'}" @click="$emit('update:vf','vf')">VF</button>
      <button class="filter-pill" :class="{active:vf==='vo'}" @click="$emit('update:vf','vo')">VO</button>
      <button class="filter-pill" :class="{active:vf==='unchecked'}" @click="$emit('update:vf','unchecked')">Non analysée</button>

      <template v-if="users.length > 0">
        <div class="divider"></div>
        <span class="filter-label">Utilisateur:</span>
        <select :value="userFilter" class="filter-select" title="Filtre pour les demandes en cours" @change="$emit('update:userFilter',$event.target.value)">
          <option value="">Tous</option>
          <option v-for="u in users" :key="u.id" :value="u.plex_user_id || u.custom_name || u.display_name">{{ u.custom_name || u.display_name || u.plex_user_id }}</option>
        </select>
      </template>
    </div>
  </div>
</template>

<script setup>
import { Grid2X2, List } from '@lucide/vue';

defineProps({
  query: { type: String, default: '' },
  type: { type: String, default: '' },
  vf: { type: String, default: '' },
  status: { type: String, default: '' },
  userFilter: { type: String, default: '' },
  view: { type: String, default: 'grid' },
  users: { type: Array, default: () => [] },
});
defineEmits(['update:query', 'update:type', 'update:vf', 'update:status', 'update:userFilter', 'update:view', 'search']);
</script>
