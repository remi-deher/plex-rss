<template>
  <div class="interval-input">
    <div class="stepper">
      <button type="button" class="step-btn" :disabled="amount<=1" @click="step(-1)"><Minus/></button>
      <input v-model.number="amount" type="number" min="1" @input="onAmountInput" @blur="clampAmount">
      <button type="button" class="step-btn" @click="step(1)"><Plus/></button>
    </div>
    <div v-if="units.length>1" class="segmented small unit-toggle">
      <button v-for="u in units" :key="u" type="button" :class="{active:displayUnit===u}" @click="setUnit(u)">{{ UNIT_LABELS[u] }}</button>
    </div>
    <span v-else class="unit-label">{{ UNIT_LABELS[units[0]] }}</span>
  </div>
</template>
<script setup>
import { ref, watch } from 'vue';
import { Minus, Plus } from '@lucide/vue';

// Composant reutilisable pour tout champ "a quelle frequence" (intervalle de
// verification, de rescan...), quelle que soit l'unite de stockage cote backend
// (secondes ou minutes) -- remplace les <input type="number"> ad-hoc epars dans
// les differents onglets de Parametres par un stepper + bascule d'unite commune.

const SECONDS_PER_UNIT = { hours: 3600, minutes: 60, seconds: 1 };
const UNIT_LABELS = { hours: 'Heures', minutes: 'Minutes', seconds: 'Secondes' };

const props = defineProps({
  modelValue: { type: Number, required: true }, // exprime dans `storageUnit`
  storageUnit: { type: String, default: 'seconds' }, // unite de `modelValue`
  units: { type: Array, default: () => ['hours', 'minutes', 'seconds'] }, // unites proposees a l'utilisateur
});
const emit = defineEmits(['update:modelValue']);

function bestUnit(totalSeconds) {
  const candidates = props.units;
  if (candidates.includes('hours') && totalSeconds > 0 && totalSeconds % 3600 === 0) return 'hours';
  if (candidates.includes('minutes') && totalSeconds > 0 && totalSeconds % 60 === 0) return 'minutes';
  return candidates[candidates.length - 1];
}

function toSeconds(value, unit) { return value * SECONDS_PER_UNIT[unit]; }

const initialSeconds = toSeconds(props.modelValue, props.storageUnit);
const displayUnit = ref(bestUnit(initialSeconds));
const amount = ref(Math.round(initialSeconds / SECONDS_PER_UNIT[displayUnit.value]));

watch(() => props.modelValue, (val) => {
  const totalSeconds = toSeconds(val, props.storageUnit);
  const ourSeconds = toSeconds(amount.value, displayUnit.value);
  if (ourSeconds === totalSeconds) return; // evite de re-decomposer notre propre emission
  displayUnit.value = bestUnit(totalSeconds);
  amount.value = Math.round(totalSeconds / SECONDS_PER_UNIT[displayUnit.value]);
});

function emitChange() {
  if (!amount.value || amount.value < 1) return;
  const totalSeconds = toSeconds(amount.value, displayUnit.value);
  emit('update:modelValue', Math.round(totalSeconds / SECONDS_PER_UNIT[props.storageUnit]));
}

function onAmountInput() { emitChange(); }
function clampAmount() { if (!amount.value || amount.value < 1) amount.value = 1; emitChange(); }
function step(delta) { amount.value = Math.max(1, (amount.value || 0) + delta); emitChange(); }
function setUnit(u) {
  if (u === displayUnit.value) return;
  const totalSeconds = toSeconds(amount.value, displayUnit.value);
  displayUnit.value = u;
  amount.value = Math.max(1, Math.round(totalSeconds / SECONDS_PER_UNIT[u]));
  emitChange();
}
</script>
<style scoped>
.interval-input {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.stepper {
  display: flex;
  align-items: center;
  gap: 0;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 999px;
  overflow: hidden;
  flex-shrink: 0;
}

.stepper input {
  width: 56px;
  text-align: center;
  border: none;
  background: transparent;
  padding: 8px 2px;
  font-variant-numeric: tabular-nums;
  -moz-appearance: textfield;
}

.stepper input::-webkit-outer-spin-button,
.stepper input::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
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

.step-btn:hover:not(:disabled) {
  color: var(--text);
  background: rgba(255, 255, 255, 0.06);
}

.step-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.step-btn svg {
  width: 14px;
  height: 14px;
}

.unit-toggle {
  flex-shrink: 0;
}

.unit-label {
  font-size: 0.8125rem;
  color: var(--muted);
}
</style>
