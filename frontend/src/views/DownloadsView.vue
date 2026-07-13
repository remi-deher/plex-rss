<template>
  <div class="page">
    <header class="page-head">
      <div><h1>Telechargements</h1><p>Files Sonarr/Radarr, clients directs et historique.</p></div>
      <button class="icon-button" :disabled="loading" title="Actualiser" @click="loadAll"><RefreshCw :class="{spin:loading}"/></button>
    </header>
    <section class="metric-grid compact-metrics">
      <article v-for="entry in summary" :key="entry.label" class="metric-card"><span>{{ entry.label }}</span><strong>{{ entry.value }}</strong></article>
    </section>

    <!-- Imports non associés — alerte si des items nécessitent une action -->
    <section v-if="unmatchedItems.length" class="panel unmatched-alert">
      <div class="unmatched-header">
        <div class="unmatched-icon"><AlertTriangle /></div>
        <div>
          <strong>{{ unmatchedItems.length }} import{{ unmatchedItems.length > 1 ? 's' : '' }} non associé{{ unmatchedItems.length > 1 ? 's' : '' }}</strong>
          <span>Ces téléchargements ne sont pas liés à une demande ou à un élément de la bibliothèque. Cliquez sur <Link style="width:14px;height:14px;display:inline;vertical-align:middle"/> pour les associer.</span>
        </div>
        <button class="panel-link" @click="tab='queue'; statusFilter='unmatched'">Voir les imports</button>
      </div>
      <div class="unmatched-list">
        <div v-for="row in unmatchedItems.slice(0, 4)" :key="rowKey(row)" class="unmatched-item">
          <span class="unmatched-title">{{ row.title }}</span>
          <span class="badge" :class="row.arr_type === 'sonarr' ? '' : ''">{{ row.instance || '-' }}</span>
          <button class="icon-button" title="Associer manuellement" @click="openManual(row)"><Link /></button>
        </div>
        <div v-if="unmatchedItems.length > 4" class="unmatched-more">
          + {{ unmatchedItems.length - 4 }} autre(s)
        </div>
      </div>
    </section>

    <nav class="detail-tabs page-tabs">
      <button :class="{active:tab==='queue'}" @click="tab='queue'; statusFilter=''">
        File active
        <span v-if="errorItems.length" class="tab-badge error-badge">{{ errorItems.length }}</span>
      </button>
      <button :class="{active:tab==='history'}" @click="tab='history'">Historique</button>
    </nav>
    <div class="toolbar wrap">
      <input v-model="query" class="search" type="search" placeholder="Filtrer les titres">
      <select v-if="tab==='queue'" v-model="instance"><option value="">Toutes les instances</option><option v-for="value in instances" :key="value">{{ value }}</option></select>
      <select v-if="tab==='queue'" v-model="status"><option value="">Tous les statuts</option><option value="downloading">En cours</option><option value="queued">En file</option><option value="paused">En pause</option><option value="error">En erreur</option><option value="unmatched">Non associés</option></select>
    </div>
    <p v-if="error" class="notice error-text">{{ error }}</p>

    <section v-if="tab==='queue'" class="panel table-wrap">
      <table>
        <thead>
          <tr>
            <th>Titre</th>
            <th>Instance</th>
            <th>Progression</th>
            <th>Restant</th>
            <th>Etat</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in filteredQueue" :key="rowKey(row)" :class="{'row-unmatched': isUnmatched(row)}">
            <td>
              <div class="inline-row gap-10">
                <span v-if="isUnmatched(row)" class="unmatched-dot" title="Non associé"></span>
                <div>
                  <strong>{{ row.title }}</strong>
                  <small>{{ row.download_client||row.indexer||'' }}</small>
                  <small v-if="row.error" class="error-text">{{ row.error }}</small>
                </div>
              </div>
            </td>
            <td>{{ row.instance||row.download_client||'-' }}</td>
            <td>
              <progress :value="row.progress||0" max="100"></progress>
              <small>{{ Math.round(row.progress||0) }}%</small>
            </td>
            <td>{{ row.timeleft||'-' }}</td>
            <td><span class="badge" :class="statusKey(row)==='error'?'failed':'pending'">{{ statusLabel(row) }}</span></td>
            <td class="actions">
              <button v-if="isUnmatched(row)||needsEpisodeImport(row)||isImportPending(row)" class="icon-button import-btn" title="Associer / Importer manuellement" @click="openManual(row)"><Link/></button>
              <button v-if="canAct(row)" class="icon-button" title="Blocklister et relancer" @click="queueAction(row,true,true)"><RotateCcw/></button>
              <button v-if="canAct(row)" class="icon-button danger" title="Retirer de la file" @click="queueAction(row,false,false)"><X/></button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="!loading&&!filteredQueue.length" class="empty">Aucun telechargement actif.</p>
    </section>

    <section v-else class="panel table-wrap">
      <table>
        <thead>
          <tr><th>Titre</th><th>Type</th><th>Source</th><th>Instance</th><th>Termine</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in filteredHistory" :key="row.id">
            <td><strong>{{ row.title }}</strong><small v-if="row.year">{{ row.year }}</small></td>
            <td>{{ row.media_type==='show'?'Serie':'Film' }}</td>
            <td><span class="badge">{{ row.source }}</span></td>
            <td>{{ row.instance_name||'-' }}</td>
            <td>{{ formatDate(row.completed_at) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!filteredHistory.length" class="empty">Aucun telechargement termine.</p>
    </section>

    <!-- Modale association manuelle -->
    <div v-if="manualRow" class="drawer-backdrop" @click.self="manualRow=null">
      <aside class="modal-panel import-modal">
        <div class="panel-head">
          <div>
            <h2>Associer / Importer</h2>
            <p style="font-size:13px;margin-top:4px">{{ manualRow.title }}</p>
          </div>
          <button class="icon-button" title="Fermer" @click="manualRow=null"><X/></button>
        </div>

        <div class="import-steps">
          <!-- Étape 1: Chercher le media -->
          <div class="import-step">
            <div class="step-num">1</div>
            <div class="step-body">
              <strong>Identifier le media</strong>
              <div class="inline-row" style="margin-top:8px">
                <input v-model="lookupQuery" placeholder="Chercher dans Sonarr/Radarr">
                <button class="secondary" @click="lookup"><Search/>Chercher</button>
              </div>
              <div v-if="manual.arr_id && !lookupResults.length" class="notice" style="margin-top:8px">
                ✅ Média auto-détecté : <strong>{{ manual.title }}</strong>
              </div>
              <div v-if="lookupResults.length" class="lookup-list">
                <button v-for="item in lookupResults" :key="`${item.title}:${item.year}`" class="lookup-result" :class="{selected:manual.arr_id===item.arr_id}" @click="pickLookup(item)">
                  <strong>{{ item.title }}</strong>
                  <span>{{ item.year }} · {{ item.already_added?'Déjà dans Sonarr/Radarr':'Non ajouté' }}</span>
                </button>
              </div>
            </div>
          </div>

          <!-- Étape 2: Champs manuels -->
          <div class="import-step">
            <div class="step-num">2</div>
            <div class="step-body">
              <strong>Informations du media</strong>
              <div class="settings-grid two" style="margin-top:8px">
                <label>Titre<input v-model="manual.title"></label>
                <label>Annee<input v-model.number="manual.year" type="number"></label>
              </div>
            </div>
          </div>

          <!-- Étape 3: Episode (Sonarr) -->
          <div v-if="manualRow.arr_type==='sonarr'" class="import-step">
            <div class="step-num">3</div>
            <div class="step-body">
              <strong>Episode a importer</strong>
              <p v-if="targetsLoading" style="margin-top:8px">Chargement des saisons et episodes...</p>
              <template v-else>
                <div class="settings-grid two" style="margin-top:8px">
                  <label>Saison<select v-model.number="episodeForm.season"><option v-for="season in seasonOptions" :key="season" :value="season">Saison {{ season }}</option></select></label>
                  <label>Episode<select v-model.number="episodeForm.episode_id"><option v-for="episode in filteredEpisodes" :key="episode.id" :value="episode.id">E{{ String(episode.episodeNumber).padStart(2,'0') }} · {{ episode.title||'Sans titre' }}</option></select></label>
                </div>
                <label v-if="episodeCandidates.length" style="margin-top:8px">Fichier a importer<select v-model.number="episodeForm.candidate"><option v-for="(candidate,index) in episodeCandidates" :key="candidate.path" :value="index">{{ candidate.path }}</option></select></label>
                <p v-else class="warning-text" style="margin-top:8px">Aucun fichier importable detecte. L'association a la serie reste possible.</p>
              </template>
            </div>
          </div>

          <!-- Étape 3: Film (Radarr) -->
          <div v-if="manualRow.arr_type==='radarr'" class="import-step">
            <div class="step-num">3</div>
            <div class="step-body">
              <strong>Fichier a importer</strong>
              <p v-if="targetsLoading" style="margin-top:8px">Chargement des fichiers...</p>
              <template v-else>
                <label v-if="episodeCandidates.length" style="margin-top:8px">Fichier<select v-model.number="episodeForm.candidate"><option v-for="(candidate,index) in episodeCandidates" :key="candidate.path" :value="index">{{ candidate.path }}</option></select></label>
                <p v-else class="warning-text" style="margin-top:8px">Aucun fichier importable detecte. L'association au film reste possible.</p>
              </template>
            </div>
          </div>
        </div>

        <div class="form-actions" style="margin-top:16px">
          <button class="secondary" @click="manualRow=null">Annuler</button>
          <button class="primary" :disabled="busy||targetsLoading||!manual.title||!manual.arr_id||(manualRow.arr_type==='sonarr'&&!episodeForm.episode_id)" @click="submitManual">
            <Clapperboard v-if="(manualRow.arr_type==='sonarr'||manualRow.arr_type==='radarr')&&episodeCandidates.length"/>
            <Link v-else/>
            {{ (manualRow.arr_type==='sonarr'||manualRow.arr_type==='radarr')&&episodeCandidates.length?'Associer et importer':'Associer' }}
          </button>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed,onMounted,onUnmounted,reactive,ref,watch } from 'vue';
import { AlertTriangle,Clapperboard,Link,RefreshCw,RotateCcw,Search,X } from '@lucide/vue';
import { api } from '@/api';
import { useRealtime } from '@/events';

const queue=ref([]),history=ref([]),tab=ref('queue'),query=ref(''),instance=ref(''),status=ref(''),statusFilter=ref(''),manualRow=ref(null),lookupQuery=ref(''),lookupResults=ref([]),episodeCandidates=ref([]),episodeOptions=ref([]),targetsLoading=ref(false),loading=ref(false),busy=ref(false),error=ref('');
const manual=reactive({title:'',year:null,tmdb_id:null,tvdb_id:null,poster_url:null,arr_id:null});
const episodeForm=reactive({candidate:0,season:null,episode_id:null});
let fallback;

function rowKey(row){return `${row.instance_id||row.instance||'direct'}:${row.queue_id||row.download_id||row.title}`}
function canAct(row){return row.instance_id!=null&&row.queue_id!=null}
function isImportPending(row){return (row.tracked_state||'').toLowerCase()==='importpending'&&row.instance_id!=null&&row.queue_id!=null}
function isUnmatched(row){return row.request_id==null&&row.library_id==null&&['sonarr','radarr'].includes(row.arr_type)}
function needsEpisodeImport(row){return row.arr_type==='sonarr'&&statusKey(row)==='error'&&row.arr_media_id!=null}
function statusKey(row){const value=(row.status||'').toLowerCase();if(row.error||value.includes('error')||value.includes('warning')||value.includes('failed'))return'error';if(value.includes('pause'))return'paused';if(value.includes('queue'))return'queued';if((row.progress||0)>=100)return'completed';return'downloading'}
function statusLabel(row){return ({error:'Erreur',paused:'En pause',queued:'En file',completed:'Termine',downloading:'En cours'})[statusKey(row)]}
function formatDate(value){return value?new Intl.DateTimeFormat('fr-FR',{dateStyle:'medium',timeStyle:'short'}).format(new Date(value)):'-'}

const instances=computed(()=>[...new Set(queue.value.map(x=>x.instance||x.download_client).filter(Boolean))]);
const unmatchedItems=computed(()=>queue.value.filter(row=>isUnmatched(row)||needsEpisodeImport(row)));
const errorItems=computed(()=>queue.value.filter(row=>statusKey(row)==='error'));

const filteredQueue=computed(()=>{
  const activeStatus=status.value||statusFilter.value;
  return queue.value.filter(row=>{
    if(query.value&&!row.title?.toLowerCase().includes(query.value.toLowerCase()))return false;
    if(instance.value&&(row.instance||row.download_client)!==instance.value)return false;
    if(activeStatus==='unmatched')return isUnmatched(row)||needsEpisodeImport(row);
    if(activeStatus&&statusKey(row)!==activeStatus)return false;
    return true;
  });
});
const filteredHistory=computed(()=>history.value.filter(row=>!query.value||row.title?.toLowerCase().includes(query.value.toLowerCase())));
const summary=computed(()=>[{label:'En cours',value:queue.value.filter(x=>statusKey(x)==='downloading').length},{label:'En file',value:queue.value.filter(x=>statusKey(x)==='queued').length},{label:'En erreur',value:errorItems.value.length},{label:'Termines recents',value:history.value.length}]);
const seasonOptions=computed(()=>[...new Set(episodeOptions.value.map(x=>x.seasonNumber).filter(x=>x!=null&&x>0))].sort((a,b)=>a-b));
const filteredEpisodes=computed(()=>episodeOptions.value.filter(x=>x.seasonNumber===episodeForm.season).sort((a,b)=>a.episodeNumber-b.episodeNumber));

async function loadAll(){loading.value=true;error.value='';try{const [arr,direct,done]=await Promise.all([api('/api/arr/queue').catch(()=>[]),api('/api/downloads/direct').catch(()=>[]),api('/api/downloads/history?limit=100').catch(()=>[])]);queue.value=[...arr,...direct].sort((a,b)=>(a.progress||0)-(b.progress||0));history.value=done}catch(e){error.value=e.message}finally{loading.value=false}}
async function queueAction(row,blocklist,search){if(!confirm(blocklist?'Blocklister et relancer une recherche ?':'Retirer cet element de la file ?'))return;try{await api(`/api/arr/queue/${row.instance_id}/${row.queue_id}?blocklist=${blocklist}&search=${search}`,{method:'DELETE'});await loadAll()}catch(e){error.value=e.message}}
async function openManual(row){manualRow.value=row;Object.assign(manual,{title:row.series_title||row.title||'',year:row.year||null,tmdb_id:row.tmdb_id||null,tvdb_id:row.tvdb_id||null,poster_url:row.poster_url||null,arr_id:row.arr_media_id||null});lookupQuery.value=manual.title;lookupResults.value=[];episodeCandidates.value=[];episodeOptions.value=[];episodeForm.candidate=0;episodeForm.season=row.season_number||null;episodeForm.episode_id=null;if(row.arr_type==='sonarr'&&manual.arr_id)await loadSonarrTargets();if(row.arr_type==='radarr'&&manual.arr_id)await loadRadarrTargets()}
async function lookup(){lookupResults.value=await api(`/api/media/lookup?query=${encodeURIComponent(lookupQuery.value)}&type=${manualRow.value.arr_type==='sonarr'?'show':'movie'}`)}
async function pickLookup(item){Object.assign(manual,{title:item.title,year:item.year,tmdb_id:item.tmdb_id,tvdb_id:item.tvdb_id,poster_url:item.poster,arr_id:item.arr_id});if(manualRow.value.arr_type==='sonarr'&&item.arr_id)await loadSonarrTargets();if(manualRow.value.arr_type==='radarr'&&item.arr_id)await loadRadarrTargets()}
async function loadSonarrTargets(){targetsLoading.value=true;try{const download=manualRow.value.download_id?`&download_id=${encodeURIComponent(manualRow.value.download_id)}`:'';const data=await api(`/api/downloads/sonarr-manual-import?instance_id=${manualRow.value.instance_id}&series_id=${manual.arr_id}${download}`);episodeCandidates.value=data.candidates||[];episodeOptions.value=data.episodes||[];episodeForm.season=seasonOptions.value.includes(episodeForm.season)?episodeForm.season:seasonOptions.value[0]||null;const preferred=filteredEpisodes.value.find(x=>x.episodeNumber===manualRow.value.episode_number);episodeForm.episode_id=preferred?.id||filteredEpisodes.value[0]?.id||null}catch(e){error.value=e.message}finally{targetsLoading.value=false}}
async function loadRadarrTargets(){targetsLoading.value=true;try{const download=manualRow.value.download_id?`&download_id=${encodeURIComponent(manualRow.value.download_id)}`:'';const data=await api(`/api/downloads/radarr-manual-import?instance_id=${manualRow.value.instance_id}&movie_id=${manual.arr_id}${download}`);episodeCandidates.value=data.candidates||[];}catch(e){error.value=e.message}finally{targetsLoading.value=false}}
async function submitManual(){busy.value=true;try{await api('/api/downloads/manual-import',{method:'POST',body:JSON.stringify({instance_id:manualRow.value.instance_id,media_type:manualRow.value.arr_type==='sonarr'?'show':'movie',title:manual.title,arr_id:manual.arr_id,year:manual.year,tmdb_id:manual.tmdb_id,tvdb_id:manual.tvdb_id,poster_url:manual.poster_url})});const candidate=episodeCandidates.value[episodeForm.candidate];if(manualRow.value.arr_type==='sonarr'&&candidate&&episodeForm.episode_id){await api('/api/downloads/sonarr-manual-import',{method:'POST',body:JSON.stringify({instance_id:manualRow.value.instance_id,series_id:manual.arr_id,episode_id:episodeForm.episode_id,path:candidate.path,folder_name:candidate.folderName||candidate.folder_name,download_id:manualRow.value.download_id,quality:candidate.quality,languages:candidate.languages,release_group:candidate.releaseGroup,indexer_flags:candidate.indexerFlags})})}if(manualRow.value.arr_type==='radarr'&&candidate){await api('/api/downloads/radarr-manual-import',{method:'POST',body:JSON.stringify({instance_id:manualRow.value.instance_id,movie_id:manual.arr_id,path:candidate.path,folder_name:candidate.folderName||candidate.folder_name,download_id:manualRow.value.download_id,quality:candidate.quality,languages:candidate.languages,release_group:candidate.releaseGroup,indexer_flags:candidate.indexerFlags})})}manualRow.value=null;await loadAll()}catch(e){error.value=e.message}finally{busy.value=false}}

watch(()=>episodeForm.season,()=>{if(!filteredEpisodes.value.some(x=>x.id===episodeForm.episode_id))episodeForm.episode_id=filteredEpisodes.value[0]?.id||null});
useRealtime(['download.updated'],loadAll);
onMounted(()=>{loadAll();fallback=setInterval(loadAll,15000)});
onUnmounted(()=>clearInterval(fallback));
</script>
