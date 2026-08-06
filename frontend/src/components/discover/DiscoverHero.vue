<template>
  <section v-if="item" class="discover-hero" :style="backdropStyle">
    <div class="discover-hero-shade" />
    <div class="discover-hero-content">
      <span class="eyebrow">À la une</span>
      <h1>{{ item.title || item.name }}</h1>
      <p v-if="item.overview">{{ item.overview }}</p>
      <div class="discover-hero-meta">
        <MediaStatusBadge :item="item" />
        <span v-if="item.year">{{ item.year }}</span>
        <span v-if="item.vote">★ {{ Number(item.vote).toFixed(1) }}</span>
      </div>
      <RouterLink class="primary" :to="itemPath">Voir la fiche</RouterLink>
    </div>
  </section>
  <div v-else-if="loading" class="discover-hero hero-loading" aria-label="Chargement de la sélection" />
</template>

<script setup>
import { computed } from 'vue';
import { mediaDetailPath } from '@/mediaUrl';
import MediaStatusBadge from './MediaStatusBadge.vue';

const props = defineProps({
  item: { type: Object, default: null },
  loading: { type: Boolean, default: false },
});

const backdropStyle = computed(() => props.item?.backdrop_url
  ? { backgroundImage: `url("${props.item.backdrop_url}")` }
  : {});
const itemPath = computed(() => {
  if (!props.item) return '/discover';
  const kind = props.item.library_id ? 'library' : props.item.request_id ? 'request' : 'discover';
  return mediaDetailPath(props.item, kind, { discover: true });
});
</script>

<style scoped>
.discover-hero {
  position: relative;
  display: flex;
  align-items: end;
  min-height: clamp(330px, 48vw, 520px);
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background-color: var(--surface-2);
  background-position: center;
  background-size: cover;
}
.discover-hero-shade { position: absolute; inset: 0; background: linear-gradient(90deg, rgba(5, 7, 12, .96), rgba(5, 7, 12, .48) 60%, rgba(5, 7, 12, .12)), linear-gradient(0deg, rgba(5, 7, 12, .9), transparent 60%); }
.discover-hero-content { position: relative; display: grid; gap: var(--space-3); width: min(620px, 88%); padding: clamp(22px, 5vw, 54px); color: #fff; }
.discover-hero h1 { margin: 0; font-size: clamp(2rem, 5vw, 4rem); line-height: 1; }
.discover-hero p { display: -webkit-box; margin: 0; overflow: hidden; color: rgba(255, 255, 255, .82); line-height: 1.55; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }
.discover-hero-meta { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); font-size: var(--fs-sm); }
.discover-hero .primary { justify-self: start; text-decoration: none; }
.hero-loading { background: linear-gradient(100deg, var(--surface-2) 20%, color-mix(in srgb, var(--surface-2) 55%, var(--border)) 40%, var(--surface-2) 60%); background-size: 220% 100%; animation: hero-shimmer 1.4s infinite; }
@keyframes hero-shimmer { to { background-position-x: -220%; } }
@media (prefers-reduced-motion: reduce) { .hero-loading { animation: none; } }
</style>
