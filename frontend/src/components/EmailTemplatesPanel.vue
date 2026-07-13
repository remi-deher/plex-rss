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

      <div class="form-section">
        <label>Sujet<input v-model="current.subject"></label>
        <label>Modele HTML / Markdown</label>
        <div class="markdown-toolbar" role="toolbar" aria-label="Mise en forme du modele">
          <select title="Niveau de titre" @change="setHeading($event.target.value);$event.target.value=''">
            <option value="">Titre</option><option value="1">Titre 1</option><option value="2">Titre 2</option><option value="3">Titre 3</option>
          </select>
          <button class="icon-button" title="Gras" @click="wrapSelection('**','**','texte en gras')"><Bold/></button>
          <button class="icon-button" title="Italique" @click="wrapSelection('*','*','texte en italique')"><Italic/></button>
          <button class="icon-button" title="Liste a puces" @click="prefixLines('- ')"><List/></button>
          <button class="icon-button" title="Liste numerotee" @click="prefixLines('1. ')"><ListOrdered/></button>
          <button class="icon-button" title="Citation" @click="prefixLines('> ')"><Quote/></button>
          <button class="icon-button" title="Lien" @click="insertLink"><Link/></button>
          <details class="variable-picker">
            <summary><Braces/>Variables</summary>
            <div class="variable-menu">
              <button v-for="variable in variables" :key="variable.tag" type="button" @click="insertText(variable.tag)"><code>{{ variable.tag }}</code><span>{{ variable.description }}</span></button>
            </div>
          </details>
        </div>
        <textarea ref="contentEditor" v-model="current.template" rows="13" class="code-editor" @focus="activeEditor='content'"></textarea>

        <div class="settings-grid two">
          <label>Couleur d'accent<input v-model="current.accent_color" type="color"></label>
          <label>Badge<input v-model="current.badge_text"></label>
          <label>Titre principal<input v-model="current.headline_text"></label>
          <label class="check"><input v-model="current.show_synopsis" type="checkbox"> Afficher le synopsis</label>
        </div>
      </div>

      <details open class="template-settings">
        <summary>En-tete commun</summary>
        <div class="settings-grid two form-section">
          <label>Marque<input v-model="shared.email_header_brand"></label>
          <label>Sous-titre<input v-model="shared.email_header_subtitle"></label>
          <label>Couleur de marque<input v-model="shared.email_brand_color" type="color"></label>
          <label class="check"><input v-model="shared.email_show_header_subtitle" type="checkbox"> Afficher le sous-titre</label>
        </div>
      </details>

      <details class="template-settings">
        <summary>Bloc media et apparence</summary>
        <div class="settings-grid two form-section">
          <label>Disposition<select v-model="shared.email_media_layout"><option value="left">Affiche a gauche</option><option value="right">Affiche a droite</option><option value="stacked">Affiche au-dessus</option></select></label>
          <label>Police<select v-model="shared.email_font_family"><option value="arial">Arial</option><option value="georgia">Georgia</option><option value="verdana">Verdana</option><option value="trebuchet">Trebuchet MS</option></select></label>
          <label>Largeur de carte <span>{{ shared.email_card_width }} px</span><input v-model.number="shared.email_card_width" type="range" min="480" max="700" step="10"></label>
          <label>Largeur affiche <span>{{ shared.email_poster_width }} px</span><input v-model.number="shared.email_poster_width" type="range" min="60" max="180" step="10"></label>
          <label>Arrondi de carte <span>{{ shared.email_card_border_radius }} px</span><input v-model.number="shared.email_card_border_radius" type="range" min="0" max="24" step="2"></label>
          <label>Taille du synopsis<select v-model="shared.email_synopsis_font_size"><option value="small">Petite</option><option value="normal">Normale</option><option value="large">Grande</option><option value="xlarge">Tres grande</option></select></label>
          <label>Fond de page<input v-model="shared.email_bg_color" type="color"></label>
          <label>Fond de carte<input v-model="shared.email_card_bg_color" type="color"></label>
          <label class="check"><input v-model="shared.email_show_poster" type="checkbox"> Afficher l'affiche</label>
          <label class="check"><input v-model="shared.email_show_genres" type="checkbox"> Afficher les genres</label>
          <label class="check"><input v-model="shared.email_show_requester" type="checkbox"> Afficher le demandeur</label>
          <label>Libelle du demandeur<input v-model="shared.email_requester_label"></label>
          <label class="check"><input v-model="shared.email_show_tmdb_link" type="checkbox"> Afficher le lien TMDB</label>
          <label class="check"><input v-model="shared.email_show_plex_button" type="checkbox"> Afficher le bouton Plex</label>
        </div>
      </details>

      <details class="template-settings">
        <summary>Pied de page commun</summary>
        <div class="form-section">
          <label>Pied de page HTML / Markdown</label>
          <textarea ref="footerEditor" v-model="shared.email_footer_template" rows="5" class="code-editor" @focus="activeEditor='footer'"></textarea>
        </div>
      </details>

      <div class="actions preview-actions">
        <select v-model="previewVariant"><option value="movie_generic">Film</option><option value="movie_vo">Film VO</option><option value="movie_vf">Film VF</option><option value="episode">Episode</option><option value="season_complete">Saison complete</option></select>
        <select v-model="previewUser"><option value="">Utilisateur exemple</option><option v-for="user in users" :key="user.id" :value="user.id">{{ user.custom_name||user.display_name||user.plex_user_id }}</option></select>
        <button class="secondary" :disabled="previewing" @click="preview"><Eye/>Actualiser l'apercu</button>
        <button class="secondary" :disabled="busy" @click="testSend"><Send/>Envoyer un test</button>
      </div>
    </section>

    <section class="panel preview-panel">
      <div class="panel-head"><h2>Apercu</h2><span class="badge">{{ eventTypes.find(x=>x.key===eventType)?.label }}</span></div>
      <iframe :srcdoc="previewHtml" title="Apercu email" sandbox="allow-same-origin"></iframe>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { Bold, Braces, Eye, Italic, Link, List, ListOrdered, Quote, RotateCcw, Save, Send, Undo2 } from '@lucide/vue';
import { api } from '@/api';

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
const contentEditor=ref(null),footerEditor=ref(null),activeEditor=ref('content');
let timer;
const models=reactive(Object.fromEntries(eventTypes.map(entry=>[entry.key,{template:'',subject:'',accent_color:'#e5a00d',badge_text:'',headline_text:'',show_synopsis:true}])));
const shared=reactive({email_header_brand:'PLEXARR',email_header_subtitle:'Notification Plex',email_footer_template:'',email_brand_color:'#e5a00d',email_show_poster:true,email_show_genres:true,email_show_requester:true,email_show_header_subtitle:true,email_requester_label:'Demande par',email_poster_width:100,email_media_layout:'left',email_bg_color:'#0d0d0d',email_card_bg_color:'#141414',email_font_family:'arial',email_card_width:600,email_card_border_radius:10,email_synopsis_font_size:'normal',email_show_tmdb_link:true,email_show_plex_button:true});
const current=computed(()=>models[eventType.value]);

function payload(){const data={...shared};for(const entry of eventTypes){const model=models[entry.key];data[`email_${entry.key}_template`]=model.template;data[`email_${entry.key}_subject`]=model.subject||null;data[`email_${entry.key}_accent_color`]=model.accent_color||null;data[`email_${entry.key}_badge_text`]=model.badge_text||null;data[`email_${entry.key}_headline_text`]=model.headline_text||null;data[`email_${entry.key}_show_synopsis`]=model.show_synopsis}return data}
function previewPayload(){return{template:current.value.template,subject:current.value.subject,type:eventType.value,user_id:previewUser.value||null,preview_variant:previewVariant.value,header_brand:shared.email_header_brand,header_subtitle:shared.email_header_subtitle,footer_template:shared.email_footer_template,brand_color:shared.email_brand_color,show_header_subtitle:shared.email_show_header_subtitle,show_poster:shared.email_show_poster,show_genres:shared.email_show_genres,show_requester:shared.email_show_requester,requester_label:shared.email_requester_label,poster_width:shared.email_poster_width,media_layout:shared.email_media_layout,bg_color:shared.email_bg_color,card_bg_color:shared.email_card_bg_color,font_family:shared.email_font_family,card_width:shared.email_card_width,card_border_radius:shared.email_card_border_radius,synopsis_font_size:shared.email_synopsis_font_size,show_tmdb_link:shared.email_show_tmdb_link,show_plex_button:shared.email_show_plex_button,accent_color:current.value.accent_color,badge_text:current.value.badge_text,headline_text:current.value.headline_text,show_synopsis:current.value.show_synopsis}}
function fill(data){for(const entry of eventTypes){const model=models[entry.key];model.template=data[`email_${entry.key}_template`]||'';model.subject=data[`email_${entry.key}_subject`]||'';model.accent_color=data[`email_${entry.key}_accent_color`]||'#e5a00d';model.badge_text=data[`email_${entry.key}_badge_text`]||'';model.headline_text=data[`email_${entry.key}_headline_text`]||'';model.show_synopsis=data[`email_${entry.key}_show_synopsis`]!==false}for(const key of Object.keys(shared))if(data[key]!=null)shared[key]=data[key];hasPrevious.value=Boolean(data.has_previous_version)}
async function load(){error.value='';try{const [templates,userRows]=await Promise.all([api('/api/email-templates'),api('/api/users')]);users.value=userRows;fill(templates);await preview()}catch(e){error.value=e.message}}
async function save(){busy.value=true;error.value='';try{await api('/api/email-templates',{method:'PUT',body:JSON.stringify(payload())});message.value='Modeles enregistres.';hasPrevious.value=true;await preview()}catch(e){error.value=e.message}finally{busy.value=false}}
async function reset(){if(!confirm('Retablir tous les modeles par defaut ?'))return;busy.value=true;try{await api('/api/email-templates/reset',{method:'POST'});await load();message.value='Modeles retablis.'}catch(e){error.value=e.message}finally{busy.value=false}}
async function restorePrevious(){busy.value=true;try{await api('/api/email-templates/restore-previous',{method:'POST'});await load();message.value='Version precedente restauree.'}catch(e){error.value=e.message}finally{busy.value=false}}
async function preview(){clearTimeout(timer);previewing.value=true;try{const response=await fetch('/api/email-preview',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(previewPayload())});if(!response.ok)throw new Error((await response.json()).detail);previewHtml.value=await response.text()}catch(e){error.value=e.message}finally{previewing.value=false}}
function schedulePreview(){clearTimeout(timer);timer=setTimeout(preview,500)}
async function testSend(){busy.value=true;try{const data=await api('/api/email-templates/test-send',{method:'POST',body:JSON.stringify(previewPayload())});message.value=data.message}catch(e){error.value=e.message}finally{busy.value=false}}

function editor(){return activeEditor.value==='footer'?footerEditor.value:contentEditor.value}
function updateEditor(value,start,end){if(activeEditor.value==='footer')shared.email_footer_template=value;else current.value.template=value;nextTick(()=>{const target=editor();target?.focus();if(target){target.selectionStart=start;target.selectionEnd=end}})}
function insertText(text){const target=editor();if(!target)return;const start=target.selectionStart??target.value.length,end=target.selectionEnd??start;updateEditor(target.value.slice(0,start)+text+target.value.slice(end),start+text.length,start+text.length)}
function wrapSelection(prefix,suffix,placeholder){activeEditor.value='content';const target=contentEditor.value;if(!target)return;const start=target.selectionStart,end=target.selectionEnd,selected=target.value.slice(start,end)||placeholder;updateEditor(target.value.slice(0,start)+prefix+selected+suffix+target.value.slice(end),start+prefix.length,start+prefix.length+selected.length)}
function prefixLines(prefix){activeEditor.value='content';const target=contentEditor.value;if(!target)return;const start=target.selectionStart,end=target.selectionEnd,lineStart=target.value.lastIndexOf('\n',start-1)+1;let lineEnd=target.value.indexOf('\n',end);if(lineEnd<0)lineEnd=target.value.length;const transformed=target.value.slice(lineStart,lineEnd).split('\n').map(line=>prefix+line).join('\n');updateEditor(target.value.slice(0,lineStart)+transformed+target.value.slice(lineEnd),lineStart,lineStart+transformed.length)}
function setHeading(level){activeEditor.value='content';const target=contentEditor.value;if(!target||!level)return;const position=target.selectionStart,lineStart=target.value.lastIndexOf('\n',position-1)+1;let lineEnd=target.value.indexOf('\n',position);if(lineEnd<0)lineEnd=target.value.length;const line=target.value.slice(lineStart,lineEnd).replace(/^#{1,6}\s*/,''),replacement=`${'#'.repeat(Number(level))} ${line}`;updateEditor(target.value.slice(0,lineStart)+replacement+target.value.slice(lineEnd),lineStart+replacement.length,lineStart+replacement.length)}
function insertLink(){activeEditor.value='content';const target=contentEditor.value;if(!target)return;const start=target.selectionStart,end=target.selectionEnd,selected=target.value.slice(start,end)||'texte du lien',url=prompt('URL du lien :','https://');if(!url)return;const value=`[${selected}](${url})`;updateEditor(target.value.slice(0,start)+value+target.value.slice(end),start+value.length,start+value.length)}

watch([eventType,previewVariant,previewUser],schedulePreview);
watch(shared,schedulePreview,{deep:true});
watch(models,schedulePreview,{deep:true});
onMounted(load);
onBeforeUnmount(()=>clearTimeout(timer));
</script>
