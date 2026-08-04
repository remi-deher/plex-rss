<template>
  <div class="media-rows" role="table" aria-label="Fichiers média">
    <div class="media-row media-row-head" role="row">
      <HeaderFilter label="Titre">
        <select :value="filters.media_type" aria-label="Filtrer par type" @change="update('media_type', $event.target.value)">
          <option value="">Tous les types</option><option value="movie">Films</option>
          <option value="episode">Épisodes</option><option value="track">Musique</option>
        </select>
      </HeaderFilter>
      <HeaderFilter label="Bibliothèque">
        <select :value="filters.library" aria-label="Filtrer par bibliothèque" @change="update('library', $event.target.value)">
          <option value="">Toutes</option><option v-for="value in options.library || []" :key="value">{{ value }}</option>
        </select>
      </HeaderFilter>
      <HeaderFilter label="Studio">
        <select :value="filters.studio" aria-label="Filtrer par studio" @change="update('studio', $event.target.value)">
          <option value="">Tous</option><option v-for="value in options.studio || []" :key="value">{{ value }}</option>
        </select>
      </HeaderFilter>
      <HeaderFilter label="Qualité">
        <select :value="filters.video_codec" aria-label="Filtrer par qualité vidéo" @change="update('video_codec', $event.target.value)">
          <option value="">Toutes</option><option v-for="value in options.video_codec || []" :key="value">{{ value }}</option>
        </select>
      </HeaderFilter>
      <HeaderFilter label="Audio">
        <div class="dual-filters">
          <select :value="filters.audio_codec" aria-label="Filtrer par codec audio" @change="update('audio_codec', $event.target.value)">
            <option value="">Codec</option><option v-for="value in options.audio_codec || []" :key="value">{{ value }}</option>
          </select>
          <select :value="filters.audio_language" aria-label="Filtrer par langue audio" @change="update('audio_language', $event.target.value)">
            <option value="">Langue</option><option v-for="value in options.audio_language || []" :key="value">{{ value }}</option>
          </select>
        </div>
      </HeaderFilter>
      <HeaderFilter label="Conteneur">
        <select :value="filters.container" aria-label="Filtrer par conteneur" @change="update('container', $event.target.value)">
          <option value="">Tous</option><option v-for="value in options.container || []" :key="value">{{ value }}</option>
        </select>
      </HeaderFilter>
      <HeaderFilter label="Sous-titres">
        <div class="subtitle-filters">
          <select :value="filters.subtitle" aria-label="Filtrer la présence de sous-titres" @change="update('subtitle', $event.target.value)">
            <option value="">Présence</option><option value="with">Avec</option><option value="without">Sans</option>
          </select>
          <select :value="filters.subtitle_language" aria-label="Filtrer par langue des sous-titres" @change="update('subtitle_language', $event.target.value)">
            <option value="">Langue</option><option v-for="value in options.subtitle_language || []" :key="value">{{ value }}</option>
          </select>
          <select :value="filters.subtitle_type" aria-label="Filtrer par type de sous-titres" @change="update('subtitle_type', $event.target.value)">
            <option value="">Format</option><option v-for="value in options.subtitle_type || []" :key="value">{{ value }}</option>
          </select>
        </div>
      </HeaderFilter>
      <HeaderFilter label="Poids">
        <div class="size-filters">
          <input :value="filters.min_size_gb" type="number" min="0" step="0.5" placeholder="Min." aria-label="Poids minimal en Go" @input="update('min_size_gb', $event.target.value)">
          <input :value="filters.max_size_gb" type="number" min="0" step="0.5" placeholder="Max." aria-label="Poids maximal en Go" @input="update('max_size_gb', $event.target.value)">
        </div>
      </HeaderFilter>
      <HeaderFilter label="Audience">
        <select :value="filters.watched" aria-label="Filtrer par visionnage" @change="update('watched', $event.target.value)">
          <option value="">Tous</option><option value="yes">Visionnés</option><option value="no">Non visionnés</option>
        </select>
      </HeaderFilter>
    </div>

    <article v-for="row in items" :key="`${row.rating_key}:${row.title}`" class="media-row" role="row">
      <div class="media-title" role="cell"><strong>{{ title(row) }}</strong><small>{{ row.media_type || '—' }}</small></div>
      <span role="cell">{{ row.library || '—' }}</span>
      <span role="cell">{{ row.studio || '—' }}</span>
      <span role="cell">{{ row.video_resolution || '—' }} · {{ row.video_codec || '—' }}</span>
      <span role="cell">{{ row.audio_codec || '—' }} · {{ (row.audio_languages || []).join(', ') || 'langue inconnue' }} · {{ row.audio_track_count || 0 }} piste(s)</span>
      <span role="cell">{{ row.container || '—' }}</span>
      <span role="cell">{{ row.subtitle_count || 0 }} · {{ (row.subtitle_types || row.subtitle_languages || []).join(', ') || 'aucun' }}</span>
      <span role="cell">{{ bytes(row.size_bytes) }}</span>
      <span role="cell">{{ row.play_count || 0 }} lecture(s) · {{ (row.viewers || []).join(', ') || 'personne' }}</span>
    </article>
  </div>
</template>

<script setup>
import { defineComponent, h } from 'vue';
import { formatFileSize as bytes } from '@/utils/format';

defineProps({
  items: { type: Array, default: () => [] },
  filters: { type: Object, default: () => ({}) },
  options: { type: Object, default: () => ({}) },
});
const emit = defineEmits(['update-filter']);
const HeaderFilter = defineComponent({
  props: { label: String },
  setup(props, { slots }) {
    return () => h('div', { role: 'columnheader' }, [
      h('span', props.label),
      h('div', { class: 'column-filter' }, slots.default?.()),
    ]);
  },
});
const title = row => row.grandparent_title ? `${row.grandparent_title} · ${row.title}` : row.title;
function update(key, value) { emit('update-filter', { key, value }); }
</script>

<style scoped>
.media-rows{display:grid;min-width:0;overflow-x:auto;border:1px solid var(--border);border-radius:var(--radius-md);background:var(--surface)}
.media-row{display:grid;grid-template-columns:minmax(240px,1.7fr) minmax(135px,1fr) minmax(145px,1fr) minmax(125px,1fr) minmax(190px,1.25fr) minmax(115px,1fr) minmax(280px,1.7fr) minmax(125px,1fr) minmax(145px,1fr);gap: var(--space-3);align-items:center;min-width:1590px;padding:11px 12px;border-bottom:1px solid var(--border);font-size:var(--fs-xs)}
.media-row:last-child{border-bottom:0}.media-row-head{position:sticky;top:0;z-index:1;align-items:start;background:var(--surface-2);color:var(--muted);font-size:var(--fs-xs);font-weight:700;text-transform:uppercase}
.media-row-head>div{display:grid;gap: var(--space-2);min-width:0}.column-filter{min-width:0}.column-filter :deep(input),.column-filter :deep(select){width:100%;min-width:0;height:30px;padding:4px 7px;font-size:var(--fs-xs);text-transform:none}
.size-filters,.dual-filters{display:grid;grid-template-columns:1fr 1fr;gap: var(--space-1)}.subtitle-filters{display:grid;grid-template-columns:.75fr .9fr 1.2fr;gap: var(--space-1)}.media-title{display:grid;min-width:0}.media-row small{overflow:hidden;color:var(--muted);font-size:var(--fs-xs);text-overflow:ellipsis;white-space:nowrap}.media-row strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
</style>
