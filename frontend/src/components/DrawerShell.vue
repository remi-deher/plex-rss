<template>
  <div class="drawer-backdrop" @click.self="$emit('close')">
    <aside class="detail-drawer" :class="{ wide }" role="dialog" aria-modal="true" :aria-label="title || 'Detail'">
      <slot name="background" />
      <header class="drawer-head">
        <div><span v-if="eyebrow" class="eyebrow">{{ eyebrow }}</span><h2>{{ title }}</h2></div>
        <button class="icon-button" title="Fermer" @click="$emit('close')"><X /></button>
      </header>
      <p v-if="error" class="notice error-text">{{ error }}</p>
      <slot />
    </aside>
  </div>
</template>

<script setup>
import { X } from '@lucide/vue';

defineProps({
  eyebrow: { type: String, default: '' },
  title: { type: String, default: '' },
  wide: { type: Boolean, default: false },
  error: { type: String, default: '' },
});
defineEmits(['close']);
</script>
