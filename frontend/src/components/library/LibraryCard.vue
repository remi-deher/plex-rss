<template>
  <div class="media-card interactive" :class="{list:view==='list'}" role="button" tabindex="0" @click="$emit('open',item)" @keydown.enter="$emit('open',item)">
    <MediaPoster :poster-url="item.poster_url">
      <template #badges>
        <span class="language-tag" :class="item.has_vf===true?'vf':item.has_vf===false?'vo':'unknown'">{{ item.has_vf===true?'VF':item.has_vf===false?'VO':'?' }}</span>
      </template>
      <template #overlay>
        <div v-if="view==='grid' && (requesterLabel(item) || item.overview)" class="poster-overlay">
          <span v-if="requesterLabel(item)" class="poster-requester">👤 {{ requesterLabel(item) }}</span>
          <p v-if="item.overview" class="poster-overview">{{ item.overview }}</p>
        </div>
      </template>
    </MediaPoster>
    <div>
      <strong>{{ item.title }}</strong>
      <span>{{ item.media_type==='show'?'Serie':'Film' }}<template v-if="item.year"> · {{ item.year }}</template></span>
      <template v-if="view==='list'">
        <span v-if="requesterLabel(item)" style="font-size: 0.85em; opacity: 0.8; margin-top: 2px;">👤 {{ requesterLabel(item) }}</span>
        <small v-if="item._kind!=='request' && item.overview">{{ item.overview }}</small>
      </template>
      <small v-if="item._kind==='request'">
        {{ requestLabel(item.status) }}<template v-if="view==='list' && item.overview"> — {{ item.overview }}</template>
        <button class="manage-link" @click.stop="$emit('go-to-request',item)">Gerer la demande <ArrowRight/></button>
      </small>
    </div>
  </div>
</template>

<script setup>
import { ArrowRight } from '@lucide/vue';
import MediaPoster from '@/components/media/MediaPoster.vue';

defineProps({
  item: { type: Object, required: true },
  view: { type: String, default: 'grid' },
});
defineEmits(['open', 'go-to-request']);

function requesterLabel(item) {
  return item.custom_name || item.requested_by || item.plex_user || item.plex_user_id || '';
}

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
