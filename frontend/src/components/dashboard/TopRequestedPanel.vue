<template>
  <PanelCard title="Demandes les plus populaires" :empty="items.length ? '' : 'Aucune demande multiple.'">
    <article v-for="item in items" :key="item.id" class="detail-row">
      <div class="inline-row gap-10">
        <img v-if="item.poster_url" :src="item.poster_url" class="mini-poster" alt="" loading="lazy" decoding="async" />
        <div v-else class="mini-poster"><Film style="width: 14px; height: 20px; margin: 8px 5px;" /></div>
        <div>
          <strong>{{ item.title }}</strong>
          <span>{{ mediaTypeLabel(item.media_type) }}</span>
        </div>
      </div>
      <span class="badge available">{{ item.count }} demandeurs</span>
    </article>
  </PanelCard>
</template>

<script setup>
import PanelCard from '@/components/ui/PanelCard.vue';
import { mediaTypeLabel } from '@/utils/labels';
import { Film } from '@lucide/vue';

defineProps({ items: { type: Array, default: () => [] } });
</script>
