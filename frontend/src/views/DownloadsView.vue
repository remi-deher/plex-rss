<template>
  <div class="page">
    <header class="page-head">
      <div><h1>Telechargements</h1><p>Files Sonarr/Radarr, clients directs et historique.</p></div>
      <button class="icon-button" :disabled="loading" title="Actualiser" @click="loadAll"><RefreshCw :class="{spin:loading}"/></button>
    </header>
    <section class="metric-grid compact-metrics">
      <article v-for="entry in summary" :key="entry.label" class="metric-card"><span>{{ entry.label }}</span><strong>{{ entry.value }}</strong></article>
    </section>

    <UnmatchedImportsBanner
      :items="unmatchedItems"
      :row-key="rowKey"
      @view-all="tab='queue'; statusFilter='unmatched'"
      @associate="openManual"
    />

    <nav class="detail-tabs">
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

    <ManualImportModal
      v-if="manualRow"
      :row="manualRow"
      @close="manualRow=null"
      @submitted="onManualSubmitted"
    />
    <ConfirmModal v-bind="confirmDialog" @cancel="resolveConfirm(false)" @confirm="resolveConfirm(true)" />
  </div>
</template>

<script setup>
import { computed,onMounted,onUnmounted,ref } from 'vue';
import { RefreshCw,RotateCcw,X } from '@lucide/vue';
import { api } from '@/api';
import { useRealtime } from '@/events';
import UnmatchedImportsBanner from '@/components/downloads/UnmatchedImportsBanner.vue';
import ManualImportModal from '@/components/downloads/ManualImportModal.vue';
import ConfirmModal from '@/components/ConfirmModal.vue';
import { useConfirm } from '@/composables/useConfirm';

const queue=ref([]),history=ref([]),tab=ref('queue'),query=ref(''),instance=ref(''),status=ref(''),statusFilter=ref(''),manualRow=ref(null),loading=ref(false),error=ref('');
const hiddenItems=ref(new Set());
const { dialog: confirmDialog, askConfirm, resolveConfirm } = useConfirm();
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

async function loadAll(){loading.value=true;error.value='';try{const [arr,direct,done]=await Promise.all([api('/api/arr/queue').catch(()=>[]),api('/api/downloads/direct').catch(()=>[]),api('/api/downloads/history?limit=100').catch(()=>[])]);queue.value=[...arr,...direct].filter(x=>!hiddenItems.value.has(rowKey(x))).sort((a,b)=>(a.progress||0)-(b.progress||0));history.value=done}catch(e){error.value=e.message}finally{loading.value=false}}
async function queueAction(row,blocklist,search){if(!await askConfirm({title:blocklist?'Blocklister ce téléchargement ?':'Retirer ce téléchargement ?',message:blocklist?'Le fichier sera blocklisté et une nouvelle recherche sera lancée.':'Le téléchargement sera retiré de la file.',confirmLabel:blocklist?'Blocklister et rechercher':'Retirer',danger:true}))return;try{await api(`/api/arr/queue/${row.instance_id}/${row.queue_id}?blocklist=${blocklist}&search=${search}`,{method:'DELETE'});await loadAll()}catch(e){error.value=e.message}}
function openManual(row){manualRow.value=row}
async function onManualSubmitted(){hiddenItems.value.add(rowKey(manualRow.value));manualRow.value=null;await loadAll()}

useRealtime(['download.updated'],loadAll);
onMounted(()=>{loadAll();fallback=setInterval(loadAll,15000)});
onUnmounted(()=>clearInterval(fallback));
</script>
