<template>
  <div class="template-workspace">
    <section class="panel template-editor">
      <div class="panel-head">
        <div><h2>Modeles d'emails</h2><p>Sujets, contenu et presentation des messages.</p></div>
        <div class="actions">
          <button v-if="hasPrevious" class="secondary" :disabled="busy" @click="restorePrevious"><Undo2/>Version precedente</button>
          <button class="secondary" :disabled="busy" @click="reset"><RotateCcw/>Valeurs par defaut</button>
          <button class="primary" :disabled="busy" @click="save"><Save/>Enregistrer</button>
        </div>
      </div>

      <nav class="detail-tabs">
        <button v-for="entry in eventTypes" :key="entry.key" :class="{active:eventType===entry.key}" @click="eventType=entry.key">{{ entry.label }}</button>
      </nav>
      <p v-if="error" class="notice error-text">{{ error }}</p>
      <p v-if="message" class="notice success-text">{{ message }}</p>

      <EmailEventEditor :model="current" :variables="variables" />

      <EmailSharedSettings :shared="shared" :variables="variables" />

      <div class="actions preview-actions">
        <select v-model="previewVariant"><option value="movie_generic">Film</option><option value="movie_vo">Film VO</option><option value="movie_vf">Film VF</option><option value="episode">Episode</option><option value="season_complete">Saison complete</option></select>
        <select v-model="previewUser"><option value="">Utilisateur exemple</option><option v-for="user in users" :key="user.id" :value="user.id">{{ user.custom_name||user.display_name||user.plex_user_id }}</option></select>
        <button class="secondary" :disabled="previewing" @click="preview"><Eye/>Actualiser l'apercu</button>
        <button class="secondary" :disabled="busy" @click="testSend"><Send/>Envoyer un test</button>
      </div>
    </section>

    <EmailPreviewPanel :preview-html="previewHtml" :event-label="eventTypes.find(x=>x.key===eventType)?.label" />
  </div>
  <ConfirmModal v-bind="confirmDialog" @cancel="resolveConfirm(false)" @confirm="resolveConfirm(true)" />
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { Eye, RotateCcw, Save, Send, Undo2 } from '@lucide/vue';
import { api } from '@/api';
import EmailEventEditor from './email/EmailEventEditor.vue';
import EmailSharedSettings from './email/EmailSharedSettings.vue';
import EmailPreviewPanel from './email/EmailPreviewPanel.vue';
import ConfirmModal from './ConfirmModal.vue';
import { useConfirm } from '@/composables/useConfirm';

const eventTypes=[{key:'request',label:'Demande'},{key:'available',label:'Disponible'},{key:'upgrade',label:'Amelioration VF'},{key:'failure',label:'Echec'},{key:'correction',label:'Correction'}];
const variables=[
  {tag:'{titre}',description:"Titre de l'oeuvre"},{tag:'{type}',description:'Le film ou La serie'},
  {tag:'{media_type_et_titre}',description:'Type et titre combines'},{tag:'{annee}',description:'Annee de sortie'},
  {tag:'{affiche}',description:"URL de l'affiche"},{tag:'{details_saison_episode}',description:'Saison et episode'},
  {tag:'{langue}',description:'Version VF ou VO'},{tag:'{nom_utilisateur}',description:'Nom du demandeur'},
  {tag:'{synopsis}',description:'Resume du media'},{tag:'{raison}',description:"Raison de l'echec"},
  {tag:'{corrections}',description:'Corrections appliquees'},{tag:'{note_correction}',description:'Note de correction'},
];

const eventType=ref('request'),users=ref([]),previewHtml=ref(''),previewVariant=ref('movie_generic'),previewUser=ref('');
const error=ref(''),message=ref(''),busy=ref(false),previewing=ref(false),hasPrevious=ref(false);
let timer;
const models=reactive(Object.fromEntries(eventTypes.map(entry=>[entry.key,{template:'',subject:'',accent_color:'#e5a00d',badge_text:'',headline_text:'',show_synopsis:true}])));
const shared=reactive({email_header_brand:'PLEXARR',email_header_subtitle:'Notification Plex',email_footer_template:'',email_brand_color:'#e5a00d',email_show_poster:true,email_show_genres:true,email_show_requester:true,email_show_header_subtitle:true,email_requester_label:'Demande par',email_poster_width:100,email_media_layout:'left',email_bg_color:'#0d0d0d',email_card_bg_color:'#141414',email_font_family:'arial',email_card_width:600,email_card_border_radius:10,email_synopsis_font_size:'normal',email_show_tmdb_link:true,email_show_plex_button:true});
const current=computed(()=>models[eventType.value]);
const { dialog: confirmDialog, askConfirm, resolveConfirm } = useConfirm();

function payload(){const data={...shared};for(const entry of eventTypes){const model=models[entry.key];data[`email_${entry.key}_template`]=model.template;data[`email_${entry.key}_subject`]=model.subject||null;data[`email_${entry.key}_accent_color`]=model.accent_color||null;data[`email_${entry.key}_badge_text`]=model.badge_text||null;data[`email_${entry.key}_headline_text`]=model.headline_text||null;data[`email_${entry.key}_show_synopsis`]=model.show_synopsis}return data}
function previewPayload(){return{template:current.value.template,subject:current.value.subject,type:eventType.value,user_id:previewUser.value||null,preview_variant:previewVariant.value,header_brand:shared.email_header_brand,header_subtitle:shared.email_header_subtitle,footer_template:shared.email_footer_template,brand_color:shared.email_brand_color,show_header_subtitle:shared.email_show_header_subtitle,show_poster:shared.email_show_poster,show_genres:shared.email_show_genres,show_requester:shared.email_show_requester,requester_label:shared.email_requester_label,poster_width:shared.email_poster_width,media_layout:shared.email_media_layout,bg_color:shared.email_bg_color,card_bg_color:shared.email_card_bg_color,font_family:shared.email_font_family,card_width:shared.email_card_width,card_border_radius:shared.email_card_border_radius,synopsis_font_size:shared.email_synopsis_font_size,show_tmdb_link:shared.email_show_tmdb_link,show_plex_button:shared.email_show_plex_button,accent_color:current.value.accent_color,badge_text:current.value.badge_text,headline_text:current.value.headline_text,show_synopsis:current.value.show_synopsis}}
function fill(data){for(const entry of eventTypes){const model=models[entry.key];model.template=data[`email_${entry.key}_template`]||'';model.subject=data[`email_${entry.key}_subject`]||'';model.accent_color=data[`email_${entry.key}_accent_color`]||'#e5a00d';model.badge_text=data[`email_${entry.key}_badge_text`]||'';model.headline_text=data[`email_${entry.key}_headline_text`]||'';model.show_synopsis=data[`email_${entry.key}_show_synopsis`]!==false}for(const key of Object.keys(shared))if(data[key]!=null)shared[key]=data[key];hasPrevious.value=Boolean(data.has_previous_version)}
async function load(){error.value='';try{const [templates,userRows]=await Promise.all([api('/api/email-templates'),api('/api/users')]);users.value=userRows;fill(templates);await preview()}catch(e){error.value=e.message}}
async function save(){busy.value=true;error.value='';try{await api('/api/email-templates',{method:'PUT',body:JSON.stringify(payload())});message.value='Modeles enregistres.';hasPrevious.value=true;await preview()}catch(e){error.value=e.message}finally{busy.value=false}}
async function reset(){if(!await askConfirm({title:'Rétablir les modèles ?',message:'Tous les modèles seront remplacés par leurs valeurs par défaut.',confirmLabel:'Rétablir',danger:true}))return;busy.value=true;try{await api('/api/email-templates/reset',{method:'POST'});await load();message.value='Modeles retablis.'}catch(e){error.value=e.message}finally{busy.value=false}}
async function restorePrevious(){busy.value=true;try{await api('/api/email-templates/restore-previous',{method:'POST'});await load();message.value='Version precedente restauree.'}catch(e){error.value=e.message}finally{busy.value=false}}
async function preview(){clearTimeout(timer);previewing.value=true;try{const response=await fetch('/api/email-preview',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(previewPayload())});if(!response.ok)throw new Error((await response.json()).detail);previewHtml.value=await response.text()}catch(e){error.value=e.message}finally{previewing.value=false}}
function schedulePreview(){clearTimeout(timer);timer=setTimeout(preview,500)}
async function testSend(){busy.value=true;try{const data=await api('/api/email-templates/test-send',{method:'POST',body:JSON.stringify(previewPayload())});message.value=data.message}catch(e){error.value=e.message}finally{busy.value=false}}

watch([eventType,previewVariant,previewUser],schedulePreview);
watch(shared,schedulePreview,{deep:true});
watch(models,schedulePreview,{deep:true});
onMounted(load);
onBeforeUnmount(()=>clearTimeout(timer));
</script>
