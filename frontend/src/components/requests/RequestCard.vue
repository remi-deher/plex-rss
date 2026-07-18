<template>
  <article class="media-card request-card" :class="{list:view==='list'}">
    <MediaPoster
      :poster-url="row.poster_url ? proxyUrl(row.poster_url) : null"
      @click="row.orphan ? openOrphan(row) : router.push(mediaDetailPath(row,'request'))"
    >
      <template #badges>
        <span v-if="view==='grid'" class="badge status-tag" :class="row.status">{{ statusLabel(row.status) }}</span>
        <label v-if="isAdmin&&view==='grid'&&!row.orphan" class="select-tag" @click.stop>
          <input :checked="selected" type="checkbox" @change="$emit('toggle-select')">
        </label>
      </template>
    </MediaPoster>
    <div class="request-body">
      <div class="request-title-row">
        <button v-if="!row.orphan" class="text-button" @click="router.push(mediaDetailPath(row,'request'))">
          <strong>{{ row.title }}</strong>
          <span v-if="row.year">{{ row.year }}</span>
        </button>
        <button v-else class="text-button" :disabled="opening" @click="openOrphan(row)">
          <strong>{{ row.title }}</strong>
          <span v-if="row.year">{{ row.year }}</span>
        </button>
        <span v-if="view==='list'" class="badge status-tag" :class="row.status">{{ statusLabel(row.status) }}</span>
        <label v-if="isAdmin&&view==='list'&&!row.orphan" class="select-tag" @click.stop>
          <input :checked="selected" type="checkbox" @change="$emit('toggle-select')">
        </label>
      </div>
      <small>
        {{ row.media_type==='show'?'Serie':'Film' }}
        <template v-if="row.orphan"> · <span class="badge">Suivi {{ row.orphan_source==='sonarr'?'Sonarr':'Radarr' }}</span></template>
        <template v-else>
          · {{ row.requested_by||row.plex_user||row.plex_user_id||'?' }}
          <template v-if="row.source"> · {{ row.source }}</template>
          · {{ formatDate(row.requested_at) }}
        </template>
      </small>
      <div class="request-actions">
        <template v-if="row.orphan">
          <button v-if="isAdmin" class="icon-button danger" title="Supprimer de Sonarr/Radarr" @click="$emit('delete-orphan',row)"><Trash2/></button>
        </template>
        <template v-else>
          <button v-if="row.status==='pending_approval'&&isAdmin" class="icon-button success" title="Approuver" @click="$emit('act',row,'approve')"><Check/></button>
          <button v-if="row.status==='pending_approval'&&isAdmin" class="icon-button danger" title="Refuser" @click="$emit('reject',row)"><Ban/></button>
          <button v-if="row.arr_id" class="icon-button" title="Rechercher une release" @click="router.push(`/releases/${row.id}`)"><Search/></button>
          <button v-if="row.status==='failed'&&isAdmin" class="icon-button" title="Relancer" @click="$emit('act',row,'retry')"><RotateCcw/></button>
          <button v-if="row.status!=='available'" class="icon-button danger" title="Annuler" @click="$emit('act',row,'cancel')"><X/></button>
        </template>
      </div>
    </div>
  </article>
</template>

<script setup>
import { ref } from 'vue';
import { Ban, Check, RotateCcw, Search, Trash2, X } from '@lucide/vue';
import { useRouter } from 'vue-router';
import { api } from '@/api';
import { mediaDetailPath } from '@/mediaUrl';
import MediaPoster from '@/components/media/MediaPoster.vue';
import { statusLabel, formatDate, proxyUrl } from './requestHelpers';

defineProps({
  row: { type: Object, required: true },
  view: { type: String, default: 'grid' },
  isAdmin: { type: Boolean, default: false },
  selected: { type: Boolean, default: false },
});
defineEmits(['toggle-select', 'act', 'reject', 'delete-orphan']);

const router = useRouter();
const opening = ref(false);

// Un item "Suivi Sonarr/Radarr" n'a pas de LibraryItem tant que personne n'a ouvert
// sa fiche -- on le materialise a la demande (voir POST .../orphans/.../open) plutot
// que d'en creer un pour chaque orphelin liste, jamais consulte.
async function openOrphan(row) {
  if (opening.value) return;
  opening.value = true;
  try {
    const { library_item_id } = await api(
      `/api/requests/orphans/${row.orphan_source}/${row.arr_instance_id}/${row.arr_id}/open`,
      { method: 'POST' },
    );
    router.push(mediaDetailPath({ library_id: library_item_id }, 'library'));
  } catch (e) {
    alert(e.message || "Impossible d'ouvrir la fiche detaillee");
  } finally {
    opening.value = false;
  }
}
</script>
