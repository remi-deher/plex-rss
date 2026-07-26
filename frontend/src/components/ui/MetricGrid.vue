<template>
  <section class="metric-grid" :class="gridClass" :aria-label="ariaLabel">
    <slot />
  </section>
</template>

<script setup>
// Grille de tuiles de métriques. La variante (`compact-metrics`, `dashboard-metrics`,
// `activity-metrics`) porte le nombre de colonnes et les ruptures responsives.
defineProps({
  gridClass: { type: String, default: 'compact-metrics' },
  ariaLabel: { type: String, default: '' },
});
</script>
