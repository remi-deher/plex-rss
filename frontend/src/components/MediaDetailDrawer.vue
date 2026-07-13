<template>
  <div class="drawer-backdrop" @click.self="$emit('close')">
    <aside class="detail-drawer" role="dialog" aria-modal="true" :aria-label="detail?.title || 'Detail media'">
      <header class="drawer-head">
        <div><span class="eyebrow">{{ typeLabel }}</span><h2>{{ detail?.title || 'Chargement...' }}</h2></div>
        <button class="icon-button" title="Fermer" @click="$emit('close')"><X /></button>
      </header>
      <p v-if="error" class="notice error-text">{{ error }}</p>
      <div v-if="loading" class="drawer-loading"><LoaderCircle class="spin" /> Chargement</div>
      <template v-else-if="detail">
        <div class="detail-hero">
          <img v-if="detail.poster_url" :src="detail.poster_url" alt="" />
          <div class="detail-copy">
            <div class="inline-row compact"><span v-if="detail.year" class="badge">{{ detail.year }}</span><span v-if="detail.vote" class="badge"><Star />{{ detail.vote }}</span><span v-if="statusLabel" class="badge" :class="statusClass">{{ statusLabel }}</span></div>
            <p>{{ detail.overview || 'Aucun resume disponible.' }}</p>
            <div v-if="detail.genres?.length" class="tag-row"><span v-for="genre in detail.genres" :key="genre" class="badge">{{ genre }}</span></div>
          </div>
        </div>

        <section v-if="canRequest" class="drawer-section form-section">
          <h3>Demander ce media</h3>
          <label v-if="requesters.length">Demandeur<select v-model="requestForm.plex_user_id"><option v-for="user in requesters" :key="user.plex_user_id" :value="user.plex_user_id">{{ user.custom_name || user.display_name || user.plex_user_id }}</option></select></label>
          <label v-if="folders.length">Dossier racine<select v-model="requestForm.root_folder"><option value="">Dossier par defaut</option><option v-for="folder in folders" :key="folder.path || folder" :value="folder.path || folder">{{ folder.path || folder }}</option></select></label>
          <div v-if="detail.media_type === 'show' && seasonNumbers.length" class="season-grid"><label v-for="season in seasonNumbers" :key="season" class="check"><input v-model="requestForm.seasons" type="checkbox" :value="season"> Saison {{ season }}</label></div>
          <button class="primary" :disabled="busy || !requestForm.plex_user_id || (detail.media_type === 'show' && !requestForm.seasons.length)" @click="submitRequest"><PlusCircle />{{ busy ? 'Envoi...' : 'Demander' }}</button>
        </section>

        <template v-if="mode !== 'discover'">
          <nav class="detail-tabs">
            <button v-for="entry in tabs" :key="entry" :class="{active:tab===entry}" @click="selectTab(entry)">{{ tabLabel(entry) }}</button>
          </nav>
          <section v-if="tab === 'requests'" class="drawer-section">
            <article v-for="row in detail.requests || []" :key="row.id" class="detail-row">
              <div><strong>{{ row.requested_by || row.plex_user || row.plex_user_id }}</strong><span>{{ row.status }} · {{ formatDate(row.requested_at) }}</span></div>
              <div class="actions"><button v-if="row.arr_id" class="icon-button" title="Rechercher une release" @click="router.push(`/releases/${row.id}`)"><Search /></button><button v-if="row.status === 'failed'" class="icon-button" title="Relancer" @click="requestAction(row.id, 'retry')"><RotateCcw /></button><button v-if="row.status !== 'available'" class="icon-button" title="Marquer traitee" @click="markProcessed(row.id)"><CheckCheck /></button><button class="icon-button danger" title="Supprimer" @click="deleteRequest(row.id)"><Trash2 /></button></div>
            </article>
            <p v-if="!detail.requests?.length" class="empty">Aucune demande liee.</p>
          </section>
          <section v-else-if="tab === 'language'" class="drawer-section">
            <div class="panel-head"><h3>Versions audio</h3><div class="actions"><button class="secondary" :disabled="busy" @click="scanVff"><RefreshCw />Analyser</button><button class="secondary" :disabled="busy" @click="ignoreVff"><EyeOff />Ignorer</button></div></div>
            <pre v-if="vfDetail" class="json-summary">{{ JSON.stringify(vfDetail, null, 2) }}</pre>
            <p v-else class="empty">Chargez l'analyse pour voir les pistes et episodes.</p>
          </section>
          <section v-else-if="tab === 'calendar'" class="drawer-section timeline">
            <article v-for="event in detail.calendar || []" :key="`${event.date}:${event.title}:${event.subtitle}`" class="timeline-row"><CalendarDays /><div><strong>{{ event.title }}</strong><span>{{ event.subtitle }} · {{ formatDate(event.date) }}</span></div></article>
            <p v-if="!detail.calendar?.length" class="empty">Aucun evenement planifie.</p>
          </section>
          <section v-else class="drawer-section">
            <div class="action-grid compact-actions"><button class="secondary" :disabled="busy" @click="recheckPlex"><RefreshCw />Verifier dans Plex</button><button class="secondary" :disabled="busy" @click="reportIssue"><Flag />Signaler un probleme</button></div>
            <article v-for="issue in detail.issues || []" :key="issue.id" class="detail-row"><div><strong>{{ issue.issue_type }}</strong><span>{{ issue.message || 'Sans commentaire' }}</span></div><span class="badge">{{ issue.status }}</span></article>
          </section>
        </template>

        <section v-if="mode === 'discover' && recommendations.length" class="drawer-section"><h3>Recommandations</h3><div class="mini-media-grid"><button v-for="item in recommendations" :key="`${item.media_type}:${item.tmdb_id}`" @click="$emit('select', item)"><img v-if="item.poster_url" :src="item.poster_url" alt=""><span>{{ item.title }}</span></button></div></section>
      </template>
    </aside>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { CalendarDays, CheckCheck, EyeOff, Flag, LoaderCircle, PlusCircle, RefreshCw, RotateCcw, Search, Star, Trash2, X } from "@lucide/vue";
import { useRouter } from "vue-router";
import { api } from "@/api";

const props=defineProps({item:{type:Object,required:true},mode:{type:String,default:'library'}});
const emit=defineEmits(['close','updated','select']);
const router=useRouter();
const detail=ref(null),requesters=ref([]),folders=ref([]),vfDetail=ref(null),loading=ref(false),busy=ref(false),error=ref(''),tab=ref('summary');
const requestForm=reactive({plex_user_id:'',root_folder:'',seasons:[]});
const tabs=['summary','requests','language','calendar'];
const typeLabel=computed(()=>detail.value?.media_type==='show'?'Serie':'Film');
const statusLabel=computed(()=>detail.value?.available||detail.value?.in_library?'Disponible':detail.value?.requested?'Deja demande':detail.value?.request_status||'');
const statusClass=computed(()=>detail.value?.available||detail.value?.in_library?'available':'pending');
const canRequest=computed(()=>props.mode==='discover'&&!detail.value?.available&&!detail.value?.in_library&&!detail.value?.requested);
const seasonNumbers=computed(()=>Array.from({length:Number(detail.value?.number_of_seasons||0)},(_,i)=>i+1));
const recommendations=computed(()=>[...(detail.value?.recommendations||[]),...(detail.value?.similar||[])].slice(0,12));
function tabLabel(value){return ({summary:'Resume',requests:'Demandes',language:'VF / audio',calendar:'Calendrier'})[value]}
function formatDate(value){return value?new Intl.DateTimeFormat('fr-FR',{dateStyle:'medium'}).format(new Date(value)):'-'}
function mediaPath(){const source=props.item;if(props.mode==='discover')return `/api/discover/detail?media_type=${source.media_type}&tmdb_id=${source.tmdb_id||source.id}`;if(props.mode==='request')return `/api/media/detail?request_id=${source.id}`;const id=source.library_id||source.id;return `/api/media/detail?library_id=${id}`}
async function load(){loading.value=true;error.value='';vfDetail.value=null;try{const payload=await api(mediaPath());detail.value=props.mode==='discover'?payload:{...payload.media,...payload};if(props.mode==='discover'){requesters.value=await api('/api/discover/requesters');requestForm.plex_user_id=requesters.value[0]?.plex_user_id||'';requestForm.seasons=[...seasonNumbers.value];const service=detail.value.media_type==='show'?'sonarr':'radarr';folders.value=await api(`/api/${service}/folders`).catch(()=>[])}}catch(e){error.value=e.message}finally{loading.value=false}}
async function submitRequest(){busy.value=true;error.value='';try{const data=await api('/api/media/add',{method:'POST',body:JSON.stringify({title:detail.value.title,year:detail.value.year,media_type:detail.value.media_type,tmdb_id:detail.value.tmdb_id,tvdb_id:detail.value.tvdb_id,imdb_id:detail.value.imdb_id,poster_url:detail.value.poster_url,overview:detail.value.overview,plex_user_id:requestForm.plex_user_id,root_folder:requestForm.root_folder||null,seasons:detail.value.media_type==='show'?requestForm.seasons:null,auto_search:true})});detail.value.requested=true;detail.value.request_status=data.pending_approval?'pending_approval':'sent_to_arr';emit('updated',data)}catch(e){error.value=e.message}finally{busy.value=false}}
async function requestAction(id,action){busy.value=true;try{await api(`/api/requests/${id}/${action}`,{method:'POST'});await load();emit('updated')}catch(e){error.value=e.message}finally{busy.value=false}}
async function markProcessed(id){busy.value=true;try{await api(`/api/requests/${id}/mark-processed?event=available`,{method:'POST'});await load();emit('updated')}catch(e){error.value=e.message}finally{busy.value=false}}
async function deleteRequest(id){if(!confirm('Supprimer cette demande ?'))return;busy.value=true;try{await api(`/api/requests/${id}`,{method:'DELETE'});await load();emit('updated')}catch(e){error.value=e.message}finally{busy.value=false}}
function sourcePath(){return detail.value?.media?.kind==='request'?'requests':'library'}
function sourceId(){return detail.value?.media?.vf_source_id||props.item.id}
async function loadVf(){vfDetail.value=await api(`/api/${sourcePath()}/${sourceId()}/vf-detail`)}
async function selectTab(value){tab.value=value;if(value==='language'&&!vfDetail.value)try{await loadVf()}catch(e){error.value=e.message}}
async function scanVff(){busy.value=true;try{await api(`/api/${sourcePath()}/${sourceId()}/vff-scan`,{method:'POST'});await loadVf()}catch(e){error.value=e.message}finally{busy.value=false}}
async function ignoreVff(){busy.value=true;try{await api(`/api/${sourcePath()}/${sourceId()}/vff-ignore`,{method:'POST'});await loadVf()}catch(e){error.value=e.message}finally{busy.value=false}}
async function recheckPlex(){busy.value=true;try{const media=detail.value.media||{};await api(`/api/media/recheck-plex?${media.library_id?`library_id=${media.library_id}`:`request_id=${media.request_id}`}`,{method:'POST'});await load();emit('updated')}catch(e){error.value=e.message}finally{busy.value=false}}
async function reportIssue(){const message=prompt('Decrivez le probleme rencontre');if(message===null)return;busy.value=true;try{const media=detail.value.media||{};await api('/api/media/issues',{method:'POST',body:JSON.stringify({library_id:media.library_id,request_id:media.request_id,issue_type:'other',message})});await load();emit('updated')}catch(e){error.value=e.message}finally{busy.value=false}}
watch(()=>props.item,load,{deep:true});
onMounted(load);
</script>
