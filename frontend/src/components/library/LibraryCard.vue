<template>
  <div class="media-card interactive" :class="{list:view==='list'}" role="button" tabindex="0" @click="handleOpen" @keydown.enter="handleOpen">
    <MediaPoster :poster-url="item.poster_url">
      <template #badges>
        <span v-if="item._kind==='library'" class="language-tag" :class="item.has_vf===true?'vf':item.has_vf===false?'vo':'unknown'">{{ item.has_vf===true?'VF':item.has_vf===false?'VO':'?' }}</span>
        <span v-else class="badge status-tag" :class="item.status">{{ statusLabel(item.status) }}</span>
        <label v-if="isAdmin && item._kind==='request' && !item.orphan" class="select-tag" @click.stop>
          <input :checked="selected" type="checkbox" @change="$emit('toggle-select', item.id)">
        </label>
      </template>
      <template #overlay>
        <div v-if="view==='grid' && (requesterLabel(item) || item.overview)" class="poster-overlay">
          <span v-if="requesterLabel(item)" class="poster-requester">👤 {{ requesterLabel(item) }}</span>
          <p v-if="item.overview" class="poster-overview">{{ item.overview }}</p>
        </div>
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
        <span v-if="requesterLabel(item)" style="font-size: 0.85em; opacity: 0.8; margin-top: 2px;">👤 {{ requesterLabel(item) }}</span>
        <small v-if="item._kind==='library' && item.overview">{{ item.overview }}</small>
      </template>
      <div v-if="item._kind==='request'" class="card-actions" @click.stop>
        <template v-if="item.orphan">
          <button v-if="isAdmin" class="icon-button danger" title="Supprimer de Sonarr/Radarr" @click="$emit('delete-orphan',item)"><Trash2/></button>
        </template>
        <template v-else>
          <button v-if="item.arr_id" class="icon-button" title="Rechercher une release" @click="router.push(`/releases/${item.id}`)"><Search/></button>
          <button v-if="item.status==='failed' && isAdmin" class="icon-button" title="Relancer" @click="$emit('act',item,'retry')"><RotateCcw/></button>
          <button v-if="item.status!=='available'" class="icon-button danger" title="Annuler" @click="$emit('act',item,'cancel')"><X/></button>
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
const emit = defineEmits(['open', 'toggle-select', 'act', 'delete-orphan']);

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
    alert(e.message || "Impossible d'ouvrir la fiche detaillee");
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
  background: rgba(20, 20, 20, .9);
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

/* Resume + demandeur affiches directement sur l'affiche (au lieu du bloc texte sous
   la carte) : libere de la hauteur pour que la grille reste compacte et reguliere
   quel que soit le nombre de lignes de resume. Police distincte (serif) pour
   detacher visuellement ce texte "editorial" du reste de l'UI (Outfit, sans-serif).
   Le fond doit rester quasi opaque sur TOUTE la hauteur du bloc (pas juste en bas) :
   comme ce bloc est deja limite a la hauteur de son propre texte, un degrade qui va
   jusqu'a transparent a 100% rendait la 1ere ligne illisible sur une affiche claire --
   seul le tout dernier bord (vers l'image) doit s'estomper. */
.poster-overlay {
  position: absolute;
  inset: auto 0 0 0;
  padding: 10px 8px 9px;
  background: linear-gradient(to top, rgba(0, 0, 0, .92) 80%, rgba(0, 0, 0, 0) 100%);
  backdrop-filter: blur(3px);
  -webkit-backdrop-filter: blur(3px);
  font-family: Georgia, "Times New Roman", Times, serif;
  color: #fff;
  pointer-events: none;
}

.poster-requester {
  display: block;
  overflow: hidden;
  margin-bottom: 4px;
  font-size: 0.76rem;
  font-weight: 700;
  white-space: nowrap;
  text-overflow: ellipsis;
  text-shadow: 0 1px 3px rgba(0, 0, 0, .95), 0 0 1px rgba(0, 0, 0, .95);
}

.poster-overview {
  display: -webkit-box;
  overflow: hidden;
  margin: 0;
  font-size: 0.84rem;
  line-height: 1.38;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  text-shadow: 0 1px 3px rgba(0, 0, 0, .95), 0 0 1px rgba(0, 0, 0, .95);
}
</style>
