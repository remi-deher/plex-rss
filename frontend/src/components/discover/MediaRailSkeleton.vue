<template>
  <div class="media-rail-skeleton" aria-hidden="true">
    <div v-for="index in count" :key="index" class="skeleton-card">
      <span class="skeleton-poster" />
      <span class="skeleton-line" />
      <span class="skeleton-line short" />
    </div>
  </div>
</template>

<script setup>
defineProps({
  count: { type: Number, default: 6 },
});
</script>

<style scoped>
.media-rail-skeleton {
  display: grid;
  grid-auto-columns: clamp(132px, 16vw, 190px);
  grid-auto-flow: column;
  gap: 14px;
  overflow: hidden;
}
.skeleton-card { display: grid; gap: 8px; }
.skeleton-poster,
.skeleton-line {
  display: block;
  border-radius: 8px;
  background: linear-gradient(100deg, var(--surface-2) 20%, color-mix(in srgb, var(--surface-2) 55%, var(--border)) 40%, var(--surface-2) 60%);
  background-size: 220% 100%;
  animation: discover-shimmer 1.4s ease-in-out infinite;
}
.skeleton-poster { aspect-ratio: 2 / 3; }
.skeleton-line { width: 90%; height: 12px; }
.skeleton-line.short { width: 55%; }
@keyframes discover-shimmer { to { background-position-x: -220%; } }
@media (prefers-reduced-motion: reduce) { .skeleton-poster, .skeleton-line { animation: none; } }
</style>
