<template>
  <div class="page">
    <header class="page-head">
      <div><h1>Telechargements</h1><p>Files Sonarr/Radarr, clients directs et historique.</p></div>
      <button class="icon-button" :disabled="loading" title="Actualiser" @click="loadAll"><RefreshCw :class="{spin:loading}"/></button>
    </header>
    <section class="metric-grid compact-metrics"><article v-for="entry in summary" :key="entry.label" class="metric-card"><span>{{ entry.label }}</span><strong>{{ entry.value }}</strong></article></section>
    <nav class="detail-tabs page-tabs"><button :class="{active:tab==='queue'}" @click="tab='queue'">File active</button><button :class="{active:tab==='history'}" @click="tab='history'">Historique</button></nav>
    <div class="toolbar wrap"><input v-model="query" class="search" type="search" placeholder="Filtrer les titres"><select v-if="tab==='queue'" v-model="instance"><option value="">Toutes les instances</option><option v-for="value in instances" :key="value">{{ value }}</option></select><select v-if="tab==='queue'" v-model="status"><option value="">Tous les statuts</option><option value="downloading">En cours</option><option value="queued">En file</option><option value="paused">En pause</option><option value="error">En erreur</option></select></div>
    <p v-if="error" class="notice error-text">{{ error }}</p>

    <section v-if="tab==='queue'" class="panel table-wrap"><table><thead><tr><th>Titre</th><th>Instance</th><th>Progression</th><th>Restant</th><th>Etat</th><th></th></tr></thead><tbody><tr v-for="row in filteredQueue" :key="rowKey(row)"><td><strong>{{ row.title }}</strong><small>{{ row.download_client||row.indexer||'' }}</small><small v-if="row.error" class="error-text">{{ row.error }}</small></td><td>{{ row.instance||row.download_client||'-' }}</td><td><progress :value="row.progress||0" max="100"></progress><small>{{ Math.round(row.progress||0) }}%</small></td><td>{{ row.timeleft||'-' }}</td><td><span class="badge" :class="statusKey(row)==='error'?'failed':'pending'">{{ statusLabel(row) }}</span></td><td class="actions"><button v-if="isUnmatched(row)||needsEpisodeImport(row)" class="icon-button" title="Associer manuellement" @click="openManual(row)"><Link/></button><button v-if="canAct(row)" class="icon-button" title="Blocklister et relancer" @click="queueAction(row,true,true)"><RotateCcw/></button><button v-if="canAct(row)" class="icon-button danger" title="Retirer de la file" @click="queueAction(row,false,false)"><X/></button></td></tr></tbody></table><p v-if="!loading&&!filteredQueue.length" class="empty">Aucun telechargement actif.</p></section>
    <section v-else class="panel table-wrap"><table><thead><tr><th>Titre</th><th>Type</th><th>Source</th><th>Instance</th><th>Termine</th></tr></thead><tbody><tr v-for="row in filteredHistory" :key="row.id"><td><strong>{{ row.title }}</strong><small v-if="row.year">{{ row.year }}</small></td><td>{{ row.media_type==='show'?'Serie':'Film' }}</td><td><span class="badge">{{ row.source }}</span></td><td>{{ row.instance_name||'-' }}</td><td>{{ formatDate(row.completed_at) }}</td></tr></tbody></table><p v-if="!filteredHistory.length" class="empty">Aucun telechargement termine.</p></section>

    <div v-if="manualRow" class="drawer-backdrop" @click.self="manualRow=null">
      <aside class="modal-panel form-section">
        <div class="panel-head"><h2>Associer le telechargement</h2><button class="icon-button" title="Fermer" @click="manualRow=null"><X/></button></div>
        <label>Titre<input v-model="manual.title"></label>
        <label>Annee<input v-model.number="manual.year" type="number"></label>
        <div class="inline-row"><input v-model="lookupQuery" placeholder="Chercher dans Sonarr/Radarr"><button class="secondary" @click="lookup"><Search/>Chercher</button></div>
        <button v-for="item in lookupResults" :key="`${item.title}:${item.year}`" class="lookup-result" :class="{selected:manual.arr_id===item.arr_id}" @click="pickLookup(item)"><strong>{{ item.title }}</strong><span>{{ item.year }} · {{ item.already_added?'Deja ajoute':'Non ajoute' }}</span></button>
        <template v-if="manualRow.arr_type==='sonarr'">
          <div class="settings-grid two">
            <label>Saison<select v-model.number="episodeForm.season"><option v-for="season in seasonOptions" :key="season" :value="season">Saison {{ season }}</option></select></label>
            <label>Episode<select v-model.number="episodeForm.episode_id"><option v-for="episode in filteredEpisodes" :key="episode.id" :value="episode.id">E{{ String(episode.episodeNumber).padStart(2,'0') }} · {{ episode.title||'Sans titre' }}</option></select></label>
          </div>
          <label v-if="episodeCandidates.length">Fichier a importer<select v-model.number="episodeForm.candidate"><option v-for="(candidate,index) in episodeCandidates" :key="candidate.path" :value="index">{{ candidate.path }}</option></select></label>
          <p v-else-if="targetsLoading">Chargement des saisons et episodes...</p>
          <p v-else class="warning-text">Aucun fichier importable detecte. L'association a la serie reste possible.</p>
        </template>
        <button class="primary" :disabled="busy||targetsLoading||!manual.title||!manual.arr_id||(manualRow.arr_type==='sonarr'&&!episodeForm.episode_id)" @click="submitManual"><Clapperboard v-if="manualRow.arr_type==='sonarr'&&episodeCandidates.length"/><Link v-else/>{{ manualRow.arr_type==='sonarr'&&episodeCandidates.length?'Associer et importer':'Associer' }}</button>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed,onMounted,onUnmounted,reactive,ref,watch } from 'vue';
import { Clapperboard,Link,RefreshCw,RotateCcw,Search,X } from '@lucide/vue';
import { api } from '@/api';
import { useRealtime } from '@/events';

const queue=ref([]),history=ref([]),tab=ref('queue'),query=ref(''),instance=ref(''),status=ref(''),manualRow=ref(null),lookupQuery=ref(''),lookupResults=ref([]),episodeCandidates=ref([]),episodeOptions=ref([]),targetsLoading=ref(false),loading=ref(false),busy=ref(false),error=ref('');
const manual=reactive({title:'',year:null,tmdb_id:null,tvdb_id:null,poster_url:null,arr_id:null});
const episodeForm=reactive({candidate:0,season:null,episode_id:null});
let fallback;

function rowKey(row){return `${row.instance_id||row.instance||'direct'}:${row.queue_id||row.download_id||row.title}`}
function canAct(row){return row.instance_id!=null&&row.queue_id!=null}
function isUnmatched(row){return row.request_id==null&&row.library_id==null&&['sonarr','radarr'].includes(row.arr_type)}
function needsEpisodeImport(row){return row.arr_type==='sonarr'&&statusKey(row)==='error'&&row.arr_media_id!=null}
function statusKey(row){const value=(row.status||'').toLowerCase();if(row.error||value.includes('error')||value.includes('warning')||value.includes('failed'))return'error';if(value.includes('pause'))return'paused';if(value.includes('queue'))return'queued';if((row.progress||0)>=100)return'completed';return'downloading'}
function statusLabel(row){return ({error:'Erreur',paused:'En pause',queued:'En file',completed:'Termine',downloading:'En cours'})[statusKey(row)]}
function formatDate(value){return value?new Intl.DateTimeFormat('fr-FR',{dateStyle:'medium',timeStyle:'short'}).format(new Date(value)):'-'}

const instances=computed(()=>[...new Set(queue.value.map(x=>x.instance||x.download_client).filter(Boolean))]);
const filteredQueue=computed(()=>queue.value.filter(row=>(!query.value||row.title?.toLowerCase().includes(query.value.toLowerCase()))&&(!instance.value||(row.instance||row.download_client)===instance.value)&&(!status.value||statusKey(row)===status.value)));
const filteredHistory=computed(()=>history.value.filter(row=>!query.value||row.title?.toLowerCase().includes(query.value.toLowerCase())));
const summary=computed(()=>[{label:'En cours',value:queue.value.filter(x=>statusKey(x)==='downloading').length},{label:'En file',value:queue.value.filter(x=>statusKey(x)==='queued').length},{label:'En erreur',value:queue.value.filter(x=>statusKey(x)==='error').length},{label:'Termines recents',value:history.value.length}]);
const seasonOptions=computed(()=>[...new Set(episodeOptions.value.map(x=>x.seasonNumber).filter(x=>x!=null&&x>0))].sort((a,b)=>a-b));
const filteredEpisodes=computed(()=>episodeOptions.value.filter(x=>x.seasonNumber===episodeForm.season).sort((a,b)=>a.episodeNumber-b.episodeNumber));

async function loadAll(){loading.value=true;error.value='';try{const [arr,direct,done]=await Promise.all([api('/api/arr/queue').catch(()=>[]),api('/api/downloads/direct').catch(()=>[]),api('/api/downloads/history?limit=100').catch(()=>[])]);queue.value=[...arr,...direct].sort((a,b)=>(a.progress||0)-(b.progress||0));history.value=done}catch(e){error.value=e.message}finally{loading.value=false}}
async function queueAction(row,blocklist,search){if(!confirm(blocklist?'Blocklister et relancer une recherche ?':'Retirer cet element de la file ?'))return;try{await api(`/api/arr/queue/${row.instance_id}/${row.queue_id}?blocklist=${blocklist}&search=${search}`,{method:'DELETE'});await loadAll()}catch(e){error.value=e.message}}
async function openManual(row){manualRow.value=row;Object.assign(manual,{title:row.series_title||row.title||'',year:row.year||null,tmdb_id:row.tmdb_id||null,tvdb_id:row.tvdb_id||null,poster_url:row.poster_url||null,arr_id:row.arr_media_id||null});lookupQuery.value=manual.title;lookupResults.value=[];episodeCandidates.value=[];episodeOptions.value=[];episodeForm.candidate=0;episodeForm.season=row.season_number||null;episodeForm.episode_id=null;if(row.arr_type==='sonarr'&&manual.arr_id)await loadSonarrTargets()}
async function lookup(){lookupResults.value=await api(`/api/media/lookup?query=${encodeURIComponent(lookupQuery.value)}&type=${manualRow.value.arr_type==='sonarr'?'show':'movie'}`)}
async function pickLookup(item){Object.assign(manual,{title:item.title,year:item.year,tmdb_id:item.tmdb_id,tvdb_id:item.tvdb_id,poster_url:item.poster,arr_id:item.arr_id});if(manualRow.value.arr_type==='sonarr'&&item.arr_id)await loadSonarrTargets()}
async function loadSonarrTargets(){targetsLoading.value=true;try{const download=manualRow.value.download_id?`&download_id=${encodeURIComponent(manualRow.value.download_id)}`:'';const data=await api(`/api/downloads/sonarr-manual-import?instance_id=${manualRow.value.instance_id}&series_id=${manual.arr_id}${download}`);episodeCandidates.value=data.candidates||[];episodeOptions.value=data.episodes||[];episodeForm.season=seasonOptions.value.includes(episodeForm.season)?episodeForm.season:seasonOptions.value[0]||null;const preferred=filteredEpisodes.value.find(x=>x.episodeNumber===manualRow.value.episode_number);episodeForm.episode_id=preferred?.id||filteredEpisodes.value[0]?.id||null}catch(e){error.value=e.message}finally{targetsLoading.value=false}}
async function submitManual(){busy.value=true;try{await api('/api/downloads/manual-import',{method:'POST',body:JSON.stringify({instance_id:manualRow.value.instance_id,media_type:manualRow.value.arr_type==='sonarr'?'show':'movie',title:manual.title,arr_id:manual.arr_id,year:manual.year,tmdb_id:manual.tmdb_id,tvdb_id:manual.tvdb_id,poster_url:manual.poster_url})});const candidate=episodeCandidates.value[episodeForm.candidate];if(manualRow.value.arr_type==='sonarr'&&candidate&&episodeForm.episode_id){await api('/api/downloads/sonarr-manual-import',{method:'POST',body:JSON.stringify({instance_id:manualRow.value.instance_id,series_id:manual.arr_id,episode_id:episodeForm.episode_id,path:candidate.path,folder_name:candidate.folderName||candidate.folder_name,download_id:manualRow.value.download_id,quality:candidate.quality,languages:candidate.languages,release_group:candidate.releaseGroup,indexer_flags:candidate.indexerFlags})})}manualRow.value=null;await loadAll()}catch(e){error.value=e.message}finally{busy.value=false}}

watch(()=>episodeForm.season,()=>{if(!filteredEpisodes.value.some(x=>x.id===episodeForm.episode_id))episodeForm.episode_id=filteredEpisodes.value[0]?.id||null});
useRealtime(['download.updated'],loadAll);
onMounted(()=>{loadAll();fallback=setInterval(loadAll,15000)});
onUnmounted(()=>clearInterval(fallback));
</script>
