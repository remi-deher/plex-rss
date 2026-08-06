<template>
  <RouterLink class="discover-source-card" :to="to" :aria-label="`Découvrir ${source.name}`" :title="source.name">
    <img v-if="source.logo_url" :src="source.logo_url" :alt="source.name" loading="lazy" decoding="async">
    <strong v-else>{{ source.name }}</strong>
  </RouterLink>
</template>

<script setup>
defineProps({
  source: { type: Object, required: true },
  to: { type: [String, Object], required: true },
});
</script>

<style scoped>
.discover-source-card {
  display: grid;
  place-items: center;
  width: 100%;
  aspect-ratio: 1 / 1;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  background: var(--surface);
  text-align: center;
  text-decoration: none;
}
.discover-source-card:hover { border-color: color-mix(in srgb, var(--accent) 55%, var(--border)); transform: translateY(-2px); }
.discover-source-card img { max-width: 100%; max-height: 100%; object-fit: contain; }
.discover-source-card strong { font-size: var(--fs-xs); line-height: 1.15; }
</style>
