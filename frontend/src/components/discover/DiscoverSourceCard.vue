<template>
  <RouterLink class="discover-source-card" :to="to" :aria-label="`Découvrir ${source.name}`">
    <img v-if="source.logo_url" :src="source.logo_url" :alt="source.name" loading="lazy" decoding="async">
    <strong v-else>{{ source.name }}</strong>
    <span v-if="source.kind">{{ kindLabel }}</span>
  </RouterLink>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  source: { type: Object, required: true },
  to: { type: [String, Object], required: true },
});

const kindLabel = computed(() => ({
  provider: 'Plateforme',
  network: 'Diffuseur',
  company: 'Studio',
})[props.source.kind] || props.source.kind);
</script>

<style scoped>
.discover-source-card {
  display: grid;
  place-items: center;
  gap: 8px;
  min-height: 112px;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: 12px;
  color: var(--text);
  background: var(--surface);
  text-align: center;
  text-decoration: none;
}
.discover-source-card:hover { border-color: color-mix(in srgb, var(--accent) 55%, var(--border)); transform: translateY(-2px); }
.discover-source-card img { max-width: 86px; max-height: 46px; object-fit: contain; }
.discover-source-card span { color: var(--muted); font-size: .72rem; }
</style>
