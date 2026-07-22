<template>
  <div v-if="open" class="drawer-backdrop" @click.self="!busy && $emit('cancel')">
    <aside ref="panelRef" tabindex="-1" class="modal-panel confirm-modal" role="dialog" aria-modal="true" aria-labelledby="confirm-modal-title">
      <div class="panel-head">
        <div>
          <h2 id="confirm-modal-title">{{ title }}</h2>
          <p v-if="message">{{ message }}</p>
        </div>
        <button class="icon-button" title="Fermer" aria-label="Fermer" :disabled="busy" @click="$emit('cancel')">×</button>
      </div>
      <div class="form-actions">
        <button class="secondary" :disabled="busy" @click="$emit('cancel')">Annuler</button>
        <button :class="danger ? 'danger-button' : 'primary'" :disabled="busy" @click="$emit('confirm')">
          {{ busy ? 'Traitement…' : confirmLabel }}
        </button>
      </div>
    </aside>
  </div>
</template>

<script setup>
import { ref, toRef } from 'vue';
import { useModalA11y } from '@/composables/useModalA11y';

const props = defineProps({
  open: Boolean,
  title: { type: String, default: 'Confirmer l’action' },
  message: { type: String, default: '' },
  confirmLabel: { type: String, default: 'Confirmer' },
  danger: Boolean,
  busy: Boolean,
});
const emit = defineEmits(['cancel', 'confirm']);

const panelRef = ref(null);
useModalA11y(panelRef, toRef(props, 'open'), () => { if (!props.busy) emit('cancel'); });
</script>

<style scoped>
.confirm-modal { width: min(480px, calc(100% - 24px)); }
.confirm-modal .panel-head p { margin-top: .35rem; color: var(--muted, #667085); }
.confirm-modal .form-actions { justify-content: flex-end; margin-top: 1.5rem; }
</style>
