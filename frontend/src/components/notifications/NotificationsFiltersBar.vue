<template>
  <div class="filter-pills-scroll">
    <span class="filter-label">Etat:</span>
    <div class="multi-select" :class="{open:activeDropdown==='state'}" v-click-outside="() => { if (activeDropdown === 'state') activeDropdown = null }">
      <button class="filter-pill dropdown-toggle" @click="activeDropdown = activeDropdown === 'state' ? null : 'state'">
        {{ state === 'success' ? 'Envoyees' : state === 'error' ? 'Erreurs' : 'Tous les etats' }}
        <ChevronDown/>
      </button>
      <div v-if="activeDropdown === 'state'" class="multi-select-menu" @click.stop>
        <label class="check"><input type="radio" :checked="state===''" @change="$emit('update:state','')"> Tous les etats</label>
        <label class="check"><input type="radio" :checked="state==='success'" @change="$emit('update:state','success')"> Envoyees</label>
        <label class="check"><input type="radio" :checked="state==='error'" @change="$emit('update:state','error')"> Erreurs</label>
      </div>
    </div>

    <div class="divider"></div>
    <span class="filter-label">Types:</span>
    <div class="multi-select" :class="{open:activeDropdown==='types'}" v-click-outside="() => { if (activeDropdown === 'types') activeDropdown = null }">
      <button class="filter-pill dropdown-toggle" @click="activeDropdown = activeDropdown === 'types' ? null : 'types'">
        {{ selectedTypes.length ? selectedTypes.map(v=>typeOptions.find(o=>o.value===v)?.label||v).join(', ') : 'Tous les types' }}
        <ChevronDown/>
      </button>
      <div v-if="activeDropdown === 'types'" class="multi-select-menu" @click.stop>
        <label class="check" v-for="typeOpt in typeOptions" :key="typeOpt.value">
          <input type="checkbox" :value="typeOpt.value" :checked="selectedTypes.includes(typeOpt.value)" @change="toggleValue('update:selectedTypes',selectedTypes,typeOpt.value)"> {{ typeOpt.label }}
        </label>
        <button v-if="selectedTypes.length" class="text-button clear-selection" @click="$emit('update:selectedTypes',[])">Effacer</button>
      </div>
    </div>

    <div class="divider"></div>
    <span class="filter-label">Utilisateurs:</span>
    <div class="multi-select" :class="{open:activeDropdown==='users'}" v-click-outside="() => { if (activeDropdown === 'users') activeDropdown = null }">
      <button class="filter-pill dropdown-toggle" @click="activeDropdown = activeDropdown === 'users' ? null : 'users'">
        {{ selectedUsers.length ? `${selectedUsers.length} selectionne(s)` : 'Tous les utilisateurs' }}
        <ChevronDown/>
      </button>
      <div v-if="activeDropdown === 'users'" class="multi-select-menu" @click.stop>
        <label class="check" v-for="user in users" :key="user.id">
          <input type="checkbox" :value="user.id" :checked="selectedUsers.includes(user.id)" @change="toggleValue('update:selectedUsers',selectedUsers,user.id)"> {{ user.custom_name || user.display_name || user.plex_user_id }}
        </label>
        <p v-if="!users.length" class="empty">Aucun utilisateur.</p>
        <button v-if="selectedUsers.length" class="text-button clear-selection" @click="$emit('update:selectedUsers',[])">Effacer</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import { ChevronDown } from '@lucide/vue';

defineProps({
  state: { type: String, default: '' },
  selectedTypes: { type: Array, default: () => [] },
  selectedUsers: { type: Array, default: () => [] },
  users: { type: Array, default: () => [] },
  typeOptions: { type: Array, default: () => [] },
});
const emit = defineEmits(['update:state', 'update:selectedTypes', 'update:selectedUsers']);

const activeDropdown = ref(null);

function toggleValue(event, list, value) {
  const next = list.includes(value) ? list.filter(x => x !== value) : [...list, value];
  emit(event, next);
}

const vClickOutside = {
  mounted(el, binding) {
    el.clickOutsideEvent = function (event) {
      if (!(el === event.target || el.contains(event.target))) {
        binding.value(event);
      }
    };
    document.addEventListener('click', el.clickOutsideEvent);
  },
  unmounted(el) {
    document.removeEventListener('click', el.clickOutsideEvent);
  },
};
</script>
