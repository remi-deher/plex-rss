<template>
  <div class="page downloads-page">
    <PageHeader title="Téléchargements" description="Files Sonarr/Radarr, clients directs et historique.">
      <button class="icon-button" :disabled="loading" title="Actualiser" aria-label="Actualiser" @click="loadAll"><RefreshCw :class="{spin:loading}"/></button>
    </PageHeader>
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
    <FilterBar :active-count="activeFilterCount" :result-count="tab==='queue'?filteredQueue.length:filteredHistory.length" @reset="resetFilters">
      <template #primary><input v-model="query" class="search" type="search" placeholder="Filtrer les titres" aria-label="Filtrer les téléchargements"></template>
      <template #filters><select v-if="tab==='queue'" v-model="instance"><option value="">Toutes les instances</option><option v-for="value in instances" :key="value">{{ value }}</option></select><select v-if="tab==='queue'" v-model="status"><option value="">Tous les statuts</option><option value="downloading">En cours</option><option value="queued">En file</option><option value="paused">En pause</option><option value="error">En erreur</option><option value="unmatched">Non associés</option></select></template>
    </FilterBar>
    <UiFeedback v-if="error" type="error" title="Chargement impossible" :message="error" retry @retry="loadAll" />

    <section v-if="tab==='queue'" class="download-groups">
      <section v-for="group in queueGroups" :key="group.key" class="download-group" :class="group.key">
        <header class="download-group-head"><div><component :is="group.icon"/><div><h2>{{ group.title }}</h2><p>{{ group.description }}</p></div></div><span>{{ group.items.length }}</span></header>
        <div class="download-card-grid">
          <article v-for="row in group.items" :key="rowKey(row)" class="download-card">
            <header><div><strong>{{ row.title }}</strong><small>{{ row.instance||row.download_client||'Téléchargement direct' }}</small></div><span class="badge" :class="group.key==='intervention'?'failed':'pending'">{{ statusLabel(row) }}</span></header>
            <div class="download-progress"><div><span>Progression</span><strong>{{ Math.round(row.progress||0) }}%</strong></div><progress :value="row.progress||0" max="100"></progress><small>{{ row.timeleft||'Temps restant indisponible' }}</small></div>
            <div v-if="row.waiting_reason||row.error" class="download-callout" :class="{error:row.error}">{{ row.error||row.waiting_reason }}</div>
            <div v-if="row.origin_label||row.operational_status_label" class="download-meta">{{ row.origin_label }}<template v-if="row.operational_status_label"> · {{ row.operational_status_label }}</template></div>
            <footer><button v-if="requiresIntervention(row)" class="secondary" @click="openManual(row)"><Link/>Associer / importer</button><button v-if="canAct(row)" class="secondary" @click="queueAction(row,true,true)"><RotateCcw/>Relancer</button><button v-if="canAct(row)" class="secondary danger" @click="queueAction(row,false,false)"><X/>Retirer</button></footer>
          </article>
        </div>
      </section>
      <p v-if="!loading&&!filteredQueue.length" class="empty">Aucun telechargement actif.</p>
    </section>

    <section v-else class="panel table-wrap table-cards rich">
      <table>
        <thead>
          <tr><th>Titre</th><th>Type</th><th>Source</th><th>Instance</th><th>Termine</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in filteredHistory" :key="row.id">
            <td class="card-title"><strong>{{ row.title }}</strong><small v-if="row.year">{{ row.year }}</small></td>
            <td data-label="Type">{{ row.media_type==='show'?'Serie':'Film' }}</td>
            <td data-label="Source"><span class="badge">{{ row.source }}</span></td>
            <td data-label="Instance">{{ row.instance_name||'-' }}</td>
            <td data-label="Termine">{{ formatDate(row.completed_at) }}</td>
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
import { AlertTriangle,Clock3,Download,Link,RefreshCw,RotateCcw,X } from '@lucide/vue';
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
function requiresIntervention(row){return isUnmatched(row)||needsEpisodeImport(row)||isImportPending(row)||statusKey(row)==='error'}
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
const queueGroups=computed(()=>{
  const intervention=filteredQueue.value.filter(requiresIntervention),ids=new Set(intervention.map(rowKey));
  const remaining=filteredQueue.value.filter(row=>!ids.has(rowKey(row)));
  return [
    {key:'intervention',title:'Intervention requise',description:'Import bloqué, erreur ou média à associer',icon:AlertTriangle,items:intervention},
    {key:'active',title:'En téléchargement',description:'Transferts actuellement en progression',icon:Download,items:remaining.filter(row=>statusKey(row)==='downloading')},
    {key:'waiting',title:'En attente',description:'Éléments en file ou temporairement en pause',icon:Clock3,items:remaining.filter(row=>['queued','paused','completed'].includes(statusKey(row)))},
  ].filter(group=>group.items.length)
});
const summary=computed(()=>[{label:'En cours',value:queue.value.filter(x=>statusKey(x)==='downloading').length},{label:'En file',value:queue.value.filter(x=>statusKey(x)==='queued').length},{label:'Interventions',value:queue.value.filter(requiresIntervention).length},{label:'Termines recents',value:history.value.length}]);
const activeFilterCount=computed(()=>[query.value,instance.value,status.value||statusFilter.value].filter(Boolean).length);
function resetFilters(){query.value='';instance.value='';status.value='';statusFilter.value=''}

async function loadAll(){loading.value=true;error.value='';try{const [arr,direct,done]=await Promise.all([api('/api/arr/queue').catch(()=>[]),api('/api/downloads/direct').catch(()=>[]),api('/api/downloads/history?limit=100').catch(()=>[])]);queue.value=[...arr,...direct].filter(x=>!hiddenItems.value.has(rowKey(x))).sort((a,b)=>(a.progress||0)-(b.progress||0));history.value=done}catch(e){error.value=e.message}finally{loading.value=false}}
async function queueAction(row,blocklist,search){if(!await askConfirm({title:blocklist?'Blocklister ce téléchargement ?':'Retirer ce téléchargement ?',message:blocklist?'Le fichier sera blocklisté et une nouvelle recherche sera lancée.':'Le téléchargement sera retiré de la file.',confirmLabel:blocklist?'Blocklister et rechercher':'Retirer',danger:true}))return;try{await api(`/api/arr/queue/${row.instance_id}/${row.queue_id}?blocklist=${blocklist}&search=${search}`,{method:'DELETE'});await loadAll()}catch(e){error.value=e.message}}
function openManual(row){manualRow.value=row}
async function onManualSubmitted(){hiddenItems.value.add(rowKey(manualRow.value));manualRow.value=null;await loadAll()}

useRealtime(['download.updated'],loadAll);
onMounted(()=>{loadAll();fallback=setInterval(loadAll,15000)});
onUnmounted(()=>clearInterval(fallback));
</script>

<style scoped>
.download-groups{display:grid;gap:18px}.download-group{display:grid;gap:10px}.download-group-head{display:flex;align-items:center;justify-content:space-between;padding:0 2px}.download-group-head>div{display:flex;align-items:center;gap:10px}.download-group-head svg{width:19px;color:var(--accent)}.download-group.intervention .download-group-head svg{color:var(--danger)}.download-group-head h2{margin:0;font-size:15px}.download-group-head p{margin:2px 0 0;color:var(--muted);font-size:11px}.download-group-head>span{min-width:27px;padding:5px 8px;border:1px solid var(--border);border-radius:999px;text-align:center;font-size:11px;font-weight:700}.download-card-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.download-card{display:grid;gap:13px;padding:14px;border:1px solid var(--border);border-radius:12px;background:var(--surface)}.intervention .download-card{border-color:rgba(239,68,68,.3)}.download-card>header,.download-progress>div,.download-card footer{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.download-card>header>div{display:grid;gap:3px;min-width:0}.download-card>header strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.download-card>header small,.download-progress small,.download-meta{color:var(--muted);font-size:10px}.download-progress{display:grid;gap:6px}.download-progress span{color:var(--muted);font-size:10px}.download-progress strong{font-size:12px}.download-progress progress{width:100%;height:7px}.download-callout{padding:8px 10px;border-radius:7px;background:rgba(229,160,13,.09);color:var(--accent);font-size:11px}.download-callout.error{background:rgba(239,68,68,.09);color:var(--danger)}.download-card footer{justify-content:flex-end;margin-top:auto}.download-card footer button{display:inline-flex;align-items:center;gap:6px;padding:7px 9px;font-size:10px}.download-card footer svg{width:14px;height:14px}@media(max-width:800px){.download-card-grid{grid-template-columns:1fr}}@media(max-width:520px){.download-group-head p{display:none}.download-card{padding:12px}.download-card footer{display:grid;grid-template-columns:1fr 1fr}.download-card footer button:first-child:last-child{grid-column:1/-1}.download-card footer button{justify-content:center}}
</style>
