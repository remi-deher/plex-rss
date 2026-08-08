<template>
  <div class="poster-shell">
    <img v-if="posterUrl" :src="posterUrl" :alt="alt" loading="lazy" decoding="async" @error="$event.target.style.display='none'">
    <div v-else class="poster-fallback">
      <Music2 v-if="isMusic" />
      <Film v-else />
    </div>
    <slot name="badges" />
    <slot name="overlay" />
  </div>
</template>

<script setup>
import { Film, Music2 } from '@lucide/vue';

defineProps({
  posterUrl: { type: String, default: null },
  alt: { type: String, default: '' },
  isMusic: { type: Boolean, default: false },
});
</script>
