<template>
  <div class="retention-input">
    <input
      v-if="!indefinite"
      type="number"
      min="1"
      :value="modelValue"
      :placeholder="placeholder"
      @input="onInput"
    >
    <label class="check retention-indefinite">
      <input type="checkbox" :checked="indefinite" @change="onToggle($event.target.checked)">
      Conserver indéfiniment
    </label>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue';

// Reglage "retention en jours" reutilisable : bascule explicite entre une valeur
// numerique et "indefiniment" (valeur null/0 cote backend, voir _nullable_fields dans
// app/routers/settings_api.py) plutot que de faire deviner a l'utilisateur qu'un champ
// vide veut dire "toujours" -- source de confusion frequente sur ces reglages RGPD.
const props = defineProps({
  modelValue: { type: Number, default: null },
  placeholder: { type: [Number, String], default: '' },
  defaultDays: { type: Number, default: 30 },
});
const emit = defineEmits(['update:modelValue']);

const indefinite = computed(() => !props.modelValue);
// Derniere valeur numerique connue, pour la restaurer si l'utilisateur decoche
// "Conserver indefiniment" sans avoir a la ressaisir.
const lastCustomValue = ref(props.modelValue || props.defaultDays);
watch(() => props.modelValue, (value) => { if (value) lastCustomValue.value = value; });

function onInput(event) {
  const value = Number(event.target.value);
  if (value > 0) emit('update:modelValue', value);
}
function onToggle(checked) {
  emit('update:modelValue', checked ? null : lastCustomValue.value);
}
</script>

<style scoped>
.retention-input { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }
.retention-input input[type="number"] { width: 100px; }
.retention-indefinite { width: auto; }
</style>
