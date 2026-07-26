<template>
  <div class="page analytics-page">
    <PageHeader title="Insights médiathèque" description="Analyse technique et consommation des fichiers présents sur Plex." eyebrow="Statistiques">
      <button type="button" class="secondary" :disabled="loading" @click="load(true)"><RefreshCw/>Actualiser Plex</button>
      <a class="primary export-link" :href="exportUrl"><FileDown/>Exporter CSV</a>
    </PageHeader>
    <FilterBar :active-count="activeCount" :result-count="data.items?.length||0" @reset="reset">
      <template #primary><input v-model="filters.search" class="search" type="search" placeholder="Titre, série ou studio" aria-label="Rechercher" @keyup.enter="load()"></template>
      <template #filters>
        <select v-model="filters.media_type" aria-label="Type" @change="load"><option value="">Tous les médias</option><option value="movie">Films</option><option value="episode">Épisodes</option><option value="track">Musique</option></select>
        <select v-model="filters.library" aria-label="Bibliothèque" @change="load"><option value="">Toutes les bibliothèques</option><option v-for="v in data.options?.library||[]" :key="v">{{v}}</option></select>
        <select v-model="filters.studio" aria-label="Studio" @change="load"><option value="">Tous les studios</option><option v-for="v in data.options?.studio||[]" :key="v">{{v}}</option></select>
        <select v-model="filters.video_codec" aria-label="Codec vidéo" @change="load"><option value="">Tous les codecs vidéo</option><option v-for="v in data.options?.video_codec||[]" :key="v">{{v}}</option></select>
        <select v-model="filters.audio_codec" aria-label="Codec audio" @change="load"><option value="">Tous les codecs audio</option><option v-for="v in data.options?.audio_codec||[]" :key="v">{{v}}</option></select>
        <select v-model="filters.container" aria-label="Conteneur" @change="load"><option value="">Tous les conteneurs</option><option v-for="v in data.options?.container||[]" :key="v">{{v}}</option></select>
        <select v-model="filters.subtitle" aria-label="Sous-titres" @change="load"><option value="">Tous</option><option value="with">Avec sous-titres</option><option value="without">Sans sous-titres</option></select>
        <select v-model="filters.watched" aria-label="Visionnage" @change="load"><option value="">Tous</option><option value="yes">Déjà visionnés</option><option value="no">Jamais visionnés</option></select>
        <input v-model.number="filters.min_size_gb" type="number" min="0" step="0.5" placeholder="Poids min. Go" aria-label="Poids minimal en Go" @change="load">
        <input v-model.number="filters.max_size_gb" type="number" min="0" step="0.5" placeholder="Poids max. Go" aria-label="Poids maximal en Go" @change="load">
      </template>
    </FilterBar>
    <UiFeedback v-if="error" type="error" :message="error" retry @retry="load()"/>
    <UiFeedback v-if="loading&&!data.summary" type="loading" message="Analyse du catalogue Plex…"/>
    <section v-if="data.summary" class="metric-grid analytics-metrics">
      <article class="metric-card"><span>Fichiers</span><strong>{{number(data.summary.items)}}</strong><small>filtre actuel</small></article>
      <article class="metric-card"><span>Poids total</span><strong>{{bytes(data.summary.size_bytes)}}</strong><small>stockage observé</small></article>
      <article class="metric-card"><span>Durée</span><strong>{{duration(data.summary.duration_ms)}}</strong><small>contenu cumulé</small></article>
      <article class="metric-card"><span>Lectures</span><strong>{{number(data.summary.plays)}}</strong><small>{{data.summary.viewers}} spectateur(s)</small></article>
    </section>
    <section class="insight-grid">
      <article v-for="insight in data.insights||[]" :key="insight.kind" class="panel insight-card"><Lightbulb/><div><span>{{insight.title}}</span><strong>{{insight.unit==='bytes'?bytes(insight.value):number(insight.value)}}</strong></div></article>
    </section>
    <div class="analytics-grid">
      <BreakdownPanel v-for="chart in charts" :key="chart.key" :title="chart.title" :eyebrow="chart.eyebrow" :tone="chart.tone" :interactive="!!chart.filter" :items="breakdown(chart.key)" @select="applyChartFilter(chart,$event)"/>
    </div>
    <section class="panel raw-data-panel">
      <div class="panel-head"><div><span class="eyebrow">Données brutes</span><h2>Fichiers analysés</h2></div><small>{{date(data.generated_at)}}</small></div>
      <div class="raw-table">
        <article v-for="row in visibleItems" :key="`${row.rating_key}:${row.title}`">
          <div class="raw-title"><strong>{{row.grandparent_title?`${row.grandparent_title} · ${row.title}`:row.title}}</strong><small>{{row.library}} · {{row.studio}}</small></div>
          <span><small>Vidéo</small>{{row.video_codec}} · {{row.video_resolution}}</span><span><small>Audio</small>{{row.audio_codec}} · {{row.audio_track_count}} piste(s)</span>
          <span><small>Sous-titres</small>{{row.subtitle_count}} · {{row.subtitle_languages.join(', ')||'aucun'}}</span><span><small>Poids</small>{{bytes(row.size_bytes)}}</span>
          <span><small>Audience</small>{{row.play_count}} lecture(s) · {{row.viewers.join(', ')||'personne'}}</span>
        </article>
      </div>
      <button v-if="limit<(data.items?.length||0)" type="button" class="secondary load-more" @click="limit+=100">Afficher 100 lignes de plus</button>
      <p v-if="!loading&&!data.items?.length" class="empty">Aucun fichier ne correspond aux filtres.</p>
    </section>
  </div>
</template>
<script setup>
import { computed,onMounted,reactive,ref } from 'vue';
import { FileDown,Lightbulb,RefreshCw } from '@lucide/vue';
import { api } from '@/api';
import { useRealtime } from '@/events';
import BreakdownPanel from '@/components/activity/BreakdownPanel.vue';
const data=ref({items:[],options:{},distributions:{}}),loading=ref(false),error=ref(''),limit=ref(100);
const filters=reactive({search:'',media_type:'',library:'',studio:'',video_codec:'',audio_codec:'',container:'',subtitle:'',watched:'',min_size_gb:'',max_size_gb:''});
const charts=[{key:'types',title:'Types de médias',eyebrow:'Catalogue',tone:'blue',filter:'media_type'},{key:'studios',title:'Studios principaux',eyebrow:'Origine',tone:'accent',filter:'studio'},{key:'video_codecs',title:'Codecs vidéo',eyebrow:'Vidéo',tone:'green',filter:'video_codec'},{key:'audio_codecs',title:'Codecs audio',eyebrow:'Audio',tone:'purple',filter:'audio_codec'},{key:'resolutions',title:'Résolutions',eyebrow:'Qualité',tone:'blue'},{key:'containers',title:'Conteneurs',eyebrow:'Fichiers',tone:'red',filter:'container'}];
const params=computed(()=>{const p=new URLSearchParams();Object.entries(filters).forEach(([k,v])=>{if(v)p.set(k,v)});return p});
const activeCount=computed(()=>[...params.value].length),exportUrl=computed(()=>`/api/library-analytics/export.csv?${params.value}`),visibleItems=computed(()=>(data.value.items||[]).slice(0,limit.value));
function breakdown(k){return(data.value.distributions?.[k]||[]).map(x=>({label:x.label,value:x.count,detail:`${x.percent} % du catalogue filtré`}))}
function applyChartFilter(chart,value){if(chart.filter){filters[chart.filter]=value;load()}}
async function load(refresh=false){loading.value=true;error.value='';limit.value=100;try{const p=new URLSearchParams(params.value);if(refresh)p.set('refresh','true');data.value=await api(`/api/library-analytics?${p}`)}catch(e){error.value=e.message}finally{loading.value=false}}
function reset(){Object.keys(filters).forEach(k=>filters[k]='');load()}function number(v){return Number(v||0).toLocaleString('fr-FR')}
function bytes(v){if(!v)return'0 o';const u=['o','Ko','Mo','Go','To'],i=Math.min(4,Math.floor(Math.log(v)/Math.log(1024)));return`${(v/1024**i).toLocaleString('fr-FR',{maximumFractionDigits:1})} ${u[i]}`}
function duration(v){return`${Math.round((v||0)/3600000).toLocaleString('fr-FR')} h`}function date(v){return v?`Actualisé ${new Intl.DateTimeFormat('fr-FR',{dateStyle:'medium',timeStyle:'short'}).format(new Date(v))}`:''}onMounted(()=>load());
useRealtime(['library.analytics.updated'],()=>load());
</script>
<style scoped>
.export-link{display:inline-flex;align-items:center;gap:7px;text-decoration:none}.analytics-metrics{grid-template-columns:repeat(4,minmax(0,1fr))}.metric-card small,.panel-head small{color:var(--muted);font-size:10px}.insight-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.insight-card{display:flex;align-items:center;gap:12px}.insight-card>svg{width:22px;color:var(--accent)}.insight-card>div,.raw-title,.raw-table article>span{display:grid;min-width:0}.insight-card span{color:var(--muted);font-size:10px}.insight-card strong{font-size:18px}.analytics-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.raw-data-panel{display:grid;gap:12px}.raw-table{display:grid}.raw-table article{display:grid;grid-template-columns:minmax(210px,1.5fr) repeat(5,minmax(110px,1fr));gap:12px;align-items:center;padding:11px 2px;border-bottom:1px solid var(--border);font-size:11px}.raw-table small{overflow:hidden;color:var(--muted);font-size:9px;text-overflow:ellipsis;white-space:nowrap}.raw-table strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.load-more{justify-self:center}@media(max-width:1100px){.analytics-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.raw-table article{grid-template-columns:minmax(180px,1fr) repeat(3,minmax(100px,1fr))}}@media(max-width:720px){.analytics-grid,.insight-grid{grid-template-columns:1fr}.raw-table article{grid-template-columns:1fr 1fr}.raw-title{grid-column:1/-1}}@media(max-width:420px){.analytics-metrics,.raw-table article{grid-template-columns:1fr}.raw-title{grid-column:auto}}
</style>
