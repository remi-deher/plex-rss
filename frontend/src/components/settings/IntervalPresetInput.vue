<template>
  <div class="interval-preset">
    <select :value="selectValue" @change="onSelect($event.target.value)">
      <option v-for="p in presets" :key="p.value" :value="p.value">{{ p.label }}</option>
      <option value="custom">Personnalise...</option>
    </select>
    <input v-if="customMode" type="number" min="1" :value="modelValue" placeholder="Valeur" @input="onCustomInput">
  </div>
</template>
<script setup>
import { ref, watch } from 'vue';

// Composant reutilisable pour tout reglage "a quelle frequence" (intervalle de
// verification, de rescan...) : une liste de frequences courantes plutot qu'un
// stepper+bascule d'unite -- plus rapide a lire et a choisir pour les valeurs les
// plus courantes, avec un repli "Personnalise" pour les cas particuliers.
//
// `presets` : [{ label, value }], value exprimee dans la meme unite que `modelValue`
// (pas de conversion a faire ici, contrairement a l'ancien stepper -- l'appelant
// choisit deja des presets dans l'unite de stockage).

const props = defineProps({
  modelValue: { type: Number, required: true },
  presets: { type: Array, required: true },
});
const emit = defineEmits(['update:modelValue']);

function matchesPreset(value) { return props.presets.some(p => p.value === value); }

const customMode = ref(!matchesPreset(props.modelValue));
const selectValue = ref(customMode.value ? 'custom' : String(props.modelValue));

watch(() => props.modelValue, (val) => {
  if (customMode.value) return; // en mode personnalise, le select reste sur "custom"
  selectValue.value = String(val);
});

function onSelect(raw) {
  if (raw === 'custom') {
    customMode.value = true;
    selectValue.value = 'custom';
    return;
  }
  customMode.value = false;
  selectValue.value = raw;
  emit('update:modelValue', Number(raw));
}

function onCustomInput(event) {
  const value = Number(event.target.value);
  if (value > 0) emit('update:modelValue', value);
}
</script>
<style scoped>
.interval-preset {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.interval-preset select {
  width: auto;
}

.interval-preset input {
  width: 100px;
}
</style>
