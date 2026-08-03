<template>
  <section class="panel history-panel">
    <div class="panel-head"><div><span class="eyebrow">Historique</span><h2>Dernières lectures</h2></div><small>{{ items.length }} résultat{{ items.length>1?'s':'' }}</small></div>
    <div class="history-table">
      <button v-for="item in items" :key="`${item.source}:${item.session_id}`" @click="$emit('select',item)">
        <MediaArtwork :src="item.thumb_url" :alt="displayTitle(item)" :type="item.media_type" size="history"/>
        <span class="history-title"><strong>{{ displayTitle(item) }}</strong><small>{{ item.user_name || 'Utilisateur Plex' }}</small></span>
        <span class="history-client">
          <span><Monitor/><strong>{{ deviceLabel(item) }}</strong></span>
          <span><Network/><code>{{ addressLabel(item) }}</code></span>
          <span class="history-place"><MapPin/><span>{{ locationLabel(item) }}</span></span>
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
import { MapPin, Monitor, Network } from '@lucide/vue';
import { formatDurationExact as formatDuration, formatDateTimeShort } from '@/utils/format';
import MediaArtwork from './MediaArtwork.vue';
import PlaybackMethodBadge from './PlaybackMethodBadge.vue';
defineProps({items:{type:Array,default:()=>[]}});
defineEmits(['select']);
function displayTitle(item){return item.grandparent_title?`${item.grandparent_title} · ${item.title}`:item.title}
function deviceLabel(item){return item.player||item.product||item.platform||'Appareil inconnu'}
function addressLabel(item){return item.address||'IP indisponible'}
function locationLabel(item){
  if(item.geo_status==='local')return 'local';
  if(item.geo_status==='anonymized')return 'Lieu masqué';
  return [item.geo_city,item.geo_region,item.geo_country_code||item.geo_country].filter(Boolean).join(', ')||'Lieu indisponible';
}
const formatDate=value=>formatDateTimeShort(value,'—');
</script>

<style scoped>
.panel-head>small{color:var(--muted);font-size:12px}.history-table{display:grid;margin-top:12px}.history-table button{display:grid;grid-template-columns:64px minmax(210px,1fr) minmax(190px,250px) 112px 84px 145px;gap:16px;align-items:center;width:100%;min-height:112px;padding:10px 12px;border:0;border-bottom:1px solid var(--border);background:transparent;color:var(--text);text-align:left}.history-table button:hover{background:rgba(255,255,255,.045)}.history-title{display:grid;gap:7px;min-width:0}.history-title strong,.history-title small,.history-client strong,.history-client code,.history-place span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.history-title strong{font-size:16px;line-height:1.4}.history-title small{color:color-mix(in srgb,var(--text) 76%,transparent);font-size:13px}.history-client{display:grid;gap:8px;min-width:0}.history-client>span{display:flex;align-items:center;gap:8px;min-width:0;color:color-mix(in srgb,var(--text) 80%,transparent);font-size:12px;line-height:1.3}.history-client svg{flex:none;width:16px;height:16px;color:var(--accent)}.history-client code{font-family:inherit;font-size:12px;font-variant-numeric:tabular-nums}.history-place span{font-weight:600}.history-table time{color:color-mix(in srgb,var(--text) 72%,transparent);font-size:12px;line-height:1.4}.history-duration{font-size:14px;font-weight:700;white-space:nowrap}@media(max-width:1150px){.history-table button{grid-template-columns:64px minmax(190px,1fr) minmax(180px,230px) 112px 80px}.history-table time{grid-column:2/4;font-size:11px}.history-duration{grid-column:5;grid-row:1/3}}@media(max-width:800px){.history-table button{grid-template-columns:64px minmax(0,1fr) auto;gap:11px 14px;align-items:start}.history-client{grid-column:2}.history-duration{grid-column:2;grid-row:auto;font-size:13px}.history-table time{grid-column:3;grid-row:2;font-size:11px}.history-table :deep(.playback-badge){grid-column:3;grid-row:1}}@media(max-width:480px){.history-table button{grid-template-columns:58px minmax(0,1fr) auto;padding-inline:6px}.history-table time{display:none}.history-title strong{font-size:14px}.history-title small,.history-client>span,.history-client code{font-size:11px}}
</style>
