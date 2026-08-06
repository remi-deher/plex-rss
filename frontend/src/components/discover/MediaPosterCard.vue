<template>
  <article class="media-card discover-card discover-media-card">
    <div
      class="discover-poster-wrap"
      :class="{ revealed }"
      @mouseenter="revealed = true"
      @mouseleave="revealed = false"
      @focusin="revealed = true"
      @focusout="revealed = false"
    >
      <RouterLink :to="to" :aria-label="accessibleLabel" class="discover-poster-link" @click="handleLinkClick">
        <MediaPoster :poster-url="item.poster_url" :alt="`Affiche de ${title}`">
          <template #badges>
            <div class="discover-card-badges">
              <MediaStatusBadge :item="item" />
            </div>
          </template>
          <template #overlay>
            <div class="discover-card-overlay">
              <div class="discover-card-copy">
                <div class="discover-card-meta">
                  <span v-if="item.year">{{ item.year }}</span>
                  <span>{{ mediaTypeLabel(item.media_type) }}</span>
                  <span v-if="rating" class="discover-rating"><Star aria-hidden="true" />{{ rating }}</span>
                </div>
                <strong v-if="!requestable">{{ title }}</strong>
                <span v-if="actionLabel && !requestable" class="discover-card-link-action">{{ actionLabel }}</span>
              </div>
            </div>
          </template>
        </MediaPoster>
      </RouterLink>
      <button
        v-if="requestable"
        type="button"
        class="discover-card-action request-action"
        :disabled="requestBusy"
        :aria-label="`Demander ${title}`"
        @click="$emit('request', item)"
      >
        <Download aria-hidden="true" />{{ requestBusy ? 'Envoi…' : 'Demander' }}
      </button>
    </div>
  </article>
</template>

<script setup>
import { computed, ref } from 'vue';
import { Download, Star } from '@lucide/vue';
import MediaPoster from '@/components/media/MediaPoster.vue';
import { mediaTypeLabel } from '@/utils/labels';
import MediaStatusBadge from './MediaStatusBadge.vue';

const props = defineProps({
  item: { type: Object, required: true },
  to: { type: [String, Object], required: true },
  actionLabel: { type: String, default: '' },
  requestable: { type: Boolean, default: false },
  requestBusy: { type: Boolean, default: false },
});
defineEmits(['request']);

/**
 * Bandeau (titre/meta/action) masqué au repos, révélé au survol/focus (souris/clavier) ou
 * au premier tap tactile — `revealed` sert de filet JS pour le tactile (pas de :hover réel),
 * le CSS :hover/:focus-within couvre nativement souris et clavier.
 */
const revealed = ref(false);

function handleLinkClick(e) {
  if (!revealed.value) {
    e.preventDefault();
    revealed.value = true;
  }
}

const title = computed(() => props.item.title || props.item.name || 'Sans titre');
const rating = computed(() => {
  const value = Number(props.item.vote_average || props.item.vote || 0);
  return value > 0 ? value.toFixed(1) : '';
});
const accessibleLabel = computed(() => [
  title.value,
  mediaTypeLabel(props.item.media_type),
  props.item.year,
].filter(Boolean).join(', '));
</script>

<style scoped>
.discover-media-card {
  position: relative;
  min-width: 0;
  aspect-ratio: 2 / 3;
  padding: 0;
  overflow: hidden;
  border-radius: var(--radius-md);
  background: var(--surface-2);
  color: inherit;
}
.discover-media-card:hover,
.discover-media-card:focus-within {
  border-color: color-mix(in srgb, var(--accent) 65%, var(--border));
  box-shadow: 0 16px 34px rgba(0, 0, 0, .42);
  transform: translateY(-4px) scale(1.015);
}
.discover-poster-wrap { position: relative; width: 100%; height: 100%; padding: 0 !important; }
.discover-poster-link { display: block; height: 100%; color: inherit; text-decoration: none; }
.discover-poster-link :deep(.poster-shell) { width: 100%; height: 100%; padding: 0; overflow: hidden; }
.discover-poster-link :deep(.poster-shell > img),
.discover-poster-link :deep(.poster-fallback) { display: block; width: 100%; height: 100%; padding: 0; aspect-ratio: auto; object-fit: cover; }
.discover-poster-link :deep(.poster-fallback) { display: grid; }
.discover-card-badges {
  position: absolute;
  top: 7px;
  left: 7px;
  right: 7px;
  display: flex;
  padding: 0;
  pointer-events: none;
}
.discover-card-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: flex-end;
  padding: 70px 12px 12px;
  background: linear-gradient(180deg, transparent 20%, rgba(8, 10, 14, .18) 43%, rgba(8, 10, 14, .96) 100%);
  color: #fff;
  opacity: 0;
  pointer-events: none;
  transition: opacity .18s ease;
}
.discover-poster-wrap:hover .discover-card-overlay,
.discover-poster-wrap:focus-within .discover-card-overlay,
.discover-poster-wrap.revealed .discover-card-overlay {
  opacity: 1;
  pointer-events: auto;
}
.discover-card-copy { display: grid; gap: var(--space-1); width: 100%; min-width: 0; padding: 0 !important; }
.discover-card-copy > strong {
  display: -webkit-box;
  overflow: hidden;
  color: #fff;
  font-size: clamp(1rem, 1.25vw, 1.25rem);
  font-weight: 800;
  line-height: 1.12;
  text-shadow: 0 2px 8px rgba(0, 0, 0, .9);
  word-break: break-word;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}
.discover-card-meta { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1) var(--space-2); padding: 0 !important; }
.discover-card-meta > span { color: rgba(255, 255, 255, .82); font-size: var(--fs-xs); font-weight: 650; }
.discover-rating { display: inline-flex !important; align-items: center; gap: var(--space-1); }
.discover-rating svg { width: 12px; height: 12px; color: #fbbf24; fill: currentColor; }
.discover-card-link-action { margin-top: 2px; color: var(--text) !important; font-size: var(--fs-xs); font-weight: 800; }
.discover-card-action {
  position: absolute;
  inset: auto 9px 9px;
  z-index: 3;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-height: 34px;
  padding: 7px 10px;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: #111;
  font-size: var(--fs-sm);
  font-weight: 800;
  text-align: center;
  box-shadow: 0 5px 16px rgba(0, 0, 0, .38);
  opacity: 0;
  pointer-events: none;
  transition: opacity .18s ease;
}
.discover-poster-wrap:hover .discover-card-action,
.discover-poster-wrap:focus-within .discover-card-action,
.discover-poster-wrap.revealed .discover-card-action {
  opacity: 1;
  pointer-events: auto;
}
.discover-card-action svg { width: 15px; height: 15px; }
.request-action {
  width: calc(100% - 18px);
  border: 1px solid color-mix(in srgb, var(--accent) 75%, #fff);
  cursor: pointer;
}
@media (max-width: 640px) {
  .discover-media-card:hover,
  .discover-media-card:focus-within { transform: translateY(-2px); }
  .discover-card-overlay { padding-inline: 10px; }
  .discover-card-copy > strong { font-size: var(--fs-base); }
}
</style>
