<template>
  <ModalShell
    :open="open"
    :title="title"
    :subtitle="message"
    panel-class="confirm-modal"
    :busy="busy"
    @close="$emit('cancel')"
  >
    <div class="form-actions">
      <button class="secondary" :disabled="busy" @click="$emit('cancel')">Annuler</button>
      <button :class="danger ? 'danger-button' : 'primary'" :disabled="busy" @click="$emit('confirm')">
        {{ busy ? 'Traitement…' : confirmLabel }}
      </button>
    </div>
  </ModalShell>
</template>

<script setup>
import ModalShell from '@/components/ui/ModalShell.vue';

defineProps({
  open: Boolean,
  title: { type: String, default: 'Confirmer l’action' },
  message: { type: String, default: '' },
  confirmLabel: { type: String, default: 'Confirmer' },
  danger: Boolean,
  busy: Boolean,
});
defineEmits(['cancel', 'confirm']);
</script>

<style scoped>
/* Le panneau est rendu par ModalShell : il n'est plus la racine de ce composant, d'où
   `:deep`. La racine (le backdrop de ModalShell) porte bien l'attribut de scope, donc
   ces règles restent limitées à cette modale. */
:deep(.confirm-modal) { width: min(480px, calc(100% - 24px)); }
:deep(.confirm-modal .panel-head p) { margin-top: .35rem; color: var(--muted, #667085); }
:deep(.confirm-modal .form-actions) { justify-content: flex-end; margin-top: 1.5rem; }
</style>
