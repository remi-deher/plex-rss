<template>
  <section class="panel history-panel">
    <div class="panel-head"><div><span class="eyebrow">Historique</span><h2>Dernières lectures</h2></div><small>{{ items.length }} résultat{{ items.length>1?'s':'' }}</small></div>
    <div class="history-table">
      <button v-for="item in items" :key="`${item.source}:${item.session_id}`" @click="$emit('select',item)">
        <MediaArtwork :src="item.thumb_url" :alt="displayTitle(item)" :type="item.media_type" size="small"/>
        <span class="history-title"><strong>{{ displayTitle(item) }}</strong><small>{{ item.user_name }} · {{ item.player||item.platform||'Plex' }}</small></span>
        <PlaybackMethodBadge :method="item.playback_method"/>
        <span class="history-duration">{{ formatDuration(item.watched_ms) }}</span>
        <time>{{ formatDate(item.started_at) }}</time>
      </button>
      <p v-if="!items.length" class="empty">Aucune lecture ne correspond aux filtres.</p>
    </div>
  </section>
</template>

<script setup>
import MediaArtwork from './MediaArtwork.vue';
import PlaybackMethodBadge from './PlaybackMethodBadge.vue';
defineProps({items:{type:Array,default:()=>[]}});
defineEmits(['select']);
function displayTitle(item){return item.grandparent_title?`${item.grandparent_title} · ${item.title}`:item.title}
function formatDuration(ms){const minutes=Math.round((ms||0)/60000);return minutes<60?`${minutes} min`:`${Math.floor(minutes/60)} h ${minutes%60} min`}
function formatDate(value){return value?new Intl.DateTimeFormat('fr-FR',{dateStyle:'short',timeStyle:'short'}).format(new Date(value)):'—'}
</script>

<style scoped>
.panel-head>small{color:var(--muted);font-size:10px}.history-table{display:grid;margin-top:10px}.history-table button{display:grid;grid-template-columns:42px minmax(180px,1fr) 105px 72px 135px;gap:12px;align-items:center;width:100%;padding:9px;border:0;border-bottom:1px solid var(--border);background:transparent;color:var(--text);text-align:left}.history-table button:hover{background:rgba(255,255,255,.025)}.history-title{display:grid;min-width:0}.history-title strong,.history-title small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.history-title small,.history-table time{color:var(--muted);font-size:10px}.history-duration{font-size:11px}@media(max-width:760px){.history-table button{grid-template-columns:42px minmax(0,1fr) auto}.history-duration,.history-table time{grid-column:2;font-size:9px}.history-table time{grid-column:3;grid-row:2}.history-table :deep(.playback-badge){grid-column:3;grid-row:1}}@media(max-width:430px){.history-table time{display:none}}
</style>
