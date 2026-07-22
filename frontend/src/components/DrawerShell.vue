<template>
  <div class="drawer-backdrop" @click.self="$emit('close')">
    <aside ref="panelRef" tabindex="-1" class="detail-drawer" :class="{ wide }" role="dialog" aria-modal="true" :aria-label="title || 'Detail'">
      <slot name="background" />
      <header class="drawer-head">
        <div><span v-if="eyebrow" class="eyebrow">{{ eyebrow }}</span><h2>{{ title }}</h2></div>
        <button class="icon-button" title="Fermer" aria-label="Fermer" @click="$emit('close')"><X /></button>
      </header>
      <p v-if="error" class="notice error-text">{{ error }}</p>
      <slot />
    </aside>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import { X } from '@lucide/vue';
import { useModalA11y } from '@/composables/useModalA11y';

defineProps({
  eyebrow: { type: String, default: '' },
  title: { type: String, default: '' },
  wide: { type: Boolean, default: false },
  error: { type: String, default: '' },
});
const emit = defineEmits(['close']);

const panelRef = ref(null);
useModalA11y(panelRef, null, () => emit('close'));
</script>
