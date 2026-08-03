<template>
  <section class="panel history-panel">
    <div class="panel-head"><div><span class="eyebrow">Historique</span><h2>Dernières lectures</h2></div><small>{{ items.length }} résultat{{ items.length>1?'s':'' }}</small></div>
    <div class="history-table">
      <button v-for="item in items" :key="`${item.source}:${item.session_id}`" @click="$emit('select',item)">
        <MediaArtwork :src="item.thumb_url" :alt="displayTitle(item)" :type="item.media_type" size="small"/>
        <span class="history-title"><strong>{{ displayTitle(item) }}</strong><small>{{ item.user_name || 'Utilisateur Plex' }}</small></span>
        <span class="history-client">
          <span><Monitor/><strong>{{ deviceLabel(item) }}</strong></span>
          <span><Network/><code>{{ addressLabel(item) }}</code></span>
        </span>
        <PlaybackMethodBadge :method="item.playback_method"/>
        <span class="history-duration">{{ formatDuration(item.watched_ms) }}</span>
        <time>{{ formatDate(item.started_at) }}</time>
      </button>
      <p v-if="!items.length" class="empty">Aucune lecture ne correspond aux filtres.</p>
    </div>
  </section>
</template>

<script setup>
import { Monitor, Network } from '@lucide/vue';
import { formatDurationExact as formatDuration, formatDateTimeShort } from '@/utils/format';
import MediaArtwork from './MediaArtwork.vue';
import PlaybackMethodBadge from './PlaybackMethodBadge.vue';
defineProps({items:{type:Array,default:()=>[]}});
defineEmits(['select']);
function displayTitle(item){return item.grandparent_title?`${item.grandparent_title} · ${item.title}`:item.title}
function deviceLabel(item){return item.player||item.product||item.platform||'Appareil inconnu'}
function addressLabel(item){return item.address||'IP indisponible'}
const formatDate=value=>formatDateTimeShort(value,'—');
</script>

<style scoped>
.panel-head>small{color:var(--muted);font-size:11px}.history-table{display:grid;margin-top:10px}.history-table button{display:grid;grid-template-columns:42px minmax(180px,1fr) minmax(150px,210px) 105px 74px 135px;gap:14px;align-items:center;width:100%;min-height:68px;padding:11px 10px;border:0;border-bottom:1px solid var(--border);background:transparent;color:var(--text);text-align:left}.history-table button:hover{background:rgba(255,255,255,.04)}.history-title{display:grid;gap:4px;min-width:0}.history-title strong,.history-title small,.history-client strong,.history-client code{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.history-title strong{font-size:13px;line-height:1.35}.history-title small{color:color-mix(in srgb,var(--text) 70%,transparent);font-size:11px}.history-client{display:grid;gap:6px;min-width:0}.history-client>span{display:flex;align-items:center;gap:7px;min-width:0;color:color-mix(in srgb,var(--text) 74%,transparent);font-size:11px}.history-client svg{flex:none;width:14px;height:14px;color:var(--accent)}.history-client code{font-family:inherit;font-size:10px;font-variant-numeric:tabular-nums}.history-table time{color:color-mix(in srgb,var(--text) 66%,transparent);font-size:11px}.history-duration{font-size:12px;font-weight:650;white-space:nowrap}@media(max-width:1050px){.history-table button{grid-template-columns:42px minmax(180px,1fr) minmax(145px,190px) 105px 70px}.history-table time{grid-column:2/4;font-size:10px}.history-duration{grid-column:5;grid-row:1/3}}@media(max-width:760px){.history-table button{grid-template-columns:42px minmax(0,1fr) auto;gap:10px 12px}.history-client{grid-column:2}.history-duration{grid-column:2;grid-row:auto;font-size:11px}.history-table time{grid-column:3;grid-row:2;font-size:10px}.history-table :deep(.playback-badge){grid-column:3;grid-row:1}}@media(max-width:430px){.history-table time{display:none}.history-client>span{font-size:10px}}
</style>
