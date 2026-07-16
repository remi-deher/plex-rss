<template>
  <article class="media-card request-card" :class="{list:view==='list'}">
    <div class="poster-shell" @click="router.push(mediaDetailPath(row,'request'))">
      <img v-if="row.poster_url" :src="proxyUrl(row.poster_url)" alt="" @error="$event.target.style.display='none'">
      <div v-else class="poster-fallback"><Film/></div>
      <span v-if="view==='grid'" class="badge status-tag" :class="row.status">{{ statusLabel(row.status) }}</span>
      <label v-if="isAdmin&&view==='grid'" class="select-tag" @click.stop>
        <input :checked="selected" type="checkbox" @change="$emit('toggle-select')">
      </label>
    </div>
    <div class="request-body">
      <div class="request-title-row">
        <button class="text-button" @click="router.push(mediaDetailPath(row,'request'))">
          <strong>{{ row.title }}</strong>
          <span v-if="row.year">{{ row.year }}</span>
        </button>
        <span v-if="view==='list'" class="badge status-tag" :class="row.status">{{ statusLabel(row.status) }}</span>
        <label v-if="isAdmin&&view==='list'" class="select-tag" @click.stop>
          <input :checked="selected" type="checkbox" @change="$emit('toggle-select')">
        </label>
      </div>
      <small>
        {{ row.media_type==='show'?'Serie':'Film' }}
        · {{ row.requested_by||row.plex_user||row.plex_user_id||'?' }}
        <template v-if="row.source"> · {{ row.source }}</template>
        · {{ formatDate(row.requested_at) }}
      </small>
      <div class="request-actions">
        <button v-if="row.status==='pending_approval'&&isAdmin" class="icon-button success" title="Approuver" @click="$emit('act',row,'approve')"><Check/></button>
        <button v-if="row.status==='pending_approval'&&isAdmin" class="icon-button danger" title="Refuser" @click="$emit('reject',row)"><Ban/></button>
        <button v-if="row.arr_id" class="icon-button" title="Rechercher une release" @click="router.push(`/releases/${row.id}`)"><Search/></button>
        <button v-if="row.status==='failed'&&isAdmin" class="icon-button" title="Relancer" @click="$emit('act',row,'retry')"><RotateCcw/></button>
        <button v-if="row.status!=='available'" class="icon-button danger" title="Annuler" @click="$emit('act',row,'cancel')"><X/></button>
      </div>
    </div>
  </article>
</template>

<script setup>
import { Ban, Check, Film, RotateCcw, Search, X } from '@lucide/vue';
import { useRouter } from 'vue-router';
import { mediaDetailPath } from '@/mediaUrl';
import { statusLabel, formatDate, proxyUrl } from './requestHelpers';

defineProps({
  row: { type: Object, required: true },
  view: { type: String, default: 'grid' },
  isAdmin: { type: Boolean, default: false },
  selected: { type: Boolean, default: false },
});
defineEmits(['toggle-select', 'act', 'reject']);

const router = useRouter();
</script>
