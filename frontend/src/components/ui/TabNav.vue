<template>
  <nav class="detail-tabs" role="tablist" :aria-label="ariaLabel">
    <button
      v-for="tab in tabs"
      :key="tab.value"
      type="button"
      role="tab"
      :aria-selected="modelValue === tab.value"
      :class="{ active: modelValue === tab.value }"
      @click="$emit('update:modelValue', tab.value)"
    >
      {{ tab.label }}
      <span v-if="tab.count" class="tab-badge" :class="tab.badgeClass">{{ tab.count }}</span>
    </button>
  </nav>
</template>

<script setup>
// Barre d'onglets `.detail-tabs`, recopiée dans cinq vues avec chaque fois son propre
// `:class="{active: …}"` et, selon les cas, `role="tablist"` oublié.
defineProps({
  /** [{ value, label, count?, badgeClass? }] */
  tabs: { type: Array, required: true },
  modelValue: { type: String, required: true },
  ariaLabel: { type: String, default: 'Onglets' },
});
defineEmits(['update:modelValue']);
</script>
