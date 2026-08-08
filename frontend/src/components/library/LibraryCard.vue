<template>
  <div class="media-card interactive" :class="{ list: view === 'list', 'is-music': isMusic }" role="link" tabindex="0" :aria-label="`Ouvrir la fiche de ${item.title}`" @click="handleOpen" @keydown.enter.prevent="handleOpen" @keydown.space.prevent="handleOpen">
    <MediaPoster :poster-url="item.poster_url" :is-music="isMusic">
      <template #badges>
        <!-- En vue liste, l'affiche n'est qu'une vignette de 64 px : y epingler un badge
             texte le tronque forcement (« Partiellement disponible » demande ~152 px).
             Les badges passent alors dans le corps de la carte, ci-dessous. La case a
             cocher, elle, tient dans tous les cas. -->
        <template v-if="view!=='list'">
          <span v-for="badge in badges" :key="badge.key" :class="badge.cls">{{ badge.label }}</span>
        </template>
        <label v-if="canModerate && item._kind==='request' && !item.orphan" class="select-tag" @click.stop>
          <input :checked="selected" :disabled="busy" type="checkbox" :aria-label="`Sélectionner ${item.title}`" @change="$emit('toggle-select', item.id)">
        </label>
      </template>
    </MediaPoster>
    <div class="card-body">
      <strong>{{ item.title }}</strong>
      <span>
        {{ mediaTypeLabel(item.media_type) }}<template v-if="item.year"> · {{ item.year }}</template>
        <template v-if="item.orphan"> · Suivi {{ item.orphan_source==='sonarr'?'Sonarr':'Radarr' }}</template>
        <template v-else-if="item._kind==='request' && item.source"> · {{ item.source }}</template>
      </span>
      <div v-if="view==='list'" class="badge-row card-badges">
        <span v-for="badge in badges" :key="badge.key" :class="badge.cls">{{ badge.label }}</span>
      </div>
      <div v-if="item._kind==='request'" class="card-actions" @click.stop>
        <template v-if="item.orphan">
          <button v-if="canModerate" class="icon-button danger" :disabled="busy" title="Supprimer de Sonarr/Radarr" aria-label="Supprimer de Sonarr/Radarr" @click="$emit('delete-orphan',item)"><Trash2/></button>
        </template>
        <template v-else>
          <button v-if="item.arr_id" class="icon-button" :disabled="busy" title="Rechercher une release" aria-label="Rechercher une release" @click="router.push(`/releases/${item.id}`)"><Search/></button>
          <button v-if="item.status==='failed' && canModerate" class="icon-button" :disabled="busy" title="Relancer" aria-label="Relancer" @click="$emit('act',item,'retry')"><RotateCcw/></button>
          <button v-if="item.status!=='available'" class="icon-button danger" :disabled="busy" title="Annuler" aria-label="Annuler" @click="$emit('act',item,'cancel')"><X/></button>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue';
import { RotateCcw, Search, Trash2, X } from '@lucide/vue';
import { useRouter } from 'vue-router';
import { api } from '@/api';
import { mediaDetailPath } from '@/mediaUrl';
import { mediaTypeLabel } from '@/utils/labels';
import MediaPoster from '@/components/media/MediaPoster.vue';
import { statusLabel, statusShortLabel } from '@/components/media/mediaListHelpers';

const props = defineProps({
  item: { type: Object, required: true },
  view: { type: String, default: 'grid' },
  canModerate: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
  selected: { type: Boolean, default: false },
});
const emit = defineEmits(['open', 'toggle-select', 'act', 'delete-orphan', 'error']);

const router = useRouter();
const opening = ref(false);

const isMusic = computed(() => props.item.media_type === 'artist' || props.item.media_type === 'album');

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

/**
 * Badges de la carte, definis une seule fois : la vue grille les superpose a l'affiche,
 * la vue liste les affiche dans le corps. Le demandeur etait auparavant rendu deux fois
 * en vue liste (une version epinglee sur la vignette *et* une version en ligne).
 */
const badges = computed(() => {
  const item = props.item;
  const list = [];
  if (isMusic.value) {
    const label = item.media_type === 'artist' ? '🎤 Artiste' : item.media_type === 'album' ? '💿 Album' : '🎵 Musique';
    list.push({ key: 'music-type', cls: 'badge music-tag', label });
  } else if (item._kind === 'library') {
    const label = item.has_vf === true ? 'VF' : item.has_vf === false ? 'VO' : '?';
    const variant = item.has_vf === true ? 'vf' : item.has_vf === false ? 'vo' : 'unknown';
    list.push({ key: 'langue', cls: `language-tag ${variant}`, label });
  } else {
    const label = props.view === 'list' ? statusLabel(item.status) : statusShortLabel(item.status);
    list.push({ key: 'statut', cls: `badge status-tag ${item.status}`, label });
  }
  const requester = requesterLabel(item);
  if (requester) list.push({ key: 'demandeur', cls: 'requester-tag', label: `👤 ${requester}` });
  return list;
});
</script>

<style scoped>
.card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: 6px;
}
.media-card.list .card-actions {
  margin-top: 4px;
}

.poster-shell .status-tag {
  position: absolute;
  top: 8px;
  left: 8px;
  /* Sur l'affiche, le libelle ne doit pas deborder de la largeur disponible. */
  max-width: calc(100% - 16px);
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Badges en vue liste : dans le corps de la carte, ou ils ont la place de s'afficher. */
.card-badges {
  margin-top: 5px;
}
.poster-shell .select-tag {
  position: absolute;
  top: 8px;
  right: 8px;
  padding: 4px;
  border-radius: var(--radius-sm);
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
  gap: var(--space-1);
  max-width: 100%;
  padding: 3px 9px;
  overflow: hidden;
  border-radius: var(--radius-pill);
  color: #fff;
  background: rgba(37, 99, 235, .92);
  font-size: var(--fs-sm);
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

.media-card.is-music :deep(img),
.media-card.is-music :deep(.poster-fallback) {
  aspect-ratio: 1 / 1;
  border-radius: var(--radius-md);
  object-fit: cover;
}

.music-tag {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 3px 9px;
  border-radius: var(--radius-pill);
  color: #fff;
  background: rgba(147, 51, 234, 0.92);
  font-size: var(--fs-xs);
  font-weight: 700;
}
.poster-shell .music-tag {
  position: absolute;
  top: 8px;
  left: 8px;
  max-width: calc(100% - 16px);
}
</style>
