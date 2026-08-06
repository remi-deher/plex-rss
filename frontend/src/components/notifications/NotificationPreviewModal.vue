<template>
  <ModalShell
    :open="open"
    title="Aperçu de l'email"
    :subtitle="subject"
    panel-class="notification-preview-modal"
    :error="error"
    @close="$emit('close')"
  >
    <p v-if="loading" class="notice">Chargement…</p>
    <template v-else>
      <p v-if="note" class="notice">{{ note }}</p>
      <p v-if="!reconstructable && !note" class="notice">{{ note || "Aperçu indisponible pour ce type d'événement." }}</p>
      <div v-if="html" class="notification-preview-viewport">
        <iframe :srcdoc="html" title="Aperçu email" sandbox="allow-same-origin"></iframe>
      </div>
    </template>
  </ModalShell>
</template>

<script setup>
import ModalShell from '@/components/ui/ModalShell.vue';

defineProps({
  open: Boolean,
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  subject: { type: String, default: '' },
  html: { type: String, default: '' },
  note: { type: String, default: '' },
  reconstructable: { type: Boolean, default: true },
});
defineEmits(['close']);
</script>

<style scoped>
:deep(.notification-preview-modal) { width: min(720px, calc(100% - 24px)); }
.notification-preview-viewport {
  overflow: auto;
  margin-top: 12px;
  padding: 10px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}
.notification-preview-viewport iframe {
  display: block;
  width: 100%;
  min-height: 60vh;
  border: 0;
}
</style>
