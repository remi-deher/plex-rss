<template>
  <div class="media-rows" role="table" aria-label="Fichiers média">
    <div class="media-row media-row-head" role="row">
      <div role="columnheader">
        <span>Titre</span>
        <div v-if="filterable" class="column-filters">
          <input :value="filters.search" type="search" placeholder="Rechercher…" aria-label="Rechercher un titre" @input="update('search', $event.target.value)">
          <select :value="filters.library" aria-label="Filtrer par bibliothèque" @change="update('library', $event.target.value)">
            <option value="">Bibliothèques</option>
            <option v-for="value in options.library || []" :key="value">{{ value }}</option>
          </select>
          <select :value="filters.studio" aria-label="Filtrer par studio" @change="update('studio', $event.target.value)">
            <option value="">Studios</option>
            <option v-for="value in options.studio || []" :key="value">{{ value }}</option>
          </select>
        </div>
      </div>
      <div role="columnheader">
        <span>Vidéo</span>
        <div v-if="filterable" class="column-filters">
          <select :value="filters.media_type" aria-label="Filtrer par type" @change="update('media_type', $event.target.value)">
            <option value="">Types</option><option value="movie">Films</option>
            <option value="episode">Épisodes</option><option value="track">Musique</option>
          </select>
          <select :value="filters.video_codec" aria-label="Filtrer par codec vidéo" @change="update('video_codec', $event.target.value)">
            <option value="">Codecs</option>
            <option v-for="value in options.video_codec || []" :key="value">{{ value }}</option>
          </select>
          <select :value="filters.container" aria-label="Filtrer par conteneur" @change="update('container', $event.target.value)">
            <option value="">Conteneurs</option>
            <option v-for="value in options.container || []" :key="value">{{ value }}</option>
          </select>
        </div>
      </div>
      <div role="columnheader">
        <span>Audio</span>
        <div v-if="filterable" class="column-filters">
          <select :value="filters.audio_codec" aria-label="Filtrer par codec audio" @change="update('audio_codec', $event.target.value)">
            <option value="">Tous les codecs</option>
            <option v-for="value in options.audio_codec || []" :key="value">{{ value }}</option>
          </select>
        </div>
      </div>
      <div role="columnheader">
        <span>Sous-titres</span>
        <div v-if="filterable" class="column-filters">
          <select :value="filters.subtitle" aria-label="Filtrer les sous-titres" @change="update('subtitle', $event.target.value)">
            <option value="">Tous</option><option value="with">Avec</option><option value="without">Sans</option>
          </select>
        </div>
      </div>
      <div role="columnheader">
        <span>Poids</span>
        <div v-if="filterable" class="column-filters size-filters">
          <input :value="filters.min_size_gb" type="number" min="0" step="0.5" placeholder="Min. Go" aria-label="Poids minimal" @input="update('min_size_gb', $event.target.value)">
          <input :value="filters.max_size_gb" type="number" min="0" step="0.5" placeholder="Max. Go" aria-label="Poids maximal" @input="update('max_size_gb', $event.target.value)">
        </div>
      </div>
      <div role="columnheader">
        <span>Audience</span>
        <div v-if="filterable" class="column-filters">
          <select :value="filters.watched" aria-label="Filtrer par visionnage" @change="update('watched', $event.target.value)">
            <option value="">Tous</option><option value="yes">Visionnés</option><option value="no">Non visionnés</option>
          </select>
          <button v-if="activeCount" type="button" class="clear-filters" @click="$emit('reset')">Effacer ({{ activeCount }})</button>
        </div>
      </div>
    </div>

    <article v-for="row in items" :key="`${row.rating_key}:${row.title}`" class="media-row" role="row">
      <div class="media-title" role="cell"><strong>{{ title(row) }}</strong><small>{{ row.library || '—' }} · {{ row.studio || '—' }}</small></div>
      <span role="cell">{{ row.video_codec || '—' }} · {{ row.video_resolution || '—' }}</span>
      <span role="cell">{{ row.audio_codec || '—' }} · {{ row.audio_track_count || 0 }} piste(s)</span>
      <span role="cell">{{ row.subtitle_count || 0 }} · {{ (row.subtitle_languages || []).join(', ') || 'aucun' }}</span>
      <span role="cell">{{ bytes(row.size_bytes) }}</span>
      <span role="cell">{{ row.play_count || 0 }} lecture(s) · {{ (row.viewers || []).join(', ') || 'personne' }}</span>
    </article>
  </div>
</template>

<script setup>
import { formatFileSize as bytes } from '@/utils/format';

defineProps({
  items: { type: Array, default: () => [] },
  filters: { type: Object, default: () => ({}) },
  options: { type: Object, default: () => ({}) },
  filterable: Boolean,
  activeCount: { type: Number, default: 0 },
});
const emit = defineEmits(['update-filter', 'reset']);
const title = row => row.grandparent_title ? `${row.grandparent_title} · ${row.title}` : row.title;
function update(key, value) { emit('update-filter', { key, value }); }
</script>

<style scoped>
.media-rows{display:grid;min-width:0;overflow-x:auto;border:1px solid var(--border);border-radius:12px;background:var(--surface)}
.media-row{display:grid;grid-template-columns:minmax(260px,1.7fr) repeat(5,minmax(125px,1fr));gap:10px;align-items:center;min-width:980px;padding:11px 12px;border-bottom:1px solid var(--border);font-size:11px}
.media-row:last-child{border-bottom:0}.media-row-head{position:sticky;top:0;z-index:1;align-items:start;background:var(--surface-2);color:var(--muted);font-size:9px;font-weight:700;text-transform:uppercase}
.media-row-head>div{display:grid;gap:7px;min-width:0}.column-filters{display:grid;gap:5px}.column-filters input,.column-filters select,.clear-filters{width:100%;min-width:0;height:30px;padding:4px 7px;font-size:10px;text-transform:none}
.size-filters{grid-template-columns:1fr 1fr}.clear-filters{border:1px solid var(--border);border-radius:7px;background:transparent;color:var(--muted);cursor:pointer}
.clear-filters:hover{border-color:var(--accent);color:var(--accent)}.media-title{display:grid;min-width:0}.media-row small{overflow:hidden;color:var(--muted);font-size:9px;text-overflow:ellipsis;white-space:nowrap}.media-row strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
</style>
