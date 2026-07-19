<template>
  <section class="panel email-studio">
    <div class="panel-head studio-head">
      <div><h2>Modeles d'emails</h2><p>Declencheurs, contenu et simulation des destinataires.</p></div>
      <div class="actions">
        <button v-if="hasPrevious" class="secondary" :disabled="busy" @click="restorePrevious"><Undo2/>Version precedente</button>
        <button class="secondary" :disabled="busy" @click="reset"><RotateCcw/>Valeurs par defaut</button>
        <button class="primary" :disabled="busy" @click="save"><Save/>Enregistrer</button>
      </div>
    </div>

    <p v-if="error" class="notice error-text">{{ error }}</p>
    <p v-if="message" class="notice success-text">{{ message }}</p>

    <div class="simulation-bar">
      <label>Utilisateur simule
        <select v-model="previewUser">
          <option value="">Utilisateur exemple</option>
          <option v-for="user in users" :key="user.id" :value="user.id">{{ userName(user) }}</option>
        </select>
      </label>
      <label v-if="!showAppearance">Scenario
        <select v-model="previewVariant">
          <option v-for="scenario in scenarios" :key="scenario.value" :value="scenario.value">{{ scenario.label }}</option>
        </select>
      </label>
      <div class="view-switch" aria-label="Mode d'affichage">
        <button v-for="mode in viewModes" :key="mode.key" :class="{active:viewMode===mode.key}" @click="viewMode=mode.key"><component :is="mode.icon"/>{{ mode.label }}</button>
      </div>
      <label v-if="viewMode!=='edit'">Format
        <select v-model="deviceMode"><option value="desktop">Ordinateur</option><option value="tablet">Tablette</option><option value="phone">Telephone</option></select>
      </label>
    </div>

    <div v-if="selectedUser" class="simulation-result" :class="eligibility.ok?'eligible':'ineligible'">
      <component :is="eligibility.ok ? CircleCheck : CircleAlert"/>
      <div><strong>{{ eligibility.title }}</strong><span>{{ eligibility.detail }}</span></div>
    </div>

    <label class="mobile-model-select">Modele
      <select :value="showAppearance?'appearance':eventType" @change="selectMobile($event.target.value)">
        <optgroup v-for="group in eventGroups" :key="group.label" :label="group.label">
          <option v-for="entry in group.items" :key="entry.key" :value="entry.key">{{ entry.label }}</option>
        </optgroup>
        <option value="appearance">Apparence generale</option>
      </select>
    </label>

    <div class="studio-layout" :class="`mode-${viewMode}`">
      <aside class="template-sidebar">
        <div v-for="group in eventGroups" :key="group.label" class="template-group">
          <span>{{ group.label }}</span>
          <button v-for="entry in group.items" :key="entry.key" :class="{active:!showAppearance&&eventType===entry.key}" @click="selectEvent(entry.key)">
            <component :is="entry.icon"/><span>{{ entry.label }}<small>{{ entry.description }}</small></span>
          </button>
        </div>
        <div class="template-group">
          <span>Presentation</span>
          <button :class="{active:showAppearance}" @click="showAppearance=true"><Palette/><span>Apparence generale<small>En-tete, affiche, couleurs et pied de page</small></span></button>
        </div>
      </aside>

      <main v-if="viewMode!=='preview'" class="studio-editor">
        <template v-if="!showAppearance">
          <header class="editor-title"><div><h3>{{ currentEvent.label }}</h3><p>{{ currentEvent.description }}</p></div><span class="badge">{{ modelState }}</span></header>
          <EmailEventEditor :model="current" :variables="currentVariables" :appearance-editable="!seriesEventTypes.includes(eventType)" />
        </template>
        <template v-else>
          <header class="editor-title"><div><h3>Apparence generale</h3><p>Presentation partagee par tous les emails.</p></div></header>
          <EmailSharedSettings :shared="shared" :variables="variables" />
        </template>
        <div class="studio-actions">
          <button class="secondary" :disabled="previewing" @click="preview"><Eye/>Actualiser l'apercu</button>
          <button class="secondary" :disabled="busy" @click="testSend('admin')"><Send/>Tester vers l'admin</button>
          <button v-if="selectedUser" class="secondary" :disabled="busy" @click="testSend('user')"><UserRoundCheck/>Tester vers cet utilisateur</button>
          <button class="primary" :disabled="busy" @click="save"><Save/>Enregistrer</button>
        </div>
      </main>

      <EmailPreviewPanel v-if="viewMode!=='edit'" :preview-html="previewHtml" :event-label="showAppearance?'Apparence':currentEvent.label" :device-mode="deviceMode" />
    </div>
  </section>
  <ConfirmModal v-bind="confirmDialog" @cancel="resolveConfirm(false)" @confirm="resolveConfirm(true)" />
</template>

<script setup>
import { computed, markRaw, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { CircleAlert,CircleCheck,Eye,FileWarning,Film,LayoutPanelLeft,MailCheck,Monitor,Palette,RotateCcw,Save,Send,ShieldAlert,Sparkles,Tv,Undo2,UserRoundCheck } from '@lucide/vue';
import { api } from '@/api';
import EmailEventEditor from './email/EmailEventEditor.vue';
import EmailSharedSettings from './email/EmailSharedSettings.vue';
import EmailPreviewPanel from './email/EmailPreviewPanel.vue';
import ConfirmModal from './ConfirmModal.vue';
import { useConfirm } from '@/composables/useConfirm';

const seriesEventTypes=['episode_available','season_started','season_partial','season_complete','series_partial','series_complete'];
const eventGroups=[
  {label:'Demandes',items:[
    {key:'request',label:'Demande enregistree',description:'Confirmation de la demande',icon:markRaw(MailCheck)},
    {key:'failure',label:'Echec de transmission',description:'Envoi vers Sonarr ou Radarr impossible',icon:markRaw(FileWarning)},
  ]},
  {label:'Disponibilite',items:[
    {key:'available',label:'Film disponible',description:'Premiere disponibilite du film',icon:markRaw(Film)},
    {key:'episode_available',label:'Episode disponible',description:'Un episode isole',icon:markRaw(Tv)},
    {key:'season_started',label:'Saison demarree',description:'Premier episode de la saison',icon:markRaw(Tv)},
    {key:'season_partial',label:'Saison partielle',description:'Plusieurs episodes, saison incomplete',icon:markRaw(Tv)},
    {key:'season_complete',label:'Saison complete',description:'Une saison entierement disponible',icon:markRaw(Tv)},
    {key:'series_partial',label:'Plusieurs saisons',description:'Certaines saisons seulement',icon:markRaw(Tv)},
    {key:'series_complete',label:'Serie complete',description:'Toutes les saisons attendues',icon:markRaw(Tv)},
  ]},
  {label:'Suivi et administration',items:[
    {key:'upgrade',label:'Amelioration VF',description:'Passage connu de VO vers VF',icon:markRaw(Sparkles)},
    {key:'correction',label:'Correction',description:'Message manuel de correction',icon:markRaw(ShieldAlert)},
  ]},
];
const eventTypes=eventGroups.flatMap(group=>group.items);
const scenarioMap={
  available:[{value:'movie_generic',label:'Film sans langue'},{value:'movie_vo',label:'Film en VO'},{value:'movie_vf',label:'Film en VF'}],
  episode_available:[{value:'default',label:'Episode generique'},{value:'episode_vo',label:'Episode en VO'},{value:'episode_vf',label:'Episode en VF'}],
  season_started:[{value:'default',label:'Premier episode'},{value:'season_start_vf',label:'Premier episode en VF'}],
  season_partial:[{value:'default',label:'6 episodes sur 10'}],
  season_complete:[{value:'default',label:'Une saison sur plusieurs'},{value:'season_complete_vf',label:'Saison complete en VF'}],
  series_partial:[{value:'default',label:'3 saisons completes sur 5'}],
  series_complete:[{value:'default',label:'Toutes les saisons completes'}],
  upgrade:[{value:'movie_vf',label:'Film passe en VF'},{value:'episode_vf',label:'Episode passe en VF'},{value:'season_complete_vf',label:'Saison passee en VF'}],
  request:[{value:'default',label:'Nouvelle demande'}],failure:[{value:'default',label:'Sonarr indisponible'}],correction:[{value:'default',label:'Correction manuelle'}],
};
const variables=[
  {tag:'{titre}',description:"Titre de l'oeuvre"},{tag:'{type}',description:'Le film ou La serie'},{tag:'{media_type_et_titre}',description:'Type et titre combines'},{tag:'{annee}',description:'Annee de sortie'},{tag:'{affiche}',description:"URL de l'affiche"},{tag:'{details_saison_episode}',description:'Saison et episode'},{tag:'{langue}',description:'Version VF ou VO'},{tag:'{nom_utilisateur}',description:'Nom du demandeur'},{tag:'{synopsis}',description:'Resume du media'},{tag:'{raison}',description:"Raison de l'echec"},{tag:'{corrections}',description:'Corrections appliquees'},{tag:'{note_correction}',description:'Note de correction'},{tag:'{resume_disponibilite}',description:'Resume complet de la disponibilite'},{tag:'{saisons_disponibles}',description:'Numeros des saisons disponibles'},{tag:'{saisons_completes}',description:'Numeros des saisons completes'},{tag:'{saisons_partielles}',description:'Numeros des saisons partielles'},{tag:'{saisons_manquantes}',description:'Numeros des saisons encore absentes'},{tag:'{nombre_saisons_disponibles}',description:'Nombre de saisons disponibles'},{tag:'{nombre_saisons_completes}',description:'Nombre de saisons completes'},{tag:'{nombre_saisons_attendues}',description:'Nombre total de saisons attendues'},{tag:'{nombre_episodes_disponibles}',description:'Nombre d episodes disponibles dans le lot'},
];
const variableTags={request:['{titre}','{type}','{annee}','{nom_utilisateur}','{synopsis}'],failure:['{titre}','{raison}','{nom_utilisateur}'],correction:['{titre}','{details_saison_episode}','{corrections}','{note_correction}','{nom_utilisateur}']};
const viewModes=[{key:'edit',label:'Edition',icon:markRaw(Monitor)},{key:'split',label:'Partagee',icon:markRaw(LayoutPanelLeft)},{key:'preview',label:'Apercu',icon:markRaw(Eye)}];
const eventType=ref('request'),showAppearance=ref(false),viewMode=ref('split'),deviceMode=ref('desktop'),users=ref([]),previewHtml=ref(''),previewVariant=ref('default'),previewUser=ref('');
const error=ref(''),message=ref(''),busy=ref(false),previewing=ref(false),hasPrevious=ref(false),simulationSettings=ref({});
let timer;
const models=reactive(Object.fromEntries(eventTypes.map(entry=>[entry.key,{template:'',subject:'',accent_color:'#e5a00d',badge_text:'',headline_text:'',show_synopsis:true,initialTemplate:'',initialSubject:''}])));
const shared=reactive({email_header_brand:'PLEXARR',email_header_subtitle:'Notification Plex',email_footer_template:'',email_brand_color:'#e5a00d',email_show_poster:true,email_show_genres:true,email_show_requester:true,email_show_header_subtitle:true,email_requester_label:'Demande par',email_poster_width:100,email_media_layout:'left',email_bg_color:'#0d0d0d',email_card_bg_color:'#141414',email_font_family:'arial',email_card_width:600,email_card_border_radius:10,email_synopsis_font_size:'normal',email_show_tmdb_link:true,email_show_plex_button:true});
const {dialog:confirmDialog,askConfirm,resolveConfirm}=useConfirm();
const current=computed(()=>models[eventType.value]);
const currentEvent=computed(()=>eventTypes.find(entry=>entry.key===eventType.value)||eventTypes[0]);
const scenarios=computed(()=>scenarioMap[eventType.value]||scenarioMap.request);
const selectedUser=computed(()=>users.value.find(user=>String(user.id)===String(previewUser.value))||null);
const modelState=computed(()=>current.value.template!==current.value.initialTemplate||current.value.subject!==current.value.initialSubject?'Modifie':'Enregistre');
const currentVariables=computed(()=>{const tags=variableTags[eventType.value];if(!tags)return variables;return variables.filter(item=>tags.includes(item.tag))});
const eligibility=computed(()=>simulateEligibility(selectedUser.value));

function userName(user){return user.custom_name||user.display_name||user.plex_user_id}
function inherited(user,key,fallback){return user?.[key]??fallback}
function simulateEligibility(user){
  if(!user)return{ok:true,title:'Apercu avec un utilisateur exemple',detail:'Selectionnez un utilisateur pour simuler ses preferences reelles.'};
  const s=simulationSettings.value;
  if(!s.email_enabled)return{ok:false,title:'Email non envoye',detail:'Le canal email est desactive globalement.'};
  if(s.notification_hold_enabled)return{ok:false,title:'Email conserve dans la file',detail:'La bascule de blocage des notifications est active.'};
  if(user.enabled===false)return{ok:false,title:'Email non envoye',detail:'Cet utilisateur est desactive.'};
  const requestEvent=eventType.value==='request',failureEvent=eventType.value==='failure';
  if(requestEvent&&(!s.email_on_request||user.notify_on_request===false))return{ok:false,title:'Email non envoye',detail:'Les confirmations de demande sont desactivees pour cet utilisateur.'};
  if(failureEvent&&!s.email_on_failure)return{ok:false,title:'Email non envoye',detail:'Les notifications d echec sont desactivees globalement.'};
  if(!requestEvent&&!failureEvent&&eventType.value!=='upgrade'&&(!s.email_on_available||user.notify_on_available===false))return{ok:false,title:'Email non envoye',detail:'Les notifications de disponibilite sont desactivees pour cet utilisateur.'};
  if(eventType.value==='upgrade'&&!s.email_on_vf_available)return{ok:false,title:'Email non envoye',detail:'Les notifications d amelioration VF sont desactivees globalement.'};
  const languageScenario=previewVariant.value.includes('_vf')||eventType.value==='upgrade';
  const movieScenario=eventType.value==='available'||(eventType.value==='upgrade'&&previewVariant.value==='movie_vf');
  const vfPreference=movieScenario?user.notify_vf_movie:user.notify_vf_series;
  if(languageScenario&&vfPreference===false)return{ok:false,title:'Email non envoye',detail:`Le suivi VF des ${movieScenario?'films':'series'} est desactive pour cet utilisateur.`};
  const granularity=inherited(user,'series_notify_granularity',s.series_notify_granularity||'jalons');
  if(eventType.value==='episode_available'&&granularity!=='tout')return{ok:false,title:'Email non envoye',detail:`Granularite ${granularity} : les episodes individuels ne sont pas annonces.`};
  if(['season_started','season_partial','season_complete'].includes(eventType.value)&&granularity==='minimal')return{ok:false,title:'Email non envoye',detail:'Granularite minimale : seule la serie complete est annoncee.'};
  const address=user.notification_email||user.plex_email;
  if(!address&&!s.has_fallback_recipient)return{ok:false,title:'Email non envoye',detail:'Aucune adresse utilisateur ni adresse de repli.'};
  return{ok:true,title:'Email envoye a cet utilisateur',detail:`Destinataire : ${address||'adresse SMTP de repli'}${user.notify_admin&&s.has_admin_recipient?' · administrateur en copie':''}.`};
}
function selectEvent(key){eventType.value=key;showAppearance.value=false;previewVariant.value=(scenarioMap[key]||scenarioMap.request)[0].value}
function selectMobile(key){if(key==='appearance')showAppearance.value=true;else selectEvent(key)}
function payload(){const data={...shared};for(const entry of eventTypes){const model=models[entry.key];data[`email_${entry.key}_template`]=model.template;data[`email_${entry.key}_subject`]=model.subject||null;data[`email_${entry.key}_accent_color`]=model.accent_color||null;data[`email_${entry.key}_badge_text`]=model.badge_text||null;data[`email_${entry.key}_headline_text`]=model.headline_text||null;data[`email_${entry.key}_show_synopsis`]=model.show_synopsis}return data}
function previewPayload(extra={}){return{template:current.value.template,subject:current.value.subject,type:eventType.value,user_id:previewUser.value||null,preview_variant:previewVariant.value,header_brand:shared.email_header_brand,header_subtitle:shared.email_header_subtitle,footer_template:shared.email_footer_template,brand_color:shared.email_brand_color,show_header_subtitle:shared.email_show_header_subtitle,show_poster:shared.email_show_poster,show_genres:shared.email_show_genres,show_requester:shared.email_show_requester,requester_label:shared.email_requester_label,poster_width:shared.email_poster_width,media_layout:shared.email_media_layout,bg_color:shared.email_bg_color,card_bg_color:shared.email_card_bg_color,font_family:shared.email_font_family,card_width:shared.email_card_width,card_border_radius:shared.email_card_border_radius,synopsis_font_size:shared.email_synopsis_font_size,show_tmdb_link:shared.email_show_tmdb_link,show_plex_button:shared.email_show_plex_button,accent_color:current.value.accent_color,badge_text:current.value.badge_text,headline_text:current.value.headline_text,show_synopsis:current.value.show_synopsis,...extra}}
function fill(data){for(const entry of eventTypes){const model=models[entry.key];model.template=data[`email_${entry.key}_template`]||'';model.subject=data[`email_${entry.key}_subject`]||'';model.initialTemplate=model.template;model.initialSubject=model.subject;model.accent_color=data[`email_${entry.key}_accent_color`]||data.email_available_accent_color||'#e5a00d';model.badge_text=data[`email_${entry.key}_badge_text`]||data.email_available_badge_text||'';model.headline_text=data[`email_${entry.key}_headline_text`]||data.email_available_headline_text||'';model.show_synopsis=data[`email_${entry.key}_show_synopsis`]!==false}for(const key of Object.keys(shared))if(data[key]!=null)shared[key]=data[key];hasPrevious.value=Boolean(data.has_previous_version);simulationSettings.value=data.simulation_settings||{}}
async function load(){error.value='';try{const[templates,userRows]=await Promise.all([api('/api/email-templates'),api('/api/users')]);users.value=userRows;fill(templates);await preview()}catch(e){error.value=e.message}}
async function save(){busy.value=true;error.value='';try{await api('/api/email-templates',{method:'PUT',body:JSON.stringify(payload())});message.value='Modeles enregistres.';hasPrevious.value=true;for(const model of Object.values(models)){model.initialTemplate=model.template;model.initialSubject=model.subject}await preview()}catch(e){error.value=e.message}finally{busy.value=false}}
async function reset(){if(!await askConfirm({title:'Retablir tous les modeles ?',message:'Tous les contenus et reglages visuels seront remplaces par leurs valeurs par defaut.',confirmLabel:'Retablir',danger:true}))return;busy.value=true;try{await api('/api/email-templates/reset',{method:'POST'});await load();message.value='Modeles retablis.'}catch(e){error.value=e.message}finally{busy.value=false}}
async function restorePrevious(){busy.value=true;try{await api('/api/email-templates/restore-previous',{method:'POST'});await load();message.value='Version precedente restauree.'}catch(e){error.value=e.message}finally{busy.value=false}}
async function preview(){clearTimeout(timer);previewing.value=true;try{const response=await fetch('/api/email-preview',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(previewPayload())});if(!response.ok)throw new Error((await response.json()).detail);previewHtml.value=await response.text()}catch(e){error.value=e.message}finally{previewing.value=false}}
function schedulePreview(){clearTimeout(timer);timer=setTimeout(preview,500)}
async function testSend(mode){if(mode==='user'&&!await askConfirm({title:'Envoyer le test a cet utilisateur ?',message:`Un email reel sera envoye a ${userName(selectedUser.value)}.`,confirmLabel:'Envoyer'}))return;busy.value=true;try{const data=await api('/api/email-templates/test-send',{method:'POST',body:JSON.stringify(previewPayload({recipient_mode:mode}))});message.value=data.message}catch(e){error.value=e.message}finally{busy.value=false}}
watch([eventType,previewVariant,previewUser],schedulePreview);watch(shared,schedulePreview,{deep:true});watch(models,schedulePreview,{deep:true});onMounted(load);onBeforeUnmount(()=>clearTimeout(timer));
</script>

<style scoped>
.email-studio{display:grid;gap:16px}.studio-head{align-items:flex-start}.simulation-bar{display:flex;gap:10px;align-items:end;flex-wrap:wrap;padding:12px;background:var(--surface-2);border:1px solid var(--border);border-radius:8px}.simulation-bar label{display:grid;gap:5px;min-width:180px;font-size:12px;color:var(--muted)}.simulation-bar select{width:100%}.view-switch{display:flex;border:1px solid var(--border);border-radius:7px;overflow:hidden}.view-switch button{display:flex;gap:6px;align-items:center;border:0;border-right:1px solid var(--border);border-radius:0;background:transparent;color:var(--muted);padding:9px 11px}.view-switch button:last-child{border-right:0}.view-switch button.active{background:var(--accent);color:#111}.view-switch svg,.template-sidebar svg{width:16px}.simulation-result{display:flex;gap:10px;align-items:center;padding:11px 13px;border-radius:8px;border:1px solid}.simulation-result svg{width:20px;flex:none}.simulation-result div{display:grid;gap:2px}.simulation-result span{font-size:12px}.simulation-result.eligible{border-color:rgba(34,197,94,.35);background:rgba(34,197,94,.08);color:var(--success)}.simulation-result.ineligible{border-color:rgba(239,68,68,.35);background:rgba(239,68,68,.08);color:var(--danger)}.studio-layout{display:grid;grid-template-columns:240px minmax(0,1fr) minmax(340px,.85fr);gap:14px;align-items:start}.studio-layout.mode-edit{grid-template-columns:240px minmax(0,1fr)}.studio-layout.mode-preview{grid-template-columns:240px minmax(0,1fr)}.template-sidebar{position:sticky;top:16px;display:grid;gap:15px;max-height:calc(100vh - 32px);overflow:auto;padding-right:4px}.template-group{display:grid;gap:4px}.template-group>span{text-transform:uppercase;letter-spacing:.08em;font-size:10px;color:var(--muted);padding:0 8px 4px}.template-group button{display:flex;gap:9px;text-align:left;align-items:flex-start;border:0;background:transparent;color:var(--text);padding:9px;border-radius:7px}.template-group button:hover{background:var(--surface-2)}.template-group button.active{background:rgba(229,160,13,.14);color:var(--accent)}.template-group button span{display:grid;gap:2px}.template-group small{color:var(--muted);font-size:10px;line-height:1.3}.studio-editor{min-width:0;display:grid;gap:14px}.editor-title{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.editor-title h3{margin:0}.editor-title p{margin:4px 0 0;color:var(--muted);font-size:12px}.studio-actions{display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap;padding-top:12px;border-top:1px solid var(--border)}.mobile-model-select{display:none}.mode-preview :deep(.preview-panel){position:static}.mode-preview :deep(.preview-panel iframe){height:760px}
@media(max-width:1100px){.studio-layout,.studio-layout.mode-edit,.studio-layout.mode-preview{grid-template-columns:210px minmax(0,1fr)}.mode-split .studio-editor,.mode-split :deep(.preview-panel){grid-column:2}.mode-split :deep(.preview-panel){position:static}.template-sidebar{grid-row:1/span 2}}
@media(max-width:700px){.studio-head{display:grid;gap:10px}.studio-head .actions{width:100%;overflow:auto;flex-wrap:nowrap}.simulation-bar{display:grid;grid-template-columns:1fr}.simulation-bar label{min-width:0}.view-switch{width:100%}.view-switch button{flex:1;justify-content:center}.mobile-model-select{display:grid;gap:5px}.template-sidebar{display:none}.studio-layout,.studio-layout.mode-edit,.studio-layout.mode-preview{grid-template-columns:1fr}.mode-split .studio-editor,.mode-split :deep(.preview-panel){grid-column:1}.studio-actions{position:sticky;bottom:0;background:var(--surface);padding:10px 0;z-index:2}.studio-actions button{flex:1;min-width:140px}.email-studio{padding:12px}.mode-preview :deep(.preview-panel iframe){height:640px}}
</style>
