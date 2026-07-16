<template>
  <DrawerShell :eyebrow="typeLabel" :title="detail?.title || 'Chargement...'" :error="error" @close="$emit('close')">
      <template #background>
        <div v-if="detail?.backdrop_url" class="modal-bg" :style="{ backgroundImage: `url(${detail.backdrop_url})` }"></div>
      </template>
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
            <div v-if="admin" class="add-requester-row">
              <span class="add-requester-label">Co-demandeur</span>
              <div class="inline-row compact">
                <select v-model="newRequesterId" :disabled="!addableUsers.length">
                  <option value="">{{ addableUsers.length ? 'Sélectionnez un utilisateur' : 'Tous les utilisateurs sont déjà demandeurs' }}</option>
                  <option v-for="u in addableUsers" :key="u.plex_user_id" :value="u.plex_user_id">{{ u.custom_name || u.display_name || u.plex_user_id }}</option>
                </select>
                <button class="primary" :disabled="busy || !newRequesterId" @click="addRequester"><PlusCircle/> Ajouter</button>
              </div>
            </div>
            <article v-for="row in detail.requests || []" :key="row.id" class="detail-row request-detail-row">
              <div>
                <div class="request-detail-top">
                  <strong>{{ row.requested_by || row.plex_user || row.plex_user_id }}</strong>
                  <span class="badge status-tag" :class="row.status">{{ requestStatusLabel(row.status) }}</span>
                </div>

                <div v-if="!['failed','rejected'].includes(row.status)" class="status-stepper">
                  <span v-for="step in statusSteps" :key="step.key" :class="['step', stepState(row, step.key)]">{{ step.label }}</span>
                </div>

                <details class="mail-history-details">
                  <summary>Historique</summary>
                  <small>Demandee le {{ formatDate(row.requested_at) }}</small>
                  <small v-if="row.arr_processed_at" class="mail-history">
                    Validee par *arr le {{ formatDateTime(row.arr_processed_at) }}
                  </small>
                  <small v-if="row.last_request_mail" class="mail-history">
                    Mail demande {{ formatDateTime(row.last_request_mail.sent_at) }} ({{ row.last_request_mail.triggered_by === 'manual' ? 'manuel' : 'auto' }})
                    <span v-if="row.last_request_mail.success === false" class="badge failed tiny">Echec</span>
                  </small>
                  <small v-if="row.available_at" class="mail-history">
                    Disponible le {{ formatDateTime(row.available_at) }}
                  </small>
                  <small v-if="row.last_available_mail" class="mail-history">
                    Mail dispo {{ formatDateTime(row.last_available_mail.sent_at) }} ({{ row.last_available_mail.triggered_by === 'manual' ? 'manuel' : 'auto' }})
                    <span v-if="row.last_available_mail.success === false" class="badge failed tiny">Echec</span>
                  </small>
                  <small v-if="row.vf_tracking_disabled" class="mail-history">Suivi VF arrete</small>
                </details>

                <div v-if="(row.requester_ids || []).length > 1" class="requester-breakdown">
                  <div v-for="(uid, idx) in row.requester_ids" :key="`${uid}-${idx}`" class="requester-line">
                    <span class="requester-name">
                      {{ row.requesters?.[idx] || uid }}
                      <span v-if="idx === 0" class="badge tiny">Principal</span>
                      <span
                        v-if="notifiedStatus(row, uid) !== null"
                        :class="['notif-dot', notifiedStatus(row, uid) ? 'ok' : 'pending']"
                        :title="notifiedStatus(row, uid) ? 'Deja notifie' : 'Pas encore notifie'"
                      ></span>
                    </span>
                    <div v-if="admin" class="requester-menu-wrap">
                      <button class="icon-button" title="Actions" @click.stop="toggleRequesterMenu(row.id, uid)"><MoreVertical /></button>
                      <div v-if="openRequesterMenu === `${row.id}:${uid}`" class="requester-menu" @click.stop>
                        <button :disabled="busy" @click="notifyUser(row.id, uid, ['request']); closeRequesterMenu()"><Mail /> Renvoyer mail demande</button>
                        <button v-if="row.status === 'available'" :disabled="busy" @click="notifyUser(row.id, uid, ['available']); closeRequesterMenu()"><MailCheck /> Renvoyer mail dispo</button>
                        <button v-if="idx !== 0" :disabled="busy" @click="promoteRequester(row, uid); closeRequesterMenu()"><Crown /> Promouvoir principal</button>
                        <button class="danger" :disabled="busy" @click="removeRequester(row, uid); closeRequesterMenu()"><UserMinus /> Retirer</button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <div class="actions">
                <button v-if="row.arr_id" class="icon-button" title="Rechercher une release" @click="router.push(`/releases/${row.id}`)"><Search /></button>
                <button v-if="row.status === 'failed'" class="icon-button" title="Relancer" @click="requestAction(row.id, 'retry')"><RotateCcw /></button>
                <button v-if="admin && hasUnnotified(row)" class="icon-button" title="Rattraper tout le monde (notifier les demandeurs pas encore prevenus)" :disabled="busy" @click="catchUpAll(row)"><Users /></button>
                <button class="icon-button" :title="(row.requester_ids || []).length > 1 ? 'Renvoyer le mail de demande a tous' : 'Renvoyer email de demande'" :disabled="busy" @click="resendMail(row.id, 'request')"><Mail /></button>
                <button v-if="row.status === 'available'" class="icon-button" :title="(row.requester_ids || []).length > 1 ? 'Renvoyer le mail de disponibilite a tous' : 'Renvoyer email de disponibilite'" :disabled="busy" @click="resendMail(row.id, 'available')"><MailCheck /></button>
                <button v-if="canClose(row)" class="icon-button" title="Cloturer la demande" :disabled="busy" @click="closeRequest(row)"><CheckCheck /></button>
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
              :available="Boolean(detail?.in_library)"
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
  </DrawerShell>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { CalendarDays, CheckCheck, Crown, LoaderCircle, Mail, MailCheck, MoreVertical, PlusCircle, RefreshCw, RotateCcw, Search, Trash2, MessageSquareWarning, UserMinus, Users } from "@lucide/vue";
import { useRouter } from "vue-router";
import { api } from "@/api";
import DrawerShell from "./DrawerShell.vue";
import MediaHero from "./media/MediaHero.vue";
import MediaAudioSection from "./media/MediaAudioSection.vue";
import MediaIssueForm from "./media/MediaIssueForm.vue";
import MediaCorrectionForm from "./media/MediaCorrectionForm.vue";

const props=defineProps({item:{type:Object,required:true},mode:{type:String,default:'library'}});
const emit=defineEmits(['close','updated','select']);
const router=useRouter();
const detail=ref(null),requesters=ref([]),folders=ref([]),vfDetail=ref(null),loading=ref(false),busy=ref(false),error=ref(''),tab=ref('summary');
const requestForm=reactive({plex_user_id:'',root_folder:'',seasons:[]});
const tabs=['summary','requests','calendar'];
const admin = ref(false);

const showIssueForm=ref(false),showCorrectionForm=ref(false);
const users=ref([]),correctionOptions=ref([]);
const correctionForm=reactive({scope:'media',season_number:null,episode_number:null,recipient_user_ids:[],corrections:[],note:''});
const newRequesterId=ref('');
const openRequesterMenu=ref(null);
const statusSteps=[{key:'requested',label:'Demandee'},{key:'sent',label:'Transmise'},{key:'available',label:'Disponible'}];

const typeLabel=computed(()=>detail.value?.media_type==='show'?'Serie':'Film');
const statusLabel=computed(()=>detail.value?.available||detail.value?.in_library?'Disponible':detail.value?.requested?'Deja demande':detail.value?.request_status||'');
const statusClass=computed(()=>detail.value?.available||detail.value?.in_library?'available':'pending');
const canRequest=computed(()=>props.mode==='discover'&&!detail.value?.available&&!detail.value?.in_library&&!detail.value?.requested);
const seasonNumbers=computed(()=>Array.from({length:Number(detail.value?.number_of_seasons||0)},(_,i)=>i+1));
const recommendations=computed(()=>[...(detail.value?.recommendations||[]),...(detail.value?.similar||[])].slice(0,6));
const addableUsers=computed(()=>{
  const already=new Set((detail.value?.requests||[]).flatMap(row=>row.requester_ids||[row.plex_user_id]));
  return users.value.filter(u=>!already.has(u.plex_user_id));
});

function tabLabel(value){return ({summary:'Resume',requests:'Demandes',calendar:'Calendrier'})[value]}
function formatDate(value){return value?new Intl.DateTimeFormat('fr-FR',{dateStyle:'medium'}).format(new Date(value)):'-'}
function formatDateTime(value){return value?new Intl.DateTimeFormat('fr-FR',{dateStyle:'medium',timeStyle:'short'}).format(new Date(value)):'-'}
function requestStatusLabel(value){
  return ({
    pending_approval: 'A approuver',
    pending: 'En attente',
    sent_to_arr: 'Transmise',
    available: 'Disponible',
    failed: 'Erreur',
    rejected: 'Refusee'
  })[value] || value;
}
function mediaPath(){const source=props.item;if(props.mode==='discover'){const p=new URLSearchParams();p.set('media_type',source.media_type);if(source.tmdb_id)p.set('tmdb_id',source.tmdb_id);else if(source.tvdb_id)p.set('tvdb_id',source.tvdb_id);else p.set('tmdb_id',source.id);return `/api/discover/detail?${p}`}if(props.mode==='request')return `/api/media/detail?request_id=${source.id}`;const id=source.library_id||source.id;return `/api/media/detail?library_id=${id}`}

async function loadUsers(){
  try{
    users.value=await api('/api/users');
    correctionOptions.value=await api('/api/media/corrections/options');
  }catch(e){}
}

async function loadSession(){
  try{
    const session=await api('/api/session');
    admin.value=Boolean(session?.is_owner||session?.role==='admin');
  }catch(e){admin.value=false}
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
    Promise.all([loadVf(), loadUsers(), loadSession()]).catch(()=>{});
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

function canClose(row){
  // Force une demande bloquee (pending/failed/...) vers "disponible", OU cloture le
  // suivi VF d'une demande deja disponible qui n'a pas encore confirme la VF.
  return row.status !== 'available' || (row.has_vf !== true && !row.vf_tracking_disabled);
}

async function closeRequest(row){
  const notify = confirm('Notifier la disponibilite par email au demandeur ?');
  let stopVfTracking = false;
  if(row.has_vf !== true){
    stopVfTracking = confirm("Arreter aussi la surveillance VO -> VF pour cette demande ? Elle ne sera plus jamais re-verifiee.");
  }
  busy.value=true;
  try{
    await api(`/api/requests/${row.id}/mark-processed?event=available&notify=${notify}&stop_vf_tracking=${stopVfTracking}`,{method:'POST'});
    await load();emit('updated');
  }catch(e){error.value=e.message}finally{busy.value=false}
}

async function resendMail(id, event){
  busy.value=true;
  try{await api(`/api/requests/${id}/resend-mail?event=${event}`,{method:'POST'});await load();emit('updated')}
  catch(e){error.value=e.message}finally{busy.value=false}
}

async function notifyUser(requestId, plexUserId, events){
  busy.value=true;error.value='';
  try{
    await api(`/api/requests/${requestId}/notify-user`,{method:'POST',body:JSON.stringify({plex_user_id:plexUserId,events})});
    await load();emit('updated');
  }catch(e){error.value=e.message}finally{busy.value=false}
}

async function addRequester(){
  busy.value=true;error.value='';
  try{
    const rows = detail.value.requests || [];
    const newUserId = newRequesterId.value;
    // Capture AVANT modification : c'est l'etat "deja en cours" qui determine si on
    // doit proposer un rattrapage retroactif, pas l'etat apres ajout.
    const rowsAlreadyInProgress = rows.filter(row => row.request_mail_sent || row.status === 'available');
    for (const row of rows) {
      const ids = [...(row.requester_ids || [row.plex_user_id])];
      if (!ids.includes(newUserId)) ids.push(newUserId);
      await api(`/api/requests/${row.id}/requesters`,{method:'PUT',body:JSON.stringify({requester_ids:ids})});
    }
    await load();
    newRequesterId.value='';
    emit('updated');
    if (rowsAlreadyInProgress.length && confirm("Cette demande est deja en cours. Renvoyer retroactivement au nouveau co-demandeur le(s) mail(s) deja envoye(s) (demande/disponibilite) ? Sinon, il ne recevra que les prochaines notifications.")) {
      for (const row of rowsAlreadyInProgress) {
        const events = [];
        if (row.request_mail_sent) events.push('request');
        if (row.status === 'available') events.push('available');
        if (events.length) await notifyUser(row.id, newUserId, events);
      }
    }
  }catch(e){error.value=e.message}finally{busy.value=false}
}

function stepState(row, key){
  const order=['requested','sent','available'];
  const statusIndex=row.status==='available'?2:row.status==='sent_to_arr'?1:0;
  const keyIndex=order.indexOf(key);
  if(keyIndex<statusIndex)return'done';
  if(keyIndex===statusIndex)return'current';
  return'upcoming';
}

function notifiedStatus(row, uid){
  const n=row.requester_notifications?.[uid];
  if(!n)return null;
  return row.status==='available'?n.available:n.request;
}

function hasUnnotified(row){
  return (row.requester_ids||[]).some(uid=>notifiedStatus(row,uid)===false);
}

async function catchUpAll(row){
  busy.value=true;error.value='';
  try{
    for (const uid of row.requester_ids||[]) {
      if (notifiedStatus(row,uid)!==false) continue;
      const events=row.status==='available'?['available']:['request'];
      await api(`/api/requests/${row.id}/notify-user`,{method:'POST',body:JSON.stringify({plex_user_id:uid,events})});
    }
    await load();emit('updated');
  }catch(e){error.value=e.message}finally{busy.value=false}
}

async function promoteRequester(row, uid){
  busy.value=true;error.value='';
  try{
    const ids=[uid, ...(row.requester_ids||[]).filter(id=>id!==uid)];
    await api(`/api/requests/${row.id}/requesters`,{method:'PUT',body:JSON.stringify({requester_ids:ids})});
    await load();emit('updated');
  }catch(e){error.value=e.message}finally{busy.value=false}
}

async function removeRequester(row, uid){
  if(!confirm('Retirer ce demandeur de la liste ?'))return;
  busy.value=true;error.value='';
  try{
    const ids=(row.requester_ids||[]).filter(id=>id!==uid);
    await api(`/api/requests/${row.id}/requesters`,{method:'PUT',body:JSON.stringify({requester_ids:ids})});
    await load();emit('updated');
  }catch(e){error.value=e.message}finally{busy.value=false}
}

function toggleRequesterMenu(rowId, uid){
  const key=`${rowId}:${uid}`;
  openRequesterMenu.value=openRequesterMenu.value===key?null:key;
}
function closeRequesterMenu(){openRequesterMenu.value=null}
function handleOutsideClick(event){
  if(!event.target.closest('.requester-menu-wrap'))closeRequesterMenu();
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
onMounted(()=>{load();document.addEventListener('click',handleOutsideClick)});
onBeforeUnmount(()=>document.removeEventListener('click',handleOutsideClick));
</script>

<style scoped>
.add-requester-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}
.add-requester-label {
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
}
.add-requester-row .inline-row {
  flex: 1;
}
.add-requester-row select {
  flex: 1;
  min-width: 0;
}

.request-detail-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.request-detail-row .mail-history {
  display: block;
  color: var(--muted);
}

.status-stepper {
  display: flex;
  align-items: center;
  gap: 4px;
  margin: 6px 0;
}
.status-stepper .step {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--border);
  color: var(--muted);
  background: var(--surface-2);
}
.status-stepper .step.done {
  border-color: rgba(34, 197, 94, .45);
  color: var(--green);
}
.status-stepper .step.current {
  border-color: var(--accent);
  color: var(--accent);
  font-weight: 600;
}

.mail-history-details {
  margin-top: 4px;
}
.mail-history-details summary {
  cursor: pointer;
  font-size: 11px;
  color: var(--muted);
  user-select: none;
}
.mail-history-details small {
  display: block;
}

.requester-breakdown {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--border);
}

.requester-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
}

.requester-name {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.badge.tiny {
  min-height: auto;
  padding: 0 6px;
  font-size: 10px;
}

.notif-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.notif-dot.ok {
  background: var(--green);
}
.notif-dot.pending {
  background: var(--muted);
}

.requester-menu-wrap {
  position: relative;
}
.requester-menu {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  z-index: 30;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 200px;
  padding: 6px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}
.requester-menu button {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: 0;
  background: transparent;
  color: var(--text);
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  text-align: left;
}
.requester-menu button:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.06);
}
.requester-menu button.danger {
  color: var(--red);
}
</style>
