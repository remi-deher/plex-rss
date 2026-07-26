<template>
  <span class="ui-status" :class="`is-${tone}`" :title="description || undefined">
    <span class="ui-status-dot" aria-hidden="true" />
    <span>{{ displayLabel }}</span>
  </span>
</template>

<script setup>
import { computed } from 'vue';

import { REQUEST_STATUS_LABELS } from '@/utils/labels';

const props = defineProps({
  status: { type: String, default: 'neutral' },
  label: { type: String, default: '' },
  description: { type: String, default: '' },
});

// Ton visuel par statut. Les statuts de demande tirent leur libellé de
// REQUEST_STATUS_LABELS (source unique, voir @/utils/labels) ; les statuts propres à
// d'autres domaines (tâches, incidents, connexions) portent le leur ici.
const TONES = {
  available: 'success', completed: 'success', active: 'success', sent: 'success', closed: 'success',
  sent_to_arr: 'info', downloading: 'info', investigating: 'info', running: 'info',
  pending: 'neutral', queued: 'neutral', inactive: 'neutral',
  pending_approval: 'warning', partially_available: 'warning', paused: 'warning', open: 'warning', warning: 'warning',
  failed: 'danger', error: 'danger', rejected: 'danger', blocked: 'danger',
};
const OWN_LABELS = {
  completed: 'Terminé', active: 'Actif', sent: 'Envoyée', closed: 'Clos',
  // Nuance propre au badge : ailleurs dans l'app, `sent_to_arr` s'affiche « Transmise ».
  sent_to_arr: 'Transmise à *Arr',
  downloading: 'Téléchargement', investigating: 'En cours', running: 'En cours',
  queued: 'En file', inactive: 'Inactif', paused: 'En pause', open: 'Ouvert',
  warning: 'Attention', error: 'Erreur', blocked: 'Bloqué',
};
const normalized = computed(() => String(props.status || 'neutral').toLowerCase());
const tone = computed(() => TONES[normalized.value] || 'neutral');
const displayLabel = computed(
  () => props.label
    || OWN_LABELS[normalized.value]
    || REQUEST_STATUS_LABELS[normalized.value]
    || String(props.status || '—'),
);
</script>
