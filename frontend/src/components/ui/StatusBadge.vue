<template>
  <span class="ui-status" :class="`is-${tone}`" :title="description || undefined">
    <span class="ui-status-dot" aria-hidden="true" />
    <span>{{ displayLabel }}</span>
  </span>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  status: { type: String, default: 'neutral' },
  label: { type: String, default: '' },
  description: { type: String, default: '' },
});

const definitions = {
  available: ['success', 'Disponible'], completed: ['success', 'Terminé'], active: ['success', 'Actif'], sent: ['success', 'Envoyée'], closed: ['success', 'Clos'],
  sent_to_arr: ['info', 'Transmise à *Arr'], downloading: ['info', 'Téléchargement'], investigating: ['info', 'En cours'], running: ['info', 'En cours'],
  pending: ['neutral', 'En attente'], queued: ['neutral', 'En file'], inactive: ['neutral', 'Inactif'],
  pending_approval: ['warning', 'À approuver'], partially_available: ['warning', 'Partiellement disponible'], paused: ['warning', 'En pause'], open: ['warning', 'Ouvert'], warning: ['warning', 'Attention'],
  failed: ['danger', 'Échec'], error: ['danger', 'Erreur'], rejected: ['danger', 'Refusée'], blocked: ['danger', 'Bloqué'],
};
const normalized = computed(() => String(props.status || 'neutral').toLowerCase());
const tone = computed(() => definitions[normalized.value]?.[0] || 'neutral');
const displayLabel = computed(() => props.label || definitions[normalized.value]?.[1] || String(props.status || '—'));
</script>
