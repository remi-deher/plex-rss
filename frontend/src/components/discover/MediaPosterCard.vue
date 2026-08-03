<template>
  <article class="media-card discover-card discover-media-card">
    <div class="discover-poster-wrap">
      <RouterLink :to="to" :aria-label="accessibleLabel" class="discover-poster-link">
        <MediaPoster :poster-url="item.poster_url" :alt="`Affiche de ${title}`">
          <template #badges>
            <div class="discover-card-badges">
              <MediaStatusBadge :item="item" />
            </div>
          </template>
          <template #overlay>
            <div class="discover-card-overlay" :class="{ 'has-request-action': requestable }">
              <div class="discover-card-copy">
                <div class="discover-card-meta">
                  <span v-if="item.year">{{ item.year }}</span>
                  <span>{{ mediaTypeLabel(item.media_type) }}</span>
                  <span v-if="rating" class="discover-rating"><Star aria-hidden="true" />{{ rating }}</span>
                </div>
                <strong>{{ title }}</strong>
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
import { computed } from 'vue';
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
  border-radius: 12px;
  color: inherit;
}
.discover-media-card:hover,
.discover-media-card:focus-within {
  border-color: color-mix(in srgb, var(--accent) 65%, var(--border));
  box-shadow: 0 16px 34px rgba(0, 0, 0, .42);
  transform: translateY(-4px) scale(1.015);
}
.discover-poster-wrap { position: relative; aspect-ratio: 2 / 3; }
.discover-poster-link { display: block; height: 100%; color: inherit; text-decoration: none; }
.discover-poster-link :deep(.poster-shell) { height: 100%; }
.discover-poster-link :deep(.poster-shell > img),
.discover-poster-link :deep(.poster-fallback) { height: 100%; aspect-ratio: auto; }
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
}
.discover-card-overlay.has-request-action { padding-bottom: 52px; }
.discover-card-copy { display: grid; gap: 5px; width: 100%; min-width: 0; padding: 0 !important; }
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
.discover-card-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 5px 9px; padding: 0 !important; }
.discover-card-meta > span { color: rgba(255, 255, 255, .82); font-size: .72rem; font-weight: 650; }
.discover-rating { display: inline-flex !important; align-items: center; gap: 3px; }
.discover-rating svg { width: 12px; height: 12px; color: #fbbf24; fill: currentColor; }
.discover-card-link-action { margin-top: 2px; color: var(--accent) !important; font-size: .72rem; font-weight: 800; }
.discover-card-action {
  position: absolute;
  inset: auto 9px 9px;
  z-index: 3;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 34px;
  padding: 7px 10px;
  border-radius: 8px;
  background: var(--accent);
  color: #111;
  font-size: .78rem;
  font-weight: 800;
  text-align: center;
  box-shadow: 0 5px 16px rgba(0, 0, 0, .38);
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
  .discover-card-copy > strong { font-size: 1rem; }
}
</style>
