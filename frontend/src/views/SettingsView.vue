<template>
  <div class="page">
    <header class="page-head">
      <div><h1>Parametres</h1><p>Connexions, notifications, automatisation et donnees.</p></div>
      <button v-if="tab !== 'data'" class="primary" :disabled="saving" @click="save"><Save/>{{ saving ? 'Enregistrement...' : 'Enregistrer' }}</button>
    </header>
    <div class="segmented settings-tabs">
      <button v-for="item in tabs" :key="item.key" :class="{active:tab===item.key}" @click="tab=item.key"><component :is="item.icon"/>{{ item.label }}</button>
    </div>
    <p v-if="error" class="notice error-text">{{ error }}</p>
    <p v-if="message" class="notice success-text">{{ message }}</p>

    <div v-if="tab === 'connections'" class="settings-grid">
      <section class="panel form-section">
        <h2>Plex</h2>
        <label>URL<input v-model="form.plex_url" type="url" placeholder="http://plex:32400"></label>
        <label>Token<input v-model="form.plex_token" type="password" placeholder="Laisser vide pour conserver"></label>
        <label>URL RSS<input v-model="form.plex_rss_url" type="url"></label>
        <label class="check"><input v-model="form.plex_verify_ssl" type="checkbox"> Verifier le certificat TLS</label>
      </section>
      <section class="panel form-section">
        <h2>Seer et TMDB</h2>
        <label class="check"><input v-model="form.seer_enabled" type="checkbox"> Activer Seer</label>
        <label>URL Seer<input v-model="form.seer_url" type="url"></label>
        <label>Cle API Seer<input v-model="form.seer_api_key" type="password" placeholder="Laisser vide pour conserver"></label>
        <label>Cle TMDB<input v-model="form.tmdb_api_key" type="password" placeholder="Laisser vide pour conserver"></label>
        <label class="check"><input v-model="form.seer_send_requests" type="checkbox"> Envoyer les demandes a Seer</label>
        <label class="check"><input v-model="form.seer_fallback_arr" type="checkbox"> Repli direct Sonarr/Radarr</label>
      </section>
      <section class="panel form-section arr-panel">
        <div class="panel-head"><h2>Instances Arr</h2><button class="icon-button" title="Actualiser" @click="loadArr"><RefreshCw/></button></div>
        <div v-for="instance in arrInstances" :key="instance.id" class="inline-row">
          <div><strong>{{ instance.name }}</strong><span>{{ instance.arr_type }} · {{ instance.url }}</span></div>
          <div class="actions">
            <button class="icon-button" :title="instance.enabled ? 'Desactiver' : 'Activer'" @click="toggleArr(instance)"><Power/></button>
            <button class="icon-button danger" title="Supprimer" @click="removeArr(instance)"><Trash2/></button>
          </div>
        </div>
        <div class="compact-form">
          <label>Nom<input v-model="arrForm.name" placeholder="Sonarr principal"></label>
          <label>Type<select v-model="arrForm.arr_type"><option value="sonarr">Sonarr</option><option value="radarr">Radarr</option><option value="prowlarr">Prowlarr</option></select></label>
          <label>URL<input v-model="arrForm.url" type="url"></label>
          <label>Cle API<input v-model="arrForm.api_key" type="password"></label>
          <label>Dossier racine<input v-model="arrForm.root_folder"></label>
          <label class="check"><input v-model="arrForm.is_default" type="checkbox"> Instance par defaut</label>
        </div>
        <button class="secondary" :disabled="busy || !arrForm.name || !arrForm.url || !arrForm.api_key" @click="addArr"><Plus/>Ajouter l'instance</button>
      </section>
    </div>

    <div v-else-if="tab === 'notifications'" class="settings-grid">
      <section class="panel form-section">
        <h2>Email</h2>
        <label class="check"><input v-model="form.email_enabled" type="checkbox"> Activer les emails</label>
        <label>Serveur SMTP<input v-model="form.smtp_host"></label>
        <label>Port<input v-model.number="form.smtp_port" type="number" min="1" max="65535"></label>
        <label>Utilisateur<input v-model="form.smtp_user"></label>
        <label>Mot de passe<input v-model="form.smtp_password" type="password" placeholder="Laisser vide pour conserver"></label>
        <label>Expediteur<input v-model="form.smtp_from" type="email"></label>
        <label class="check"><input v-model="form.smtp_tls" type="checkbox"> TLS</label>
      </section>
      <section class="panel form-section">
        <h2>Discord</h2>
        <label class="check"><input v-model="form.discord_enabled" type="checkbox"> Activer Discord</label>
        <label>Webhook<input v-model="form.discord_webhook_url" type="url"></label>
        <h2>Telegram</h2>
        <label class="check"><input v-model="form.telegram_enabled" type="checkbox"> Activer Telegram</label>
        <label>Token bot<input v-model="form.telegram_bot_token" type="password"></label>
        <label>Chat ID<input v-model="form.telegram_chat_id"></label>
      </section>
      <section class="panel form-section">
        <h2>ntfy</h2>
        <label class="check"><input v-model="form.ntfy_enabled" type="checkbox"> Activer ntfy</label>
        <label>URL<input v-model="form.ntfy_url" type="url"></label>
        <label>Topic<input v-model="form.ntfy_topic"></label>
        <label>Token<input v-model="form.ntfy_token" type="password"></label>
        <h2>Gotify</h2>
        <label class="check"><input v-model="form.gotify_enabled" type="checkbox"> Activer Gotify</label>
        <label>URL<input v-model="form.gotify_url" type="url"></label>
        <label>Token<input v-model="form.gotify_token" type="password"></label>
      </section>
    </div>

    <div v-else-if="tab === 'automation'" class="settings-grid">
      <section class="panel form-section">
        <h2>Watchlist</h2>
        <label>Intervalle en secondes<input v-model.number="form.poll_interval_seconds" type="number" min="15"></label>
        <label>Priorite<select v-model="form.watchlist_source_priority"><option value="api">API Plex</option><option value="rss">RSS</option></select></label>
        <label class="check"><input v-model="form.watchlist_fallback_enabled" type="checkbox"> Source de repli</label>
        <label class="check"><input v-model="form.require_approval" type="checkbox"> Approbation admin requise</label>
      </section>
      <section class="panel form-section">
        <h2>Analyse VF</h2>
        <label class="check"><input v-model="form.vff_enabled" type="checkbox"> Analyse VF active</label>
        <label>Bibliotheques<input v-model="form.vff_libraries" placeholder="Films, Series"></label>
        <label>Nouvelle analyse (minutes)<input v-model.number="form.vff_recheck_interval_minutes" type="number" min="1"></label>
        <label class="check"><input v-model="form.vff_auto_search" type="checkbox"> Recherche VF automatique</label>
      </section>
      <section class="panel form-section">
        <h2>Conservation</h2>
        <label>Journaux de notification (jours)<input v-model.number="form.notification_log_retention_days" type="number" min="0"></label>
        <label>Verification Arr (heures)<input v-model.number="form.arr_poll_interval_hours" type="number" min="1"></label>
        <label class="check"><input v-model="form.digest_enabled" type="checkbox"> Digest actif</label>
        <label>Heure du digest<input v-model.number="form.digest_hour" type="number" min="0" max="23"></label>
      </section>
    </div>

    <div v-else class="settings-grid">
      <section class="panel form-section">
        <h2>Export et sauvegarde</h2>
        <label class="check"><input v-model="includeSecrets" type="checkbox"> Inclure les identifiants dans l'export JSON</label>
        <a class="secondary" :href="includeSecrets ? '/api/export?include_secrets=true' : '/api/export'"><Download/>Exporter en JSON</a>
        <a class="secondary" href="/api/backup/db"><HardDriveDownload/>Telecharger un backup complet</a>
        <p class="warning-text">Ces fichiers peuvent contenir des tokens, mots de passe et cles API.</p>
      </section>
      <section class="panel form-section">
        <h2>Importer un export JSON</h2>
        <input ref="jsonInput" type="file" accept=".json">
        <button class="secondary" :disabled="busy" @click="importJson"><Upload/>Fusionner les donnees</button>
        <p>La fusion JSON conserve les donnees presentes et met a jour les entites portables.</p>
      </section>
      <section class="panel form-section migration-panel">
        <h2>Ancienne base SQLite</h2>
        <input ref="sqliteInput" type="file" accept=".db,.sqlite,.sqlite3" @change="resetInspection">
        <button class="secondary" :disabled="busy" @click="inspectSqlite"><Search/>Inspecter</button>
        <div v-if="inspection" class="migration-summary">
          <strong>{{ inspection.total_rows.toLocaleString() }} lignes</strong>
          <span>{{ inspection.populated_tables }} tables peuplees · integrite {{ inspection.integrity }}</span>
          <div class="table-badges"><span v-for="(count,name) in populatedTables" :key="name" class="badge">{{ name }} : {{ count.toLocaleString() }}</span></div>
        </div>
        <template v-if="inspection">
          <p class="warning-text">Le remplacement cree d'abord un dump PostgreSQL, puis remplace toutes les donnees dans une transaction.</p>
          <label>Confirmation<input v-model="confirmation" class="mono" placeholder="REMPLACER" autocomplete="off"></label>
          <button class="primary danger-button" :disabled="busy || confirmation !== 'REMPLACER'" @click="migrateSqlite"><DatabaseZap/>Remplacer par cette base</button>
        </template>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, markRaw, onMounted, reactive, ref } from "vue";
import { Bell, Bot, DatabaseZap, Download, HardDriveDownload, Plus, Plug, Power, RefreshCw, Save, Search, Trash2, Upload } from "@lucide/vue";
import { api } from "@/api";

const tabs=[
  {key:'connections',label:'Connexions',icon:markRaw(Plug)},
  {key:'notifications',label:'Notifications',icon:markRaw(Bell)},
  {key:'automation',label:'Automatisation',icon:markRaw(Bot)},
  {key:'data',label:'Donnees',icon:markRaw(DatabaseZap)},
];
const tab=ref(new URLSearchParams(location.search).get('tab')||'connections');
const secretFields=['plex_token','seer_api_key','tmdb_api_key','smtp_password','telegram_bot_token','ntfy_token','gotify_token'];
const form=reactive({
  plex_url:'',plex_token:'',plex_verify_ssl:true,plex_rss_url:'',seer_enabled:false,seer_url:'',seer_api_key:'',seer_send_requests:false,seer_fallback_arr:false,tmdb_api_key:'',
  email_enabled:false,smtp_host:'',smtp_port:587,smtp_user:'',smtp_password:'',smtp_from:'',smtp_tls:true,
  discord_enabled:false,discord_webhook_url:'',telegram_enabled:false,telegram_bot_token:'',telegram_chat_id:'',ntfy_enabled:false,ntfy_url:'',ntfy_topic:'',ntfy_token:'',gotify_enabled:false,gotify_url:'',gotify_token:'',
  poll_interval_seconds:300,watchlist_source_priority:'api',watchlist_fallback_enabled:true,require_approval:false,vff_enabled:true,vff_libraries:'',vff_recheck_interval_minutes:60,vff_auto_search:false,notification_log_retention_days:30,arr_poll_interval_hours:6,digest_enabled:false,digest_hour:8,
});
const saving=ref(false),busy=ref(false),error=ref(''),message=ref(''),includeSecrets=ref(false),jsonInput=ref(null),sqliteInput=ref(null),inspection=ref(null),confirmation=ref('');
const arrInstances=ref([]);
const arrForm=reactive({name:'',arr_type:'sonarr',url:'',api_key:'',root_folder:'',is_default:false,enabled:true});
const populatedTables=computed(()=>Object.fromEntries(Object.entries(inspection.value?.tables||{}).filter(([,count])=>count>0)));
function success(text){message.value=text;error.value=''}
async function load(){try{const [data]=await Promise.all([api('/api/settings'),loadArr()]);for(const key of Object.keys(form)){if(data[key]!=null)form[key]=data[key]}for(const key of secretFields)form[key]=''}catch(e){error.value=e.message}}
async function loadArr(){arrInstances.value=await api('/api/arr-instances')}
async function addArr(){busy.value=true;try{await api('/api/arr-instances',{method:'POST',body:JSON.stringify(arrForm)});Object.assign(arrForm,{name:'',arr_type:'sonarr',url:'',api_key:'',root_folder:'',is_default:false,enabled:true});await loadArr();success('Instance ajoutee.')}catch(e){error.value=e.message}finally{busy.value=false}}
async function toggleArr(instance){try{await api(`/api/arr-instances/${instance.id}/toggle`,{method:'PATCH'});await loadArr()}catch(e){error.value=e.message}}
async function removeArr(instance){try{await api(`/api/arr-instances/${instance.id}`,{method:'DELETE'});await loadArr()}catch(e){error.value=e.message}}
async function save(){saving.value=true;error.value='';message.value='';const payload={...form};for(const key of secretFields)if(!payload[key])delete payload[key];try{await api('/api/settings',{method:'PUT',body:JSON.stringify(payload)});success('Configuration enregistree.')}catch(e){error.value=e.message}finally{saving.value=false}}
async function upload(path,file,extra={}){const body=new FormData();body.append('file',file);for(const [key,value] of Object.entries(extra))body.append(key,value);const response=await fetch(path,{method:'POST',credentials:'same-origin',body});const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.detail||`HTTP ${response.status}`);return data}
async function importJson(){const file=jsonInput.value?.files?.[0];if(!file){error.value='Selectionnez un export JSON.';return}busy.value=true;try{const data=await upload('/api/import',file);success(`Import termine : ${data.stats.users_upserted} utilisateurs et ${data.stats.requests_upserted} demandes.`);await load()}catch(e){error.value=e.message}finally{busy.value=false}}
function resetInspection(){inspection.value=null;confirmation.value=''}
async function inspectSqlite(){const file=sqliteInput.value?.files?.[0];if(!file){error.value='Selectionnez une base SQLite.';return}busy.value=true;try{inspection.value=await upload('/api/migration/sqlite/inspect',file);success('Base SQLite valide.')}catch(e){error.value=e.message;inspection.value=null}finally{busy.value=false}}
async function migrateSqlite(){const file=sqliteInput.value?.files?.[0];if(!file||confirmation.value!=='REMPLACER')return;busy.value=true;try{const data=await upload('/api/migration/sqlite',file,{confirm:confirmation.value});success(`Migration terminee : ${data.report.copied_rows.toLocaleString()} lignes copiees.`);setTimeout(()=>location.assign('/dashboard'),1500)}catch(e){error.value=e.message}finally{busy.value=false}}
onMounted(load);
</script>
