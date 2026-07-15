<template>
  <div class="interval-input">
    <input v-model.number="amount" type="number" min="1" @input="emitChange">
    <select v-model="unit" @change="onUnitChange">
      <option value="3600">Heures</option>
      <option value="60">Minutes</option>
      <option value="1">Secondes</option>
    </select>
  </div>
</template>
<script setup>
import { ref, watch } from 'vue';

const props = defineProps({
  modelValue: { type: Number, required: true }, // total en secondes
});
const emit = defineEmits(['update:modelValue']);

function bestUnit(seconds) {
  if (seconds > 0 && seconds % 3600 === 0) return 3600;
  if (seconds > 0 && seconds % 60 === 0) return 60;
  return 1;
}

const unit = ref(String(bestUnit(props.modelValue)));
const amount = ref(props.modelValue / Number(unit.value));

watch(() => props.modelValue, (val) => {
  const computed = amount.value * Number(unit.value);
  if (computed === val) return; // evite de re-decomposer notre propre emission
  unit.value = String(bestUnit(val));
  amount.value = val / Number(unit.value);
});

function emitChange() {
  if (!amount.value || amount.value < 1) return;
  emit('update:modelValue', Math.round(amount.value * Number(unit.value)));
}

function onUnitChange() {
  emitChange();
}
</script>
<style scoped>
.interval-input {
  display: flex;
  gap: 8px;
}
.interval-input input {
  width: 90px;
  flex-shrink: 0;
}
</style>
