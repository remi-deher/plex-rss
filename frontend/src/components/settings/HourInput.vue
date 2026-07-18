<template>
  <div class="hour-input">
    <div class="stepper">
      <button type="button" class="step-btn" @click="step(-1)"><Minus/></button>
      <span class="hour-display">{{ formatted }}</span>
      <button type="button" class="step-btn" @click="step(1)"><Plus/></button>
    </div>
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue';
import { Minus, Plus } from '@lucide/vue';

// Composant reutilisable pour tout reglage "heure murale" (0-23, ex: digest_hour,
// plex_sync_hour) : une heure du jour n'est pas une duree (pas d'unite a choisir,
// juste un cadran qui boucle entre 0 et 23) -- volontairement distinct de
// IntervalInput, qui lui exprime un intervalle/frequence.

const props = defineProps({
  modelValue: { type: Number, required: true }, // 0-23
});
const emit = defineEmits(['update:modelValue']);

// Etat local plutot que de deriver directement de props.modelValue : un aller-retour
// props -> emit -> parent -> props prend un cycle de rendu Vue complet, donc des clics
// rapides et consecutifs sur +/- liraient tous la meme valeur (encore) pas a jour et
// n'avanceraient que d'un cran au lieu de N (bug constate en testant le stepper).
const hour = ref(props.modelValue ?? 0);
watch(() => props.modelValue, (val) => { if (val !== hour.value) hour.value = val ?? 0; });

const formatted = computed(() => `${String(hour.value).padStart(2, '0')} h`);

function step(delta) {
  hour.value = (hour.value + delta + 24) % 24;
  emit('update:modelValue', hour.value);
}
</script>
<style scoped>
.stepper {
  display: flex;
  align-items: center;
  gap: 0;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 999px;
  overflow: hidden;
  width: fit-content;
}

.hour-display {
  width: 52px;
  text-align: center;
  font-variant-numeric: tabular-nums;
  font-size: 0.875rem;
  font-weight: 500;
}

.step-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  transition: color 0.15s ease, background 0.15s ease;
}

.step-btn:hover {
  color: var(--text);
  background: rgba(255, 255, 255, 0.06);
}

.step-btn svg {
  width: 14px;
  height: 14px;
}
</style>
