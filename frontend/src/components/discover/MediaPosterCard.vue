<template>
  <RouterLink
    class="media-card discover-card discover-media-card"
    :to="to"
    :aria-label="accessibleLabel"
  >
    <MediaPoster :poster-url="item.poster_url" :alt="`Affiche de ${title}`">
      <template #badges>
        <div class="discover-card-badges">
          <MediaStatusBadge :item="item" />
        </div>
      </template>
      <template v-if="actionLabel" #overlay>
        <div class="discover-card-action">{{ actionLabel }}</div>
      </template>
    </MediaPoster>
    <div class="discover-card-info">
      <strong>{{ title }}</strong>
      <span>
        {{ mediaTypeLabel(item.media_type) }}
        <template v-if="item.year"> · {{ item.year }}</template>
        <template v-if="rating"> · <Star aria-hidden="true" />{{ rating }}</template>
      </span>
    </div>
  </RouterLink>
</template>

<script setup>
import { computed } from 'vue';
import { Star } from '@lucide/vue';
import MediaPoster from '@/components/media/MediaPoster.vue';
import { mediaTypeLabel } from '@/utils/labels';
import MediaStatusBadge from './MediaStatusBadge.vue';

const props = defineProps({
  item: { type: Object, required: true },
  to: { type: [String, Object], required: true },
  actionLabel: { type: String, default: '' },
});

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
  min-width: 0;
  color: inherit;
  cursor: pointer;
  text-decoration: none;
}
.discover-card-badges {
  position: absolute;
  top: 7px;
  left: 7px;
  right: 7px;
  display: flex;
  pointer-events: none;
}
.discover-card-action {
  position: absolute;
  inset: auto 7px 7px;
  padding: 7px;
  border-radius: 7px;
  background: rgba(10, 10, 10, .84);
  color: #fff;
  font-size: .72rem;
  font-weight: 700;
  text-align: center;
  opacity: 0;
  transform: translateY(5px);
  transition: opacity .2s, transform .2s;
}
.discover-media-card:hover .discover-card-action,
.discover-media-card:focus-visible .discover-card-action {
  opacity: 1;
  transform: none;
}
.discover-card-info {
  display: grid;
  gap: 4px;
}
.discover-card-info strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.discover-card-info > span {
  display: flex;
  align-items: center;
  color: var(--muted);
  font-size: .72rem;
}
.discover-card-info svg {
  width: 12px;
  height: 12px;
  margin-left: 3px;
  color: var(--accent);
}
@media (max-width: 640px) {
  .discover-card-action {
    position: static;
    margin-top: 6px;
    opacity: 1;
    transform: none;
  }
}
</style>
