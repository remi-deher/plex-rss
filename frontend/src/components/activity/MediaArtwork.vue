<template>
  <div class="media-artwork" :class="size">
    <img v-if="src && !failed" :src="src" :alt="alt" loading="lazy" decoding="async" @error="failed=true">
    <component :is="fallbackIcon" v-else />
  </div>
</template>

<script setup>
import { Clapperboard, Music2 } from '@lucide/vue';
import { computed, ref, watch } from 'vue';
const props = defineProps({
  src: { type: String, default: '' },
  alt: { type: String, default: '' },
  type: { type: String, default: '' },
  size: { type: String, default: 'medium' },
});
const failed=ref(false);
watch(()=>props.src,()=>{failed.value=false});
const fallbackIcon=computed(()=>props.type==='track'?Music2:Clapperboard);
</script>

<style scoped>
.media-artwork{display:grid;place-items:center;flex:none;overflow:hidden;border:1px solid rgba(255,255,255,.06);border-radius:8px;background:linear-gradient(145deg,#252525,#121212);color:var(--muted)}.media-artwork.small{width:42px;height:58px}.media-artwork.medium{width:54px;height:76px}.media-artwork.large{width:104px;height:150px}.media-artwork img{width:100%;height:100%;object-fit:cover}.media-artwork svg{width:30%;height:auto}
</style>
