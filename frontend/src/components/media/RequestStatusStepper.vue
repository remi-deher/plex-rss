<template>
  <div class="status-stepper">
    <span v-for="step in steps" :key="step.key" :class="['step', stepState(step.key)]">{{ step.label }}</span>
  </div>
</template>

<script setup>
// Frise d'avancement d'une demande. Deux parcours : une demande utilisateur part de
// « Demandee », une entrée détectée directement dans *arr part de « Detectee dans *ARR »
// (il n'y a jamais eu de demande à l'origine).
import { computed } from 'vue';

const REQUEST_STEPS = [
  { key: 'requested', label: 'Demandee' },
  { key: 'submitted', label: 'Transmise a *ARR' },
  { key: 'queued', label: 'En file' },
  { key: 'downloading', label: 'Telechargement' },
  { key: 'importing', label: 'Import *ARR' },
  { key: 'awaiting_plex', label: 'Attente Plex' },
  { key: 'completed', label: 'Disponible' },
];
const ARR_STEPS = REQUEST_STEPS.filter(step => step.key !== 'requested')
  .map(step => (step.key === 'submitted' ? { key: 'submitted', label: 'Detectee dans *ARR' } : step));

const props = defineProps({ row: { type: Object, required: true } });

const steps = computed(() => (props.row.origin_kind === 'arr' ? ARR_STEPS : REQUEST_STEPS));

// Normalise le statut opérationnel vers une étape de la frise : les états antérieurs à la
// transmission se lisent « Demandee », et « partiellement disponible » se lit « Disponible »
// (au moins un épisode est regardable — le détail par saison est affiché à côté).
const currentStep = computed(() => {
  let current = props.row.operational_status || 'not_submitted';
  if (['not_submitted', 'awaiting_submission'].includes(current)) current = 'requested';
  if (current === 'partially_available') current = 'completed';
  if (props.row.origin_kind === 'arr' && current === 'requested') current = 'submitted';
  return current;
});

function stepState(key) {
  const order = steps.value.map(step => step.key);
  const statusIndex = Math.max(0, order.indexOf(currentStep.value));
  const keyIndex = order.indexOf(key);
  if (keyIndex < statusIndex) return 'done';
  if (keyIndex === statusIndex) return 'current';
  return 'upcoming';
}
</script>
