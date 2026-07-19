<template>
  <input type="time" step="60" class="time-of-day-input" :value="timeString" @input="onInput">
</template>
<script setup>
import { computed } from 'vue';

// Composant reutilisable pour tout reglage "heure murale" avec precision minute (ex.
// digest_hour+digest_minute -- un digest doit partir a un instant precis, contrairement
// aux scans/sync periodiques qui utilisent IntervalPresetInput). Un <input type="time">
// natif plutot qu'un stepper maison : chaque segment (heures/minutes) se controle
// independamment (fleches clavier, molette, defilement tactile) sans code a maintenir.
// step="60" masque le segment secondes (non pertinent, ces reglages n'en ont pas).

const props = defineProps({
  hour: { type: Number, required: true },
  minute: { type: Number, required: true },
});
const emit = defineEmits(['update:hour', 'update:minute']);

const timeString = computed(() => `${String(props.hour).padStart(2, '0')}:${String(props.minute).padStart(2, '0')}`);

function onInput(event) {
  const [h, m] = event.target.value.split(':').map(Number);
  if (Number.isFinite(h)) emit('update:hour', h);
  if (Number.isFinite(m)) emit('update:minute', m);
}
</script>
<style scoped>
.time-of-day-input {
  width: fit-content;
}
</style>
