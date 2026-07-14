<template>
  <div class="page">
    <header class="page-head"><div><h1>Parametres</h1><p>Connexions, notifications, automatisation et exploitation.</p></div><button v-if="['connections','notifications','automation'].includes(tab)" class="primary" :disabled="saving" @click="save"><Save/>{{ saving?'Enregistrement...':'Enregistrer' }}</button></header>
    <div class="segmented settings-tabs"><button v-for="item in tabs" :key="item.key" :class="{active:tab===item.key}" @click="selectTab(item.key)"><component :is="item.icon"/>{{ item.label }}</button></div><p v-if="error" class="notice error-text">{{ error }}</p><p v-if="message" class="notice success-text">{{ message }}</p>

    <div v-if="tab==='connections'" class="settings-grid">
      <div class="accordion-list span-two">
        <!-- Plex -->
        <div class="accordion-item" :class="{ expanded: expandedSections.plex }">
          <div class="accordion-header" @click="toggleSection('plex')">
            <div class="accordion-title">
              <span class="status-indicator active"></span>
              <h3>Plex</h3>
            </div>
            <div class="accordion-actions" @click.stop>
              <button class="secondary" @click="testSaved('/api/test/plex-api')"><PlugZap/>Tester</button>
              <span class="chevron"><ChevronDown /></span>
            </div>
          </div>
          <div class="accordion-content">
            <div class="accordion-content-inner">
              <label>URL<input v-model="form.plex_url" type="url" placeholder="http://plex:32400"></label>
              <label>Token<input v-model="form.plex_token" type="password" placeholder="Laisser vide pour conserver"></label>
              <label>URL RSS<input v-model="form.plex_rss_url" type="url"></label>
              <label class="check"><input v-model="form.plex_verify_ssl" type="checkbox"> Verifier le certificat TLS</label>
              <div class="actions">
                <button class="secondary" @click="testSaved('/api/test/plex-rss')"><Rss/>Tester le RSS</button>
                <button class="secondary" @click="startPlexSso"><LogIn/>Connexion Plex SSO</button>
              </div>
            </div>
          </div>
        </div>

        <!-- Seer -->
        <div class="accordion-item" :class="{ expanded: expandedSections.seer }">
          <div class="accordion-header" @click="toggleSection('seer')">
            <div class="accordion-title">
              <span class="status-indicator" :class="{ active: form.seer_enabled }"></span>
              <h3>Seer</h3>
            </div>
            <div class="accordion-actions" @click.stop>
              <button class="secondary" :disabled="!form.seer_enabled" @click="testSeer"><PlugZap/>Tester</button>
              <span class="chevron"><ChevronDown /></span>
            </div>
          </div>
          <div class="accordion-content">
            <div class="accordion-content-inner">
              <label class="check"><input v-model="form.seer_enabled" type="checkbox"> Activer Seer</label>
              <label>URL Seer<input v-model="form.seer_url" type="url" placeholder="http://seer:5055"></label>
              <label>Cle API Seer<input v-model="form.seer_api_key" type="password" placeholder="Laisser vide pour conserver"></label>
              <label class="check"><input v-model="form.seer_send_requests" type="checkbox"> Envoyer les demandes a Seer</label>
              <label class="check"><input v-model="form.seer_fallback_arr" type="checkbox"> Repli direct Sonarr/Radarr</label>
              <label class="check"><input v-model="form.seer_suppress_notifications" type="checkbox"> Laisser Plex-RSS gerer les emails de demande pour les utilisateurs Seer</label>
            </div>
          </div>
        </div>

        <!-- TMDB -->
        <div class="accordion-item" :class="{ expanded: expandedSections.tmdb }">
          <div class="accordion-header" @click="toggleSection('tmdb')">
            <div class="accordion-title">
              <span class="status-indicator" :class="{ active: form.tmdb_enabled }"></span>
              <h3>TMDB</h3>
            </div>
            <div class="accordion-actions" @click.stop>
              <button class="secondary" :disabled="!form.tmdb_enabled" @click="testTmdb"><PlugZap/>Tester</button>
              <span class="chevron"><ChevronDown /></span>
            </div>
          </div>
          <div class="accordion-content">
            <div class="accordion-content-inner">
              <label class="check"><input v-model="form.tmdb_enabled" type="checkbox"> Activer TMDB</label>
              <label>Cle TMDB<input v-model="form.tmdb_api_key" type="password" placeholder="Laisser vide pour conserver"></label>
            </div>
          </div>
        </div>
      </div>
      <section class="panel form-section span-two"><div class="panel-head"><h2>Instances Sonarr, Radarr et Prowlarr</h2><button class="icon-button" @click="loadArr"><RefreshCw/></button></div><div class="connection-list"><article v-for="instance in arrInstances" :key="instance.id" class="inline-row"><div><strong>{{ instance.name }}</strong><span>{{ instance.arr_type }} · {{ instance.url }}</span></div><div class="actions"><button class="icon-button" title="Tester" @click="testArr(instance)"><PlugZap/></button><button class="icon-button" title="Modifier" @click="editArr(instance)"><Pencil/></button><button class="icon-button" :title="instance.enabled?'Desactiver':'Activer'" @click="toggleArr(instance)"><Power/></button><button class="icon-button danger" title="Supprimer" @click="removeArr(instance)"><Trash2/></button></div></article></div><div class="compact-form"><label>Nom<input v-model="arrForm.name"></label><label>Type<select v-model="arrForm.arr_type"><option value="sonarr">Sonarr</option><option value="radarr">Radarr</option><option value="prowlarr">Prowlarr</option></select></label><label>URL<input v-model="arrForm.url" type="url"></label><label>Cle API<input v-model="arrForm.api_key" type="password"></label><label>Profil<select v-model.number="arrForm.quality_profile_id"><option :value="null">Par defaut</option><option v-for="profile in arrProfiles" :key="profile.id" :value="profile.id">{{ profile.name }}</option></select></label><label>Dossier racine<select v-model="arrForm.root_folder"><option value="">Par defaut</option><option v-for="folder in arrFolders" :key="folder.path||folder" :value="folder.path||folder">{{ folder.path||folder }}</option></select></label><label class="check"><input v-model="arrForm.is_default" type="checkbox"> Instance par defaut</label></div><div class="actions"><button class="secondary" @click="loadArrOptions"><ListRestart/>Charger profils et dossiers</button><button class="primary" :disabled="busy||!arrForm.name||!arrForm.url||!arrForm.api_key" @click="saveArr"><Save/>{{ editingArrId?'Mettre a jour':'Ajouter' }}</button><button v-if="editingArrId" class="secondary" @click="resetArr">Annuler</button></div></section>
      <section class="panel form-section span-two"><div class="panel-head"><h2>Clients de telechargement direct</h2><button class="icon-button" @click="loadClients"><RefreshCw/></button></div><div class="connection-list"><article v-for="client in clients" :key="client.id" class="inline-row"><div><strong>{{ client.name }}</strong><span>{{ client.client_type }} · {{ client.url }}</span></div><div class="actions"><button class="icon-button" @click="testClient(client)"><PlugZap/></button><button class="icon-button" @click="editClient(client)"><Pencil/></button><button class="icon-button" @click="toggleClient(client)"><Power/></button><button class="icon-button danger" @click="removeClient(client)"><Trash2/></button></div></article></div><div class="compact-form"><label>Nom<input v-model="clientForm.name"></label><label>Type<select v-model="clientForm.client_type"><option value="qbittorrent">qBittorrent</option><option value="transmission">Transmission</option><option value="deluge">Deluge</option></select></label><label>URL<input v-model="clientForm.url" type="url"></label><label>Utilisateur<input v-model="clientForm.username"></label><label>Mot de passe<input v-model="clientForm.password" type="password"></label><label>Categorie<input v-model="clientForm.category"></label><label>Tags<input v-model="clientForm.tags"></label><label class="check"><input v-model="clientForm.is_default" type="checkbox"> Client par defaut</label></div><div class="actions"><button class="primary" @click="saveClient"><Save/>{{ editingClientId?'Mettre a jour':'Ajouter' }}</button><button v-if="editingClientId" class="secondary" @click="resetClient">Annuler</button></div></section>
    </div>

    <div v-else-if="tab==='webhooks'" class="settings-grid">
      <section class="panel form-section span-two">
        <h2>Configuration des Webhooks</h2>
        <p>Les webhooks permettent aux applications tierces de notifier Plex-RSS en temps réel.</p>
        
        <div v-if="!form.webhook_secret" class="notice warning">
          <p>Le secret webhook n'est pas configuré. L'authentification des webhooks entrants est désactivée.</p>
          <button class="primary" @click="generateWebhookSecret">Générer un secret</button>
        </div>
        
        <div v-else class="webhook-list">
          <div v-for="svc in ['plex', 'radarr', 'sonarr']" :key="svc" class="webhook-item">
            <div class="webhook-title">
              <strong>{{ svc.charAt(0).toUpperCase() + svc.slice(1) }}</strong>
            </div>
            <div class="webhook-url">
              <input type="text" readonly :value="`${baseUrl}/webhook/${svc}?secret=${form.webhook_secret}`">
              <button class="icon-button" @click="copyWebhook(svc)" title="Copier"><Copy/></button>
              <button class="secondary" @click="testWebhook(svc)" :disabled="testingWebhook === svc">
                <RefreshCw v-if="testingWebhook === svc" class="spin" />
                <span v-else>Tester</span>
              </button>
            </div>
            <div v-if="webhookStatus[svc]" class="webhook-status" :class="{ 'status-ok': webhookStatus[svc].success, 'status-error': !webhookStatus[svc].success }">
              <span v-if="webhookStatus[svc].success"><Check /> {{ webhookStatus[svc].message || 'Succès' }}</span>
              <span v-else>Erreur : {{ webhookStatus[svc].message }}</span>
            </div>
          </div>
          
          <div class="actions" style="margin-top: 2rem;">
            <button class="secondary danger" @click="revokeWebhookSecret">Révoquer le secret</button>
            <button class="secondary" @click="generateWebhookSecret">Regénérer le secret</button>
          </div>
        </div>
      </section>
    </div>

    <div v-else-if="tab==='notifications'" class="settings-grid">
      <div class="accordion-list span-two">
        <!-- Email -->
        <div class="accordion-item" :class="{ expanded: expandedSections.email }">
          <div class="accordion-header" @click="toggleSection('email')">
            <div class="accordion-title">
              <span class="status-indicator" :class="{ active: form.email_enabled }"></span>
              <h3>Email</h3>
            </div>
            <div class="accordion-actions" @click.stop>
              <button class="secondary" :disabled="!form.email_enabled" @click="testSmtp"><PlugZap/>Tester</button>
              <span class="chevron"><ChevronDown /></span>
            </div>
          </div>
          <div class="accordion-content">
            <div class="accordion-content-inner">
              <label class="check"><input v-model="form.email_enabled" type="checkbox"> Activer les emails</label>
              <label>Serveur SMTP<input v-model="form.smtp_host"></label>
              <label>Port<input v-model.number="form.smtp_port" type="number"></label>
              <label>Utilisateur<input v-model="form.smtp_user"></label>
              <label>Mot de passe<input v-model="form.smtp_password" type="password" placeholder="Laisser vide pour conserver"></label>
              <label>Expediteur<input v-model="form.smtp_from" type="email"></label>
              <label>Email administrateur<input v-model="form.admin_notification_email"></label>
              <label class="check"><input v-model="form.smtp_tls" type="checkbox"> TLS</label>
            </div>
          </div>
        </div>

        <!-- Discord, Telegram, ntfy, Gotify -->
        <div v-for="channel in channels" :key="channel.key" class="accordion-item" :class="{ expanded: expandedSections[channel.key] }">
          <div class="accordion-header" @click="toggleSection(channel.key)">
            <div class="accordion-title">
              <span class="status-indicator" :class="{ active: form[`${channel.key}_enabled`] }"></span>
              <h3>{{ channel.label }}</h3>
            </div>
            <div class="accordion-actions" @click.stop>
              <button class="secondary" :disabled="!form[`${channel.key}_enabled`]" @click="testSaved(`/api/test/${channel.key}`)"><PlugZap/>Tester</button>
              <span class="chevron"><ChevronDown /></span>
            </div>
          </div>
          <div class="accordion-content">
            <div class="accordion-content-inner">
              <label class="check"><input v-model="form[`${channel.key}_enabled`]" type="checkbox"> Activer</label>
              <template v-if="channel.key==='discord'">
                <label>Webhook<input v-model="form.discord_webhook_url"></label>
              </template>
              <template v-else-if="channel.key==='telegram'">
                <label>Token bot<input v-model="form.telegram_bot_token" type="password"></label>
                <label>Chat ID<input v-model="form.telegram_chat_id"></label>
              </template>
              <template v-else-if="channel.key==='ntfy'">
                <label>URL<input v-model="form.ntfy_url"></label>
                <label>Topic<input v-model="form.ntfy_topic"></label>
                <label>Token<input v-model="form.ntfy_token" type="password"></label>
              </template>
              <template v-else>
                <label>URL<input v-model="form.gotify_url"></label>
                <label>Token<input v-model="form.gotify_token" type="password"></label>
              </template>
            </div>
          </div>
        </div>
      </div>
      <section class="panel form-section span-two"><h2>Evenements et canaux</h2><div class="event-matrix"><div></div><strong>Email</strong><strong>Discord</strong><strong>Telegram</strong><strong>ntfy</strong><strong>Gotify</strong><template v-for="event in notificationEvents" :key="event.key"><strong>{{ event.label }}</strong><label class="check"><input v-model="form[`email_on_${event.key}`]" type="checkbox"></label><label v-for="channel in channels" :key="channel.key" class="check"><input v-model="form[`${channel.key}_send_${event.key}`]" type="checkbox"></label></template></div><label class="check"><input v-model="form.email_on_vf_available" type="checkbox"> Email lors d'une amelioration VO vers VF</label><div class="settings-grid two"><label class="check"><input v-model="form.movie_notify_language" type="checkbox"> Distinguer VO/VF pour les films</label><label class="check"><input v-model="form.series_notify_language" type="checkbox"> Distinguer VO/VF pour les series</label><label>Granularite series<select v-model="form.series_notify_granularity"><option value="minimal">Serie complete</option><option value="jalons">Debut et fin de saison</option><option value="tout">Chaque episode</option></select></label></div></section>
    </div>

    <div v-else-if="tab==='automation'" class="settings-grid">
      <div class="accordion-list span-two">

        <!-- Watchlist -->
        <div class="accordion-item" :class="{ expanded: expandedSections.watchlist }">
          <div class="accordion-header" @click="toggleSection('watchlist')">
            <div class="accordion-title">
              <span class="status-indicator active"></span>
              <h3>Watchlist</h3>
            </div>
            <div class="accordion-actions" @click.stop>
              <span class="chevron"><ChevronDown /></span>
            </div>
          </div>
          <div class="accordion-content">
            <div class="accordion-content-inner">
              <label>Intervalle en secondes<input v-model.number="form.poll_interval_seconds" type="number" min="15"></label>
              <label>Priorite<select v-model="form.watchlist_source_priority"><option value="api">API Plex</option><option value="rss">RSS</option></select></label>
              <label class="check"><input v-model="form.watchlist_fallback_enabled" type="checkbox"> Source de repli</label>
              <label class="check"><input v-model="form.require_approval" type="checkbox"> Approbation admin requise</label>
            </div>
          </div>
        </div>

        <!-- Analyse VF -->
        <div class="accordion-item" :class="{ expanded: expandedSections.vff }">
          <div class="accordion-header" @click="toggleSection('vff')">
            <div class="accordion-title">
              <span class="status-indicator" :class="{ active: form.vff_enabled }"></span>
              <h3>Analyse VF</h3>
            </div>
            <div class="accordion-actions" @click.stop>
              <span class="chevron"><ChevronDown /></span>
            </div>
          </div>
          <div class="accordion-content">
            <div class="accordion-content-inner">
              <label class="check"><input v-model="form.vff_enabled" type="checkbox"> Analyse active</label>
              <label>Nouvelle analyse (minutes)<input v-model.number="form.vff_recheck_interval_minutes" type="number"></label>
              <label class="check"><input v-model="form.vff_auto_search" type="checkbox"> Recherche automatique</label>
              <!-- Library picker -->
              <div style="margin-top:12px">
                <strong style="display:block;margin-bottom:8px;font-size:13px">Bibliotheques analysees</strong>
                <div v-if="plexSectionsLoading" class="notice">Chargement des bibliotheques Plex...</div>
                <div v-else-if="!plexSections.length" class="notice warning-text">Aucune bibliotheque Plex trouvee. Verifiez la connexion Plex dans l'onglet Connexions.</div>
                <div v-else class="vff-library-picker">
                  <div v-for="section in plexSections" :key="section.name" class="vff-library-row">
                    <label class="check vff-lib-check">
                      <input type="checkbox" :checked="isLibrarySelected(section.name)" @change="toggleLibrary(section.name, section.type, $event.target.checked)">
                      <span class="vff-lib-name">{{ section.name }}</span>
                      <span class="badge" :class="section.type==='show'?'':''">{{ section.type==='show'?'Serie':'Film' }}</span>
                    </label>
                    <div v-if="isLibrarySelected(section.name)" class="vff-lib-kind">
                      <div class="segmented small">
                        <button :class="{active: getLibraryKind(section.name)==='series'}" @click="setLibraryKind(section.name, 'series')">Serie</button>
                        <button :class="{active: getLibraryKind(section.name)==='movie'}" @click="setLibraryKind(section.name, 'movie')">Film</button>
                        <button :class="{active: getLibraryKind(section.name)==='anime'}" @click="setLibraryKind(section.name, 'anime')">Anime</button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Conservation -->
        <div class="accordion-item" :class="{ expanded: expandedSections.conservation }">
          <div class="accordion-header" @click="toggleSection('conservation')">
            <div class="accordion-title">
              <span class="status-indicator active"></span>
              <h3>Conservation</h3>
            </div>
            <div class="accordion-actions" @click.stop>
              <span class="chevron"><ChevronDown /></span>
            </div>
          </div>
          <div class="accordion-content">
            <div class="accordion-content-inner">
              <label>Journaux (jours)<input v-model.number="form.notification_log_retention_days" type="number"></label>
              <label>Verification Arr (heures)<input v-model.number="form.arr_poll_interval_hours" type="number"></label>
              <label class="check"><input v-model="form.digest_enabled" type="checkbox"> Digest actif</label>
              <label>Heure du digest<input v-model.number="form.digest_hour" type="number" min="0" max="23"></label>
            </div>
          </div>
        </div>

        <!-- Regles torrent -->
        <div class="accordion-item" :class="{ expanded: expandedSections.torrent }">
          <div class="accordion-header" @click="toggleSection('torrent')">
            <div class="accordion-title">
              <span class="status-indicator active"></span>
              <h3>Regles torrent</h3>
            </div>
            <div class="accordion-actions" @click.stop>
              <span class="chevron"><ChevronDown /></span>
            </div>
          </div>
          <div class="accordion-content">
            <div class="accordion-content-inner">
              <label>Mots requis<input v-model="form.torrent_required_keywords"></label>
              <label>Mots interdits<input v-model="form.torrent_forbidden_keywords"></label>
              <label>Taille minimale (Go)<input v-model.number="form.torrent_min_size_gb" type="number"></label>
              <label>Taille maximale (Go)<input v-model.number="form.torrent_max_size_gb" type="number"></label>
              <label>Ratio limite<input v-model.number="form.torrent_ratio_limit" type="number" step="0.1"></label>
              <label>Duree de seed (h)<input v-model.number="form.torrent_seed_time_limit_hours" type="number"></label>
              <label class="check"><input v-model="form.torrent_auto_delete_files" type="checkbox"> Supprimer les fichiers apres seed</label>
            </div>
          </div>
        </div>

      </div>
    </div>
    <SettingsOperationsPanel v-else-if="tab==='operations'"/><EmailTemplatesPanel v-else-if="tab==='templates'"/>
    <div v-else class="settings-grid"><section class="panel form-section"><h2>Export et sauvegarde</h2><label class="check"><input v-model="includeSecrets" type="checkbox"> Inclure les identifiants</label><a class="secondary" :href="includeSecrets?'/api/export?include_secrets=true':'/api/export'"><Download/>Exporter en JSON</a><a class="secondary" href="/api/backup/db"><HardDriveDownload/>Backup complet</a><p class="warning-text">Ces fichiers peuvent contenir des secrets.</p></section><section class="panel form-section"><h2>Importer un export JSON</h2><input ref="jsonInput" type="file" accept=".json"><button class="secondary" :disabled="busy" @click="importJson"><Upload/>Fusionner les donnees</button></section><section class="panel form-section migration-panel"><h2>Ancienne base SQLite</h2><input ref="sqliteInput" type="file" accept=".db,.sqlite,.sqlite3" @change="resetInspection"><button class="secondary" :disabled="busy" @click="inspectSqlite"><Search/>Inspecter</button><div v-if="inspection" class="migration-summary"><strong>{{ inspection.total_rows.toLocaleString() }} lignes</strong><span>{{ inspection.populated_tables }} tables · integrite {{ inspection.integrity }}</span><div class="table-badges"><span v-for="(count,name) in populatedTables" :key="name" class="badge">{{ name }} : {{ count.toLocaleString() }}</span></div></div><template v-if="inspection"><p class="warning-text">Une sauvegarde PostgreSQL sera creee avant le remplacement.</p><label>Confirmation<input v-model="confirmation" class="mono" placeholder="REMPLACER"></label><button class="primary danger-button" :disabled="busy||confirmation!=='REMPLACER'" @click="migrateSqlite"><DatabaseZap/>Remplacer</button></template></section></div>
  </div>
</template>
<script setup>
import { computed,markRaw,onMounted,reactive,ref } from 'vue';import { Bell,Bot,ChevronDown,DatabaseZap,Download,FileCode2,HardDriveDownload,ListRestart,LogIn,Pencil,Plug,PlugZap,Plus,Power,RefreshCw,Rss,Save,Search,ServerCog,Trash2,Upload,Link,Copy,Check } from '@lucide/vue';import { api } from '@/api';import EmailTemplatesPanel from '@/components/EmailTemplatesPanel.vue';import SettingsOperationsPanel from '@/components/SettingsOperationsPanel.vue';
const tabs=[{key:'connections',label:'Connexions',icon:markRaw(Plug)},{key:'webhooks',label:'Webhooks',icon:markRaw(Link)},{key:'notifications',label:'Notifications',icon:markRaw(Bell)},{key:'automation',label:'Automatisation',icon:markRaw(Bot)},{key:'operations',label:'Exploitation',icon:markRaw(ServerCog)},{key:'templates',label:'Emails',icon:markRaw(FileCode2)},{key:'data',label:'Donnees',icon:markRaw(DatabaseZap)}];const tab=ref(new URLSearchParams(location.search).get('tab')||'connections');const channels=[{key:'discord',label:'Discord'},{key:'telegram',label:'Telegram'},{key:'ntfy',label:'ntfy'},{key:'gotify',label:'Gotify'}];const notificationEvents=[{key:'request',label:'Nouvelle demande'},{key:'available',label:'Disponibilite'},{key:'failure',label:'Echec'}];
const secretFields=['plex_token','seer_api_key','tmdb_api_key','smtp_password','telegram_bot_token','ntfy_token','gotify_token'];const form=reactive({plex_url:'',plex_token:'',plex_verify_ssl:true,plex_rss_url:'',seer_enabled:false,seer_url:'',seer_api_key:'',seer_send_requests:false,seer_fallback_arr:false,seer_suppress_notifications:true,tmdb_api_key:'',tmdb_enabled:true,webhook_secret:'',email_enabled:false,smtp_host:'',smtp_port:587,smtp_user:'',smtp_password:'',smtp_from:'',smtp_tls:true,admin_notification_email:'',email_on_request:true,email_on_available:true,email_on_failure:true,email_on_vf_available:true,discord_enabled:false,discord_webhook_url:'',discord_send_request:true,discord_send_available:true,discord_send_failure:true,telegram_enabled:false,telegram_bot_token:'',telegram_chat_id:'',telegram_send_request:true,telegram_send_available:true,telegram_send_failure:true,ntfy_enabled:false,ntfy_url:'',ntfy_topic:'',ntfy_token:'',ntfy_send_request:true,ntfy_send_available:true,ntfy_send_failure:true,gotify_enabled:false,gotify_url:'',gotify_token:'',gotify_send_request:true,gotify_send_available:true,gotify_send_failure:true,movie_notify_language:true,series_notify_language:true,series_notify_granularity:'jalons',poll_interval_seconds:300,watchlist_source_priority:'api',watchlist_fallback_enabled:true,require_approval:false,vff_enabled:true,vff_libraries:'',vff_recheck_interval_minutes:60,vff_auto_search:false,notification_log_retention_days:30,arr_poll_interval_hours:6,digest_enabled:false,digest_hour:8,torrent_required_keywords:'',torrent_forbidden_keywords:'',torrent_min_size_gb:null,torrent_max_size_gb:null,torrent_ratio_limit:null,torrent_seed_time_limit_hours:null,torrent_auto_delete_files:false});
const saving=ref(false),busy=ref(false),error=ref(''),message=ref(''),includeSecrets=ref(false),jsonInput=ref(null),sqliteInput=ref(null),inspection=ref(null),confirmation=ref('');const arrInstances=ref([]),arrProfiles=ref([]),arrFolders=ref([]),editingArrId=ref(null);const arrDefaults={name:'',arr_type:'sonarr',url:'',api_key:'',quality_profile_id:null,root_folder:'',minimum_availability:'released',is_default:false,enabled:true,indexer_ids:null};const arrForm=reactive({...arrDefaults});const clients=ref([]),editingClientId=ref(null);const clientDefaults={name:'',client_type:'qbittorrent',url:'',username:'',password:'',category:'',tags:'',is_default:false,enabled:true};const clientForm=reactive({...clientDefaults});const populatedTables=computed(()=>Object.fromEntries(Object.entries(inspection.value?.tables||{}).filter(([,count])=>count>0)));const expandedSections=reactive({plex:false,seer:false,tmdb:false,email:false,discord:false,telegram:false,ntfy:false,gotify:false,watchlist:false,vff:false,conservation:false,torrent:false});function toggleSection(sec){expandedSections[sec]=!expandedSections[sec]}
// Plex sections for vff library picker
const plexSections=ref([]);const plexSectionsLoading=ref(false);
const vffLibraryList=computed({get(){try{const raw=form.vff_libraries;if(!raw)return [];const parsed=JSON.parse(raw);return Array.isArray(parsed)?parsed:[];}catch{return [];}},set(arr){form.vff_libraries=JSON.stringify(arr);}});
function isLibrarySelected(name){return vffLibraryList.value.some(x=>x.name===name)}
function getLibraryKind(name){return vffLibraryList.value.find(x=>x.name===name)?.kind||'series'}
function toggleLibrary(name,plexType,checked){const list=[...vffLibraryList.value];if(checked){const defaultKind=plexType==='show'?'series':'movie';list.push({name,kind:defaultKind});}else{const idx=list.findIndex(x=>x.name===name);if(idx>=0)list.splice(idx,1);}vffLibraryList.value=list;}
function setLibraryKind(name,kind){const list=[...vffLibraryList.value];const entry=list.find(x=>x.name===name);if(entry)entry.kind=kind;vffLibraryList.value=list;}
async function loadPlexSections(){plexSectionsLoading.value=true;try{plexSections.value=await api('/api/plex/sections');}catch(e){plexSections.value=[];}finally{plexSectionsLoading.value=false;}}
function success(text){message.value=text;error.value=''}function selectTab(value){tab.value=value;history.replaceState(null,'',`/settings?tab=${value}`);if(value==='automation')loadPlexSections();}
async function load(){try{const [data]=await Promise.all([api('/api/settings'),loadArr(),loadClients()]);for(const key of Object.keys(form))if(data[key]!=null)form[key]=data[key];for(const key of secretFields)form[key]=''}catch(e){error.value=e.message}}async function save(){saving.value=true;const payload={...form};for(const key of secretFields)if(!payload[key])delete payload[key];try{await api('/api/settings',{method:'PUT',body:JSON.stringify(payload)});success('Configuration enregistree.')}catch(e){error.value=e.message}finally{saving.value=false}}
async function testSaved(path){await save();try{const data=await api(path,{method:'POST'});success(data.message||'Connexion valide.')}catch(e){error.value=e.message}}async function testSmtp(){await save();const recipient=prompt('Adresse de test',form.admin_notification_email||form.smtp_from);if(!recipient)return;try{const data=await api('/api/test/smtp',{method:'POST',body:JSON.stringify({recipient})});success(data.message||'Email envoye.')}catch(e){error.value=e.message}}async function testSeer(){try{const data=await api('/api/test/seer',{method:'POST',body:JSON.stringify({seer_url:form.seer_url,seer_api_key:form.seer_api_key})});success(data.message||'Connexion valide.')}catch(e){error.value=e.message}}async function testTmdb(){try{const data=await api('/api/test/tmdb',{method:'POST',body:JSON.stringify({tmdb_api_key:form.tmdb_api_key})});success(data.message||'Connexion valide.')}catch(e){error.value=e.message}}
const baseUrl=window.location.origin;const webhookStatus=reactive({plex:null,radarr:null,sonarr:null});const testingWebhook=ref(null);async function generateWebhookSecret(){if(form.webhook_secret&&!confirm("Generer un nouveau secret annulera l'ancien et cassera les webhooks configures. Continuer ?"))return;try{const res=await api('/api/settings/webhook-secret',{method:'POST'});form.webhook_secret=res.webhook_secret;success('Secret genere avec succes.')}catch(e){error.value=e.message}}async function revokeWebhookSecret(){if(!confirm("Voulez-vous vraiment desactiver l'authentification des webhooks entrants ?"))return;try{await api('/api/settings/webhook-secret',{method:'DELETE'});form.webhook_secret='';success('Secret revoque.')}catch(e){error.value=e.message}}async function copyWebhook(svc){const url=`${baseUrl}/webhook/${svc}?secret=${form.webhook_secret}`;await navigator.clipboard.writeText(url);success('URL copiee dans le presse-papier.')}async function testWebhook(svc){testingWebhook.value=svc;try{const res=await api(`/webhook/check-live/${svc}`,{method:'POST'});const result=res.results&&res.results[0];if(result){webhookStatus[svc]={success:result.success,message:result.message}}else{webhookStatus[svc]={success:true,message:'Test effectue (pas de resultat precis)'}}}catch(e){webhookStatus[svc]={success:false,message:e.message}}finally{testingWebhook.value=null}}
async function startPlexSso(){try{const data=await api('/api/plex/sso/pin',{method:'POST'});window.open(data.auth_url||data.url,'_blank','noopener');const timer=setInterval(async()=>{const state=await api(`/api/plex/sso/check/${data.id}`).catch(()=>null);if(state?.authenticated||state?.token){clearInterval(timer);success('Connexion Plex terminee.');await load()}},2000);setTimeout(()=>clearInterval(timer),180000)}catch(e){error.value=e.message}}
async function loadArr(){arrInstances.value=await api('/api/arr-instances')}function resetArr(){editingArrId.value=null;Object.assign(arrForm,arrDefaults);arrProfiles.value=[];arrFolders.value=[]}function editArr(instance){editingArrId.value=instance.id;Object.assign(arrForm,arrDefaults,instance);loadArrOptions()}async function loadArrOptions(){if(arrForm.arr_type==='prowlarr'){arrProfiles.value=[];arrFolders.value=[];return}const q=editingArrId.value?`?instance_id=${editingArrId.value}`:`?url=${encodeURIComponent(arrForm.url)}&api_key=${encodeURIComponent(arrForm.api_key)}`;[arrProfiles.value,arrFolders.value]=await Promise.all([api(`/api/${arrForm.arr_type}/profiles${q}`).catch(()=>[]),api(`/api/${arrForm.arr_type}/folders${q}`).catch(()=>[])])}async function saveArr(){busy.value=true;try{await api(editingArrId.value?`/api/arr-instances/${editingArrId.value}`:'/api/arr-instances',{method:editingArrId.value?'PUT':'POST',body:JSON.stringify(arrForm)});success(editingArrId.value?'Instance mise a jour.':'Instance ajoutee.');resetArr();await loadArr()}catch(e){error.value=e.message}finally{busy.value=false}}async function testArr(instance=arrForm){try{const data=await api('/api/test/arr-instance',{method:'POST',body:JSON.stringify({url:instance.url,api_key:instance.api_key,arr_type:instance.arr_type})});success(data.message||'Instance joignable.')}catch(e){error.value=e.message}}async function toggleArr(instance){await api(`/api/arr-instances/${instance.id}/toggle`,{method:'PATCH'});await loadArr()}async function removeArr(instance){if(!confirm(`Supprimer ${instance.name} ?`))return;await api(`/api/arr-instances/${instance.id}`,{method:'DELETE'});await loadArr()}
async function loadClients(){clients.value=await api('/api/download-clients')}function resetClient(){editingClientId.value=null;Object.assign(clientForm,clientDefaults)}function editClient(client){editingClientId.value=client.id;Object.assign(clientForm,clientDefaults,client)}async function saveClient(){try{await api(editingClientId.value?`/api/download-clients/${editingClientId.value}`:'/api/download-clients',{method:editingClientId.value?'PUT':'POST',body:JSON.stringify(clientForm)});resetClient();await loadClients();success('Client enregistre.')}catch(e){error.value=e.message}}async function testClient(client=clientForm){try{const data=await api('/api/test/download-client',{method:'POST',body:JSON.stringify(client)});success(data.message||'Client joignable.')}catch(e){error.value=e.message}}async function toggleClient(client){await api(`/api/download-clients/${client.id}/toggle`,{method:'PATCH'});await loadClients()}async function removeClient(client){if(!confirm(`Supprimer ${client.name} ?`))return;await api(`/api/download-clients/${client.id}`,{method:'DELETE'});await loadClients()}
async function upload(path,file,extra={}){const body=new FormData();body.append('file',file);for(const [key,value] of Object.entries(extra))body.append(key,value);const response=await fetch(path,{method:'POST',credentials:'same-origin',body});const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.detail||`HTTP ${response.status}`);return data}async function importJson(){const file=jsonInput.value?.files?.[0];if(!file)return;busy.value=true;try{const data=await upload('/api/import',file);success(`Import termine : ${data.stats.users_upserted} utilisateurs.`);await load()}catch(e){error.value=e.message}finally{busy.value=false}}function resetInspection(){inspection.value=null;confirmation.value=''}async function inspectSqlite(){const file=sqliteInput.value?.files?.[0];if(!file)return;busy.value=true;try{inspection.value=await upload('/api/migration/sqlite/inspect',file);success('Base SQLite valide.')}catch(e){error.value=e.message}finally{busy.value=false}}async function migrateSqlite(){const file=sqliteInput.value?.files?.[0];if(!file||confirmation.value!=='REMPLACER')return;busy.value=true;try{const data=await upload('/api/migration/sqlite',file,{confirm:confirmation.value});success(`Migration terminee : ${data.report.copied_rows.toLocaleString()} lignes.`);setTimeout(()=>location.assign('/dashboard'),1500)}catch(e){error.value=e.message}finally{busy.value=false}}
onMounted(()=>{load();if(tab.value==='automation')loadPlexSections();});
</script>
