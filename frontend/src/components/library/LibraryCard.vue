<template>
  <div class="media-card interactive" :class="{list:view==='list'}" role="button" tabindex="0" @click="handleOpen" @keydown.enter="handleOpen">
    <MediaPoster :poster-url="item.poster_url">
      <template #badges>
        <span v-if="item._kind==='library'" class="language-tag" :class="item.has_vf===true?'vf':item.has_vf===false?'vo':'unknown'">{{ item.has_vf===true?'VF':item.has_vf===false?'VO':'?' }}</span>
        <span v-else class="badge status-tag" :class="item.status">{{ statusLabel(item.status) }}</span>
        <span v-if="requesterLabel(item)" class="requester-tag">👤 {{ requesterLabel(item) }}</span>
        <label v-if="isAdmin && item._kind==='request' && !item.orphan" class="select-tag" @click.stop>
          <input :checked="selected" type="checkbox" @change="$emit('toggle-select', item.id)">
        </label>
      </template>
    </MediaPoster>
    <div class="card-body">
      <strong>{{ item.title }}</strong>
      <span>
        {{ item.media_type==='show'?'Serie':'Film' }}<template v-if="item.year"> · {{ item.year }}</template>
        <template v-if="item.orphan"> · Suivi {{ item.orphan_source==='sonarr'?'Sonarr':'Radarr' }}</template>
        <template v-else-if="item._kind==='request' && item.source"> · {{ item.source }}</template>
      </span>
      <template v-if="view==='list'">
        <span v-if="requesterLabel(item)" class="requester-tag inline" style="margin-top: 4px;">👤 {{ requesterLabel(item) }}</span>
      </template>
      <div v-if="item._kind==='request'" class="card-actions" @click.stop>
        <template v-if="item.orphan">
          <button v-if="isAdmin" class="icon-button danger" title="Supprimer de Sonarr/Radarr" aria-label="Supprimer de Sonarr/Radarr" @click="$emit('delete-orphan',item)"><Trash2/></button>
        </template>
        <template v-else>
          <button v-if="item.arr_id" class="icon-button" title="Rechercher une release" aria-label="Rechercher une release" @click="router.push(`/releases/${item.id}`)"><Search/></button>
          <button v-if="item.status==='failed' && isAdmin" class="icon-button" title="Relancer" aria-label="Relancer" @click="$emit('act',item,'retry')"><RotateCcw/></button>
          <button v-if="item.status!=='available'" class="icon-button danger" title="Annuler" aria-label="Annuler" @click="$emit('act',item,'cancel')"><X/></button>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import { RotateCcw, Search, Trash2, X } from '@lucide/vue';
import { useRouter } from 'vue-router';
import { api } from '@/api';
import { mediaDetailPath } from '@/mediaUrl';
import MediaPoster from '@/components/media/MediaPoster.vue';
import { statusLabel } from '@/components/media/mediaListHelpers';

const props = defineProps({
  item: { type: Object, required: true },
  view: { type: String, default: 'grid' },
  isAdmin: { type: Boolean, default: false },
  selected: { type: Boolean, default: false },
});
const emit = defineEmits(['open', 'toggle-select', 'act', 'delete-orphan', 'error']);

const router = useRouter();
const opening = ref(false);

// Un item "Suivi Sonarr/Radarr" n'a pas de MediaRequest ni de LibraryItem tant que
// personne n'a ouvert sa fiche -- on le materialise a la demande (voir POST
// .../orphans/.../open) plutot que d'en creer un pour chaque orphelin liste, jamais
// consulte. Les autres items (demandes/bibliotheque) ouvrent leur fiche directement.
async function handleOpen() {
  if (!props.item.orphan) {
    emit('open', props.item);
    return;
  }
  if (opening.value) return;
  opening.value = true;
  try {
    const { library_item_id } = await api(
      `/api/requests/orphans/${props.item.orphan_source}/${props.item.arr_instance_id}/${props.item.arr_id}/open`,
      { method: 'POST' },
    );
    router.push(mediaDetailPath({ library_id: library_item_id }, 'library'));
  } catch (e) {
    emit('error', e.message || "Impossible d'ouvrir la fiche detaillee");
  } finally {
    opening.value = false;
  }
}

function requesterLabel(item) {
  return item.custom_name || item.requested_by || item.plex_user || item.plex_user_id || '';
}
</script>

<style scoped>
.card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}
.media-card.list .card-actions {
  margin-top: 4px;
}

.poster-shell .status-tag {
  position: absolute;
  top: 8px;
  left: 8px;
}
.poster-shell .select-tag {
  position: absolute;
  top: 8px;
  right: 8px;
  padding: 4px;
  border-radius: 6px;
  background: rgba(20, 20, 20, .9);
}
.select-tag {
  display: flex;
  flex-shrink: 0;
  cursor: pointer;
}

/* Demandeur sous forme de badge (fond plein) plutot qu'en texte sur overlay -- coherent
   avec les badges statut/VF deja pleins (voir views.css), et plus lisible qu'un texte
   sur degrade. Couleur distincte (bleu) pour ne pas se confondre avec le sens
   statut/langue des autres badges (vert/rouge/ambre). */
.requester-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  padding: 3px 9px;
  overflow: hidden;
  border-radius: 999px;
  color: #fff;
  background: rgba(37, 99, 235, .92);
  font-size: 0.78rem;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.poster-shell .requester-tag {
  position: absolute;
  bottom: 8px;
  left: 8px;
  max-width: calc(100% - 16px);
  box-shadow: 0 1px 4px rgba(0, 0, 0, .5);
}
</style>
