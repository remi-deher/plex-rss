<template>
  <div class="media-rail-skeleton" aria-hidden="true">
    <div v-for="index in count" :key="index" class="skeleton-card">
      <span class="skeleton-poster" />
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
  grid-auto-columns: clamp(164px, 18vw, 220px);
  grid-auto-flow: column;
  gap: var(--space-4);
  overflow: hidden;
}
.skeleton-card { display: grid; gap: var(--space-2); }
.skeleton-poster {
  display: block;
  border-radius: var(--radius-sm);
  background: linear-gradient(100deg, var(--surface-2) 20%, color-mix(in srgb, var(--surface-2) 55%, var(--border)) 40%, var(--surface-2) 60%);
  background-size: 220% 100%;
  animation: discover-shimmer 1.4s ease-in-out infinite;
}
.skeleton-poster { aspect-ratio: 2 / 3; }
@keyframes discover-shimmer { to { background-position-x: -220%; } }
@media (max-width: 640px) { .media-rail-skeleton { grid-auto-columns: minmax(150px, 46vw); } }
@media (prefers-reduced-motion: reduce) { .skeleton-poster { animation: none; } }
</style>
