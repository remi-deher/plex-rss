<template>
  <section class="drawer-section form-section">
    <h3>Demander ce media</h3>
    <label v-if="requesters.length">Demandeur
      <select v-model="form.plex_user_id">
        <option v-for="user in requesters" :key="user.plex_user_id" :value="user.plex_user_id">{{ user.custom_name || user.display_name || user.plex_user_id }}</option>
      </select>
    </label>
    <label v-if="folders.length">Dossier racine
      <select v-model="form.root_folder">
        <option value="">Dossier par defaut</option>
        <option v-for="folder in folders" :key="folder.path || folder" :value="folder.path || folder">{{ folder.path || folder }}</option>
      </select>
    </label>
    <div v-if="detail.media_type === 'show' && seasonNumbers.length" class="season-grid">
      <label v-for="season in seasonNumbers" :key="season" class="check"><input v-model="form.seasons" type="checkbox" :value="season"> Saison {{ season }}</label>
    </div>
    <button class="primary" :disabled="busy || !form.plex_user_id || (detail.media_type === 'show' && !form.seasons.length)" @click="$emit('submit')"><PlusCircle/>{{ busy ? 'Envoi...' : 'Demander' }}</button>
  </section>
</template>

<script setup>
import { computed } from 'vue';
import { PlusCircle } from '@lucide/vue';

const props = defineProps({
  detail: { type: Object, required: true },
  form: { type: Object, required: true },
  requesters: { type: Array, default: () => [] },
  folders: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
});
defineEmits(['submit']);

const seasonNumbers = computed(() => Array.from({ length: Number(props.detail?.number_of_seasons || 0) }, (_, i) => i + 1));
</script>
