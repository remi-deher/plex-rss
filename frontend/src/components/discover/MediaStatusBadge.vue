<template>
  <span v-if="status" class="discover-status-badge" :class="status.variant">
    {{ status.label }}
  </span>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  item: { type: Object, required: true },
});

const status = computed(() => {
  const item = props.item;
  if (item.in_library || item.library_id) return { label: 'Dans Plex', variant: 'in-plex' };
  if (item.request_status === 'partially_available') {
    return { label: 'Partiellement disponible', variant: 'partial' };
  }
  if (item.is_downloading) return { label: 'En téléchargement', variant: 'downloading' };
  if (item.requested || item.request_id) return { label: 'Demandé', variant: 'requested' };
  return null;
});
</script>

<style scoped>
.discover-status-badge {
  display: inline-flex;
  align-items: center;
  max-width: calc(100% - 14px);
  min-height: 24px;
  padding: 3px 9px;
  overflow: hidden;
  border-radius: var(--radius-sm);
  box-shadow: 0 1px 5px rgba(0, 0, 0, .55);
  color: #fff;
  background: rgba(39, 39, 42, .94);
  font-size: var(--fs-sm);
  font-weight: 800;
  line-height: 1.2;
  text-overflow: ellipsis;
  text-shadow: 0 1px 1px rgba(0, 0, 0, .55);
  white-space: nowrap;
}
.in-plex { background: rgba(22, 101, 52, .96); }
.partial { color: #1a1200; background: rgba(245, 179, 26, .97); }
.downloading { background: rgba(3, 105, 161, .96); }
.requested { background: rgba(63, 63, 70, .96); }
</style>
