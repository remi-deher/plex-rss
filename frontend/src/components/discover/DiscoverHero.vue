<template>
  <section
    v-if="activeItem"
    class="discover-hero"
    :style="backdropStyle"
    @mouseenter="pauseAutoplay"
    @mouseleave="resumeAutoplay"
    @focusin="pauseAutoplay"
    @focusout="resumeAutoplay"
  >
    <div class="discover-hero-shade" />
    <Transition name="hero-fade" mode="out-in">
      <div class="discover-hero-content" :key="activeItem.tmdb_id ?? activeIndex">
        <span class="eyebrow">À la une</span>
        <h1>{{ activeItem.title || activeItem.name }}</h1>
        <p v-if="activeItem.overview">{{ activeItem.overview }}</p>
        <div class="discover-hero-meta">
          <MediaStatusBadge :item="activeItem" />
          <span v-if="activeItem.year">{{ activeItem.year }}</span>
          <span v-if="activeItem.vote">★ {{ Number(activeItem.vote).toFixed(1) }}</span>
        </div>
        <RouterLink class="primary" :to="itemPath">Voir la fiche</RouterLink>
      </div>
    </Transition>
    <div v-if="items.length > 1" class="discover-hero-dots" role="tablist" aria-label="Sélection à la une">
      <button
        v-for="(_, i) in items"
        :key="i"
        type="button"
        role="tab"
        class="discover-hero-dot"
        :class="{ active: i === activeIndex }"
        :aria-selected="i === activeIndex"
        :aria-label="`Voir la sélection ${i + 1}`"
        @click="goTo(i)"
      />
    </div>
  </section>
  <div v-else-if="loading" class="discover-hero hero-loading" aria-label="Chargement de la sélection" />
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { mediaDetailPath } from '@/mediaUrl';
import MediaStatusBadge from './MediaStatusBadge.vue';

const props = defineProps({
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
});

const AUTOPLAY_MS = 7000;

const activeIndex = ref(0);
const activeItem = computed(() => props.items[activeIndex.value] || null);

const backdropStyle = computed(() => activeItem.value?.backdrop_url
  ? { backgroundImage: `url("${activeItem.value.backdrop_url}")` }
  : {});
const itemPath = computed(() => {
  if (!activeItem.value) return '/discover';
  const kind = activeItem.value.library_id ? 'library' : activeItem.value.request_id ? 'request' : 'discover';
  return mediaDetailPath(activeItem.value, kind, { discover: true });
});

let timer = null;
const reducedMotion = typeof window !== 'undefined' && window.matchMedia
  ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
  : false;

function startAutoplay() {
  if (reducedMotion || props.items.length <= 1) return;
  stopAutoplay();
  timer = setInterval(() => {
    activeIndex.value = (activeIndex.value + 1) % props.items.length;
  }, AUTOPLAY_MS);
}
function stopAutoplay() {
  if (timer) { clearInterval(timer); timer = null; }
}
function pauseAutoplay() { stopAutoplay(); }
function resumeAutoplay() { startAutoplay(); }
function goTo(i) {
  activeIndex.value = i;
  startAutoplay();
}

watch(() => props.items, (next) => {
  if (activeIndex.value >= next.length) activeIndex.value = 0;
  startAutoplay();
});

onMounted(startAutoplay);
onUnmounted(stopAutoplay);
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
.hero-fade-enter-active, .hero-fade-leave-active { transition: opacity .3s ease; }
.hero-fade-enter-from, .hero-fade-leave-to { opacity: 0; }
@media (prefers-reduced-motion: reduce) {
  .hero-fade-enter-active, .hero-fade-leave-active { transition: none; }
}
.discover-hero-dots {
  position: relative;
  z-index: 1;
  display: flex;
  gap: var(--space-2);
  padding: 0 clamp(22px, 5vw, 54px) clamp(16px, 3vw, 28px);
  margin-left: auto;
}
.discover-hero-dot {
  width: 9px;
  height: 9px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: rgba(255, 255, 255, .35);
  cursor: pointer;
  transition: background-color .2s ease, width .2s ease;
}
.discover-hero-dot:hover { background: rgba(255, 255, 255, .6); }
.discover-hero-dot.active { width: 22px; border-radius: var(--radius-pill); background: var(--accent); }
.hero-loading { background: linear-gradient(100deg, var(--surface-2) 20%, color-mix(in srgb, var(--surface-2) 55%, var(--border)) 40%, var(--surface-2) 60%); background-size: 220% 100%; animation: hero-shimmer 1.4s infinite; }
@keyframes hero-shimmer { to { background-position-x: -220%; } }
@media (prefers-reduced-motion: reduce) { .hero-loading { animation: none; } }
</style>
