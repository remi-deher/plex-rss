<template>
  <div class="media-card interactive" :class="{list:view==='list'}" role="button" tabindex="0" @click="$emit('open',item)" @keydown.enter="$emit('open',item)">
    <div class="poster-shell">
      <img v-if="item.poster_url" :src="item.poster_url" alt="" @error="$event.target.style.display='none'">
      <div v-else class="poster-fallback">
        <Film/>
      </div>
      <span class="language-tag" :class="item.has_vf===true?'vf':item.has_vf===false?'vo':'unknown'">{{ item.has_vf===true?'VF':item.has_vf===false?'VO':'?' }}</span>
    </div>
    <div>
      <strong>{{ item.title }}</strong>
      <span>{{ item.media_type==='show'?'Serie':'Film' }}<template v-if="item.year"> · {{ item.year }}</template></span>
      <span v-if="item.custom_name || item.requested_by || item.plex_user || item.plex_user_id" style="font-size: 0.85em; opacity: 0.8; margin-top: 2px;">
        👤 {{ item.custom_name || item.requested_by || item.plex_user || item.plex_user_id }}
      </span>
      <small v-if="item._kind==='request'">
        {{ requestLabel(item.status) }}<template v-if="item.overview"> — {{ item.overview }}</template>
        <button class="manage-link" @click.stop="$emit('go-to-request',item)">Gerer la demande <ArrowRight/></button>
      </small>
      <small v-else-if="item.overview">{{ item.overview }}</small>
    </div>
  </div>
</template>

<script setup>
import { ArrowRight, Film } from '@lucide/vue';

defineProps({
  item: { type: Object, required: true },
  view: { type: String, default: 'grid' },
});
defineEmits(['open', 'go-to-request']);

function requestLabel(s) {
  return ({
    pending_approval: 'A approuver',
    pending: 'En attente',
    sent_to_arr: 'Transmise a Sonarr/Radarr',
    partially_available: 'Partiellement disponible',
    failed: 'Echec',
  })[s] || s;
}
</script>

<style scoped>
.manage-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 4px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--accent);
  font-size: 0.85rem;
  cursor: pointer;
}
.manage-link:hover {
  text-decoration: underline;
}
.manage-link svg {
  width: 14px;
  height: 14px;
}
</style>
