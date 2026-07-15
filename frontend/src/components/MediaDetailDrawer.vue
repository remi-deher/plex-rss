<template>
  <div class="drawer-backdrop" @click.self="$emit('close')">
    <aside class="detail-drawer" role="dialog" aria-modal="true" :aria-label="detail?.title || 'Detail media'">
      <div v-if="detail?.backdrop_url" class="modal-bg" :style="{ backgroundImage: `url(${detail.backdrop_url})` }"></div>
      <header class="drawer-head">
        <div><span class="eyebrow">{{ typeLabel }}</span><h2>{{ detail?.title || 'Chargement...' }}</h2></div>
        <button class="icon-button" title="Fermer" @click="$emit('close')"><X /></button>
      </header>
      <p v-if="error" class="notice error-text">{{ error }}</p>
      <div v-if="loading" class="drawer-loading"><LoaderCircle class="spin" /> Chargement</div>
      <template v-else-if="detail">
        <MediaHero 
          :detail="detail" 
          :status-label="statusLabel" 
          :status-class="statusClass" 
          :admin="admin"
          @report-issue="showIssueForm = !showIssueForm" 
        />

        <section v-if="canRequest" class="drawer-section form-section">
          <h3>Demander ce media</h3>
          <label v-if="requesters.length">Demandeur<select v-model="requestForm.plex_user_id"><option v-for="user in requesters" :key="user.plex_user_id" :value="user.plex_user_id">{{ user.custom_name || user.display_name || user.plex_user_id }}</option></select></label>
          <label v-if="folders.length">Dossier racine<select v-model="requestForm.root_folder"><option value="">Dossier par defaut</option><option v-for="folder in folders" :key="folder.path || folder" :value="folder.path || folder">{{ folder.path || folder }}</option></select></label>
          <div v-if="detail.media_type === 'show' && seasonNumbers.length" class="season-grid"><label v-for="season in seasonNumbers" :key="season" class="check"><input v-model="requestForm.seasons" type="checkbox" :value="season"> Saison {{ season }}</label></div>
          <button class="primary" :disabled="busy || !requestForm.plex_user_id || (detail.media_type === 'show' && !requestForm.seasons.length)" @click="submitRequest"><PlusCircle />{{ busy ? 'Envoi...' : 'Demander' }}</button>
        </section>

        <template v-if="mode !== 'discover'">
          <nav class="detail-tabs" style="overflow-x: auto; display: flex; gap: 0.5rem; white-space: nowrap; padding-bottom: 0.5rem;">
            <button v-for="entry in tabs" :key="entry" :class="{active:tab===entry}" @click="selectTab(entry)">{{ tabLabel(entry) }}</button>
          </nav>
          
          <!-- Tab Demandes -->
          <section v-if="tab === 'requests'" class="drawer-section">
            <div class="panel form-section" style="margin-bottom: 1rem;">
              <label>Ajouter un co-demandeur
                <div class="inline-row compact">
                  <select v-model="newRequesterId">
                    <option value="">Sélectionnez un utilisateur</option>
                    <option v-for="u in users" :key="u.plex_user_id" :value="u.plex_user_id">{{ u.custom_name || u.display_name || u.plex_user_id }}</option>
                  </select>
                  <button class="primary" :disabled="busy || !newRequesterId" @click="addRequester"><PlusCircle/> Ajouter</button>
                </div>
              </label>
            </div>
            <article v-for="row in detail.requests || []" :key="row.id" class="detail-row">
              <div>
                <strong>{{ row.requested_by || row.plex_user || row.plex_user_id }}</strong>
                <span>{{ row.status }} · {{ formatDate(row.requested_at) }}</span>
                <small v-if="row.last_request_mail" class="mail-history">
                  Mail demande {{ formatDate(row.last_request_mail.sent_at) }} ({{ row.last_request_mail.triggered_by === 'manual' ? 'manuel' : 'auto' }})
                </small>
                <small v-if="row.last_available_mail" class="mail-history">
                  Mail dispo {{ formatDate(row.last_available_mail.sent_at) }} ({{ row.last_available_mail.triggered_by === 'manual' ? 'manuel' : 'auto' }})
                </small>
              </div>
              <div class="actions">
                <button v-if="row.arr_id" class="icon-button" title="Rechercher une release" @click="router.push(`/releases/${row.id}`)"><Search /></button>
                <button v-if="row.status === 'failed'" class="icon-button" title="Relancer" @click="requestAction(row.id, 'retry')"><RotateCcw /></button>
                <button class="icon-button" title="Renvoyer email de demande" :disabled="busy" @click="resendMail(row.id, 'request')"><Mail /></button>
                <button v-if="row.status === 'available'" class="icon-button" title="Renvoyer email de disponibilite" :disabled="busy" @click="resendMail(row.id, 'available')"><MailCheck /></button>
                <button v-if="row.status !== 'available'" class="icon-button" title="Marquer traitee (sans notifier)" @click="markProcessed(row.id, false)"><EyeOff /></button>
                <button v-if="row.status !== 'available'" class="icon-button" title="Marquer traitee (avec email)" @click="markProcessed(row.id, true)"><CheckCheck /></button>
                <button class="icon-button danger" title="Supprimer" @click="deleteRequest(row.id)"><Trash2 /></button>
              </div>
            </article>
            <p v-if="!detail.requests?.length" class="empty">Aucune demande liee.</p>
          </section>

          <!-- Tab Calendrier -->
          <section v-else-if="tab === 'calendar'" class="drawer-section timeline">
            <article v-for="event in detail.calendar || []" :key="`${event.date}:${event.title}:${event.subtitle}`" class="timeline-row"><CalendarDays /><div><strong>{{ event.title }}</strong><span>{{ event.subtitle }} · {{ formatDate(event.date) }}</span></div></article>
            <p v-if="!detail.calendar?.length" class="empty">Aucun evenement planifie.</p>
          </section>

          <!-- Tab Resume -->
          <section v-else class="drawer-section">
            <div class="action-grid compact-actions">
              <button class="secondary" :disabled="busy" @click="recheckPlex"><RefreshCw />Verifier dans Plex</button>
              <button class="secondary" :disabled="busy" @click="openCorrection('media', null, null)"><MessageSquareWarning />Correction globale</button>
            </div>
            
            <MediaIssueForm
              v-if="showIssueForm"
              :busy="busy"
              @submit="reportIssue"
              @cancel="showIssueForm = false"
            />

            <MediaCorrectionForm
              v-if="showCorrectionForm"
              :initial-form="correctionForm"
              :users="users"
              :correction-options="correctionOptions"
              :busy="busy"
              @submit="sendCorrection"
              @cancel="showCorrectionForm = false"
            />

            <MediaAudioSection
              :vf-detail="vfDetail"
              :busy="busy"
              @scan="scanVff"
              @correction="openCorrection"
            />

            <article v-for="issue in detail.issues || []" :key="issue.id" class="detail-row" style="margin-top: 1rem;">
              <div><strong>{{ issue.issue_type }}</strong><span>{{ issue.message || 'Sans commentaire' }}</span></div>
              <span class="badge">{{ issue.status }}</span>
            </article>
          </section>
        </template>

        <section v-if="mode === 'discover' && recommendations.length" class="drawer-section"><h3>Recommandations</h3><div class="mini-media-grid"><button v-for="item in recommendations" :key="`${item.media_type}:${item.tmdb_id}`" @click="$emit('select', item)"><img v-if="item.poster_url" :src="item.poster_url" alt=""><span>{{ item.title }}</span></button></div></section>
      </template>
    </aside>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { CalendarDays, CheckCheck, EyeOff, LoaderCircle, Mail, MailCheck, PlusCircle, RefreshCw, RotateCcw, Search, Trash2, X, MessageSquareWarning } from "@lucide/vue";
import { useRouter } from "vue-router";
import { api } from "@/api";
import MediaHero from "./media/MediaHero.vue";
import MediaAudioSection from "./media/MediaAudioSection.vue";
import MediaIssueForm from "./media/MediaIssueForm.vue";
import MediaCorrectionForm from "./media/MediaCorrectionForm.vue";
import { inject } from 'vue';

const props=defineProps({item:{type:Object,required:true},mode:{type:String,default:'library'}});
const emit=defineEmits(['close','updated','select']);
const router=useRouter();
const detail=ref(null),requesters=ref([]),folders=ref([]),vfDetail=ref(null),loading=ref(false),busy=ref(false),error=ref(''),tab=ref('summary');
const requestForm=reactive({plex_user_id:'',root_folder:'',seasons:[]});
const tabs=['summary','requests','calendar'];
const admin = inject('isAdmin', false);

const showIssueForm=ref(false),showCorrectionForm=ref(false);
const users=ref([]),correctionOptions=ref([]);
const correctionForm=reactive({scope:'media',season_number:null,episode_number:null,recipient_user_ids:[],corrections:[],note:''});
const newRequesterId=ref('');

const typeLabel=computed(()=>detail.value?.media_type==='show'?'Serie':'Film');
const statusLabel=computed(()=>detail.value?.available||detail.value?.in_library?'Disponible':detail.value?.requested?'Deja demande':detail.value?.request_status||'');
const statusClass=computed(()=>detail.value?.available||detail.value?.in_library?'available':'pending');
const canRequest=computed(()=>props.mode==='discover'&&!detail.value?.available&&!detail.value?.in_library&&!detail.value?.requested);
const seasonNumbers=computed(()=>Array.from({length:Number(detail.value?.number_of_seasons||0)},(_,i)=>i+1));
const recommendations=computed(()=>[...(detail.value?.recommendations||[]),...(detail.value?.similar||[])].slice(0,6));

function tabLabel(value){return ({summary:'Resume',requests:'Demandes',calendar:'Calendrier'})[value]}
function formatDate(value){return value?new Intl.DateTimeFormat('fr-FR',{dateStyle:'medium'}).format(new Date(value)):'-'}
function mediaPath(){const source=props.item;if(props.mode==='discover'){const p=new URLSearchParams();p.set('media_type',source.media_type);if(source.tmdb_id)p.set('tmdb_id',source.tmdb_id);else if(source.tvdb_id)p.set('tvdb_id',source.tvdb_id);else p.set('tmdb_id',source.id);return `/api/discover/detail?${p}`}if(props.mode==='request')return `/api/media/detail?request_id=${source.id}`;const id=source.library_id||source.id;return `/api/media/detail?library_id=${id}`}

async function loadUsers(){
  try{
    users.value=await api('/api/users');
    correctionOptions.value=await api('/api/media/corrections/options');
  }catch(e){}
}

async function load(){
  loading.value=true;error.value='';vfDetail.value=null;
  try{
    const payload=await api(mediaPath());
    detail.value=props.mode==='discover'?payload:{...payload.media,...payload};
    if(props.mode==='discover'){
      requesters.value=await api('/api/discover/requesters');
      requestForm.plex_user_id=requesters.value[0]?.plex_user_id||'';
      requestForm.seasons=[...seasonNumbers.value];
      const service=detail.value.media_type==='show'?'sonarr':'radarr';
      folders.value=await api(`/api/${service}/folders`).catch(()=>[]);
    }
  }catch(e){error.value=e.message}finally{loading.value=false}
  
  if (props.mode !== 'discover') {
    Promise.all([loadVf(), loadUsers()]).catch(()=>{});
  }
}

function openCorrection(scope, season, episode) {
  correctionForm.scope = scope;
  correctionForm.season_number = season;
  correctionForm.episode_number = episode;
  const reqIds = (detail.value?.requests||[]).map(r=>r.plex_user_id);
  correctionForm.recipient_user_ids = users.value.filter(u=>reqIds.includes(u.plex_user_id)).map(u=>u.id);
  showCorrectionForm.value = true;
  showIssueForm.value = false;
}

async function submitRequest(){
  busy.value=true;error.value='';
  try{
    const data=await api('/api/media/add',{method:'POST',body:JSON.stringify({title:detail.value.title,year:detail.value.year,media_type:detail.value.media_type,tmdb_id:detail.value.tmdb_id,tvdb_id:detail.value.tvdb_id,imdb_id:detail.value.imdb_id,poster_url:detail.value.poster_url,overview:detail.value.overview,plex_user_id:requestForm.plex_user_id,root_folder:requestForm.root_folder||null,seasons:detail.value.media_type==='show'?requestForm.seasons:null,auto_search:true})});
    detail.value.requested=true;
    detail.value.request_status=data.pending_approval?'pending_approval':'sent_to_arr';
    emit('updated',data);
  }catch(e){error.value=e.message}finally{busy.value=false}
}

async function requestAction(id,action){
  busy.value=true;
  try{await api(`/api/requests/${id}/${action}`,{method:'POST'});await load();emit('updated')}
  catch(e){error.value=e.message}finally{busy.value=false}
}

async function markProcessed(id, notify=true){
  busy.value=true;
  try{await api(`/api/requests/${id}/mark-processed?event=available&notify=${notify}`,{method:'POST'});await load();emit('updated')}
  catch(e){error.value=e.message}finally{busy.value=false}
}

async function resendMail(id, event){
  busy.value=true;
  try{await api(`/api/requests/${id}/resend-mail?event=${event}`,{method:'POST'});await load();emit('updated')}
  catch(e){error.value=e.message}finally{busy.value=false}
}

async function addRequester(){
  busy.value=true;error.value='';
  try{
    await api('/api/media/add',{method:'POST',body:JSON.stringify({title:detail.value.title,year:detail.value.year,media_type:detail.value.media_type,tmdb_id:detail.value.tmdb_id,tvdb_id:detail.value.tvdb_id,imdb_id:detail.value.imdb_id,poster_url:detail.value.poster_url,overview:detail.value.overview,plex_user_id:newRequesterId.value,root_folder:null,seasons:null,auto_search:false})});
    await load();
    newRequesterId.value='';
    emit('updated');
  }catch(e){error.value=e.message}finally{busy.value=false}
}

async function deleteRequest(id){
  if(!confirm('Supprimer cette demande ?'))return;
  busy.value=true;
  try{await api(`/api/requests/${id}`,{method:'DELETE'});await load();emit('updated')}
  catch(e){error.value=e.message}finally{busy.value=false}
}

function sourcePath(){return detail.value?.media?.kind==='request'?'requests':'library'}
function sourceId(){return detail.value?.media?.vf_source_id||props.item.id}

async function loadVf(){
  vfDetail.value=await api(`/api/${sourcePath()}/${sourceId()}/vf-detail`);
}

async function selectTab(value){
  tab.value=value;
}

async function scanVff(){
  busy.value=true;
  try{await api(`/api/${sourcePath()}/${sourceId()}/vff-scan`,{method:'POST'});await loadVf()}
  catch(e){error.value=e.message}finally{busy.value=false}
}

async function recheckPlex(){
  busy.value=true;
  try{
    const media=detail.value.media||{};
    await api(`/api/media/recheck-plex?${media.library_id?`library_id=${media.library_id}`:`request_id=${media.request_id}`}`,{method:'POST'});
    await load();emit('updated');
  }catch(e){error.value=e.message}finally{busy.value=false}
}

async function reportIssue(issueMessage){
  busy.value=true;
  try{
    const media=detail.value.media||{};
    await api('/api/media/issues',{method:'POST',body:JSON.stringify({library_id:media.library_id,request_id:media.request_id,issue_type:'other',message:issueMessage})});
    showIssueForm.value=false;
    await load();emit('updated');
  }catch(e){error.value=e.message}finally{busy.value=false}
}

async function sendCorrection(formPayload){
  busy.value=true;error.value='';
  try{
    const media=detail.value.media||{};
    await api('/api/media/send-correction',{method:'POST',body:JSON.stringify({...formPayload, library_id:media.library_id, request_id:media.request_id})});
    showCorrectionForm.value=false;
    alert('Correction envoyee !');
  }catch(e){error.value=e.message}finally{busy.value=false}
}

watch(()=>props.item,load,{deep:true});
onMounted(load);
</script>
