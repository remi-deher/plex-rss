<template>
  <div class="poster-shell">
    <img v-if="posterUrl" :src="posterUrl" alt="" @error="$event.target.style.display='none'">
    <div v-else class="poster-fallback"><Film/></div>
    <slot name="badges" />
    <slot name="overlay" />
  </div>
</template>

<script setup>
import { Film } from '@lucide/vue';

defineProps({
  posterUrl: { type: String, default: null },
});
</script>
