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
    <div class="form-actions">
      <button class="secondary" :disabled="busy" @click="$emit('cancel')">Annuler</button>
      <button class="primary" :disabled="busy || !plexUserId" @click="$emit('confirm')">
        {{ busy ? 'Envoi…' : confirmLabel }}
      </button>
    </div>
  </ModalShell>
</template>

<script setup>
import ModalShell from '@/components/ui/ModalShell.vue';

defineProps({
  open: { type: Boolean, default: false },
  mediaTitle: { type: String, default: '' },
  requesters: { type: Array, default: () => [] },
  folders: { type: Array, default: () => [] },
  plexUserId: { type: String, default: '' },
  rootFolder: { type: String, default: '' },
  busy: { type: Boolean, default: false },
  confirmLabel: { type: String, default: 'Envoyer la demande' },
});
defineEmits(['update:plexUserId', 'update:rootFolder', 'confirm', 'cancel']);
</script>

<style scoped>
:deep(.request-options-modal) { width: min(480px, calc(100% - 24px)); }
.request-options-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); }
.request-options-grid label { display: grid; gap: var(--space-2); font-size: var(--fs-sm); font-weight: 600; }
.form-actions { justify-content: flex-end; margin-top: 1.5rem; }
@media (max-width: 640px) {
  .request-options-grid { grid-template-columns: 1fr; }
}
</style>
