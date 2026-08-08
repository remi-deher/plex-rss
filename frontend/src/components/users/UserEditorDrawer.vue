<template>
  <DrawerShell wide eyebrow="Administration" :title="creating?'Nouvel utilisateur':displayName(editing)" :error="editorError" @close="$emit('close')">
    <section v-if="!creating" class="user-drawer-summary"><div><span :class="['user-state-dot',{active:editing.enabled}]"></span><div><strong>{{ editing.enabled?'Compte actif':'Compte désactivé' }}</strong><small>{{ editing.diagnostic?.source_label||editing.source||'Source inconnue' }}</small></div></div><span class="badge" :class="editing.role==='admin'?'available':editing.role==='moderator'?'sent_to_arr':'pending'">{{ editing.role }}</span><span class="badge" :class="editing.can_login?'available':'failed'">{{ editing.can_login?'Connexion autorisée':'Connexion bloquée' }}</span></section>
    <nav class="detail-tabs"><button v-for="entry in editorTabs" :key="entry" :class="{active:editorTab===entry}" @click="editorTab=entry">{{ editorLabel(entry) }}</button></nav>

    <section v-if="editorTab==='profile'" class="drawer-section form-section">
      <label v-if="creating" class="check local-account-toggle"><input v-model="isLocalAccount" type="checkbox" @change="onLocalAccountToggle"> Compte local (sans Plex)</label>
      <div class="settings-grid two">
        <label>{{ isLocalAccount?"Identifiant de connexion":"ID Plex" }}<input v-model="form.plex_user_id" :disabled="!creating && editing.source!=='local'" :placeholder="isLocalAccount?'ex. jdupont':''"></label>
        <label>Nom affiche<input v-model="form.display_name"></label>
        <label>Nom d'usage<input v-model="form.custom_name"></label>
        <label>Email Plex<input v-model="form.plex_email" type="email"></label>
        <label>Email de notification<input v-model="form.notification_email"></label>
        <label>Role<select v-model="form.role"><option value="user">Utilisateur</option><option value="moderator">Modérateur</option><option value="admin">Administrateur</option></select></label>
        <label class="check"><input v-model="form.enabled" type="checkbox"> Traiter les demandes</label>
        <label class="check"><input v-model="form.can_login" type="checkbox"> Autoriser la connexion</label>
        <label class="check"><input v-model="form.auto_approve" type="checkbox"> Auto-approuver</label>
      </div>
      <label v-if="creating && isLocalAccount">Mot de passe initial<input v-model="initialPassword" type="password" minlength="8" autocomplete="new-password"></label>
      <div class="actions">
        <button class="primary" :disabled="busy" @click="$emit('save')"><Save/>Enregistrer</button>
        <a v-if="!creating && editing.id" class="secondary" :href="`/api/users/${editing.id}/data-export`" :download="`plexarr-donnees-${editing.plex_user_id||editing.id}.json`" title="Exporter les données de cette personne (RGPD, droit d'accès)"><Download/>Exporter les données</a>
        <button v-if="!creating" class="secondary danger" @click="$emit('delete')"><Trash2/>Supprimer</button>
      </div>

      <div v-if="!creating" class="password-section" :class="{muted:Boolean(editing.plex_account_uuid)}">
        <h3><KeyRound/>Mot de passe</h3>
        <p v-if="editing.plex_account_uuid" class="password-hint">Ce compte se connecte via Plex — le mot de passe reste modifiable mais n'est pas la méthode de connexion active.</p>
        <div class="password-row">
          <input v-model="newPassword" type="password" minlength="8" autocomplete="new-password" placeholder="Nouveau mot de passe">
          <button class="secondary" :disabled="newPassword.length<8||busy" @click="submitPassword"><KeyRound/>Definir</button>
        </div>
      </div>

      <div v-if="!creating" class="notification-history">
        <div class="panel-head"><h3>Derniers envois</h3><span>{{ editing.notification_history?.length||0 }}</span></div>
        <article v-for="log in (editing.notification_history||[]).slice(0,8)" :key="log.id" class="detail-row"><div><strong>{{ notificationLabel(log) }}</strong><span>{{ log.channel }} · {{ formatDateTime(log.sent_at) }}<template v-if="log.media_title"> · {{ log.media_title }}</template></span><small v-if="log.error_msg" class="error-text">{{ log.error_msg }}</small></div><span class="badge" :class="log.success?'available':'failed'">{{ log.success?'Envoyée':'Échec' }}</span></article>
        <p v-if="!editing.notification_history?.length" class="empty">Aucune notification enregistrée.</p>
      </div>
    </section>

    <section v-else-if="editorTab==='notifications'" class="drawer-section form-section">
      <div class="notif-group">
        <h3><Mail/>Emails</h3>
        <div class="settings-grid two">
          <label class="check"><input v-model="form.notify_on_request" type="checkbox"> Nouvelle demande</label>
          <small class="check-hint">Email envoyé à cette personne quand une de ses demandes est enregistrée.</small>
          <label class="check"><input v-model="form.notify_on_available" type="checkbox"> Disponibilité</label>
          <small class="check-hint">Email envoyé quand un média qu'elle a demandé devient disponible dans Plex.</small>
          <label class="check"><input v-model="form.notify_digest" type="checkbox"> Récapitulatif quotidien (digest)</label>
          <small class="check-hint">Reçoit un résumé une fois par jour au lieu d'un email par événement — nécessite que le digest soit activé globalement (Paramètres → Notifications → Règles).</small>
          <label class="check"><input v-model="form.notify_admin" type="checkbox"> Copier l'administrateur</label>
          <small class="check-hint">Ajoute l'adresse email admin en copie sur les notifications envoyées à cette personne.</small>
        </div>
      </div>

      <div class="notif-group">
        <h3><Languages/>Disponibilité VF</h3>
        <p class="hint">Faut-il notifier cette personne quand un média qu'elle a demandé passe en VF ? Désactivé par défaut pour les animes (VO japonaise fréquente à la sortie, pour éviter les faux positifs).</p>
        <div class="settings-grid two">
          <label class="check"><input v-model="form.notify_vf_movie" type="checkbox"> Films</label>
          <label class="check"><input v-model="form.notify_vf_series" type="checkbox"> Séries</label>
          <label class="check"><input v-model="form.notify_vf_anime" type="checkbox"> Animes</label>
          <label>Fréquence pour les séries
            <select v-model="form.series_notify_granularity">
              <option value="minimal">Une seule fois, à la fin</option>
              <option value="jalons">Début et fin de saison</option>
              <option value="tout">Chaque épisode</option>
            </select>
          </label>
        </div>
      </div>

      <div class="notif-group">
        <h3><Send/>Canaux personnels</h3>
        <p class="hint">Optionnel — si renseigné, les notifications push de cette personne partent vers ce webhook/chat personnel plutôt que le canal Discord/Telegram global configuré dans les Paramètres.</p>
        <div class="settings-grid two">
          <label>Webhook Discord personnel<input v-model="form.discord_webhook_url" placeholder="https://discord.com/api/webhooks/..."></label>
          <label>Chat ID Telegram personnel<input v-model="form.telegram_chat_id" placeholder="ex. 123456789"></label>
        </div>
      </div>

      <div class="actions">
        <button class="primary" @click="$emit('save')"><Save/>Enregistrer</button>
        <button v-if="!creating" class="secondary" @click="$emit('test-email')" title="Envoie un email de test à l'adresse configurée pour cette personne"><MailCheck/>Tester l'email</button>
      </div>
    </section>

    <section v-else-if="editorTab==='seer'" class="drawer-section">
      <div class="panel-head"><h3>Liaison Seer</h3><span class="badge">{{ editing.seer_user_id?`Compte #${editing.seer_user_id}`:'Non lie' }}</span></div>
      <div class="actions">
        <button class="secondary" @click="$emit('user-action','seer-automatch')"><Link/>Association automatique</button>
        <button v-if="editing.seer_user_id" class="secondary" @click="$emit('user-action','seer-complete')"><RefreshCw/>Completer les donnees</button>
        <button v-if="editing.seer_user_id" class="secondary danger" @click="$emit('unlink-seer')"><Unlink/>Dissocier</button>
      </div>
      <label>Fusionner cet utilisateur dans
        <select v-model="mergeTarget">
          <option value="">Selectionner...</option>
          <option v-for="user in users.filter(x=>x.id!==editing.id)" :key="user.id" :value="user.id">{{ displayName(user) }}</option>
        </select>
      </label>
      <button class="secondary danger" :disabled="!mergeTarget" @click="$emit('merge',mergeTarget)"><Merge/>Fusionner</button>
    </section>

    <section v-else-if="editorTab==='activity'" class="drawer-section">
      <section class="metric-grid compact-metrics">
        <MetricCard v-for="(value,key) in editing.stats||{}" :key="key" :label="key" :value="value??'-'"/>
      </section>
      <div class="user-activity-timeline"><article v-for="event in activityTimeline" :key="event.key" :class="['activity-event',event.type]"><span class="activity-marker"></span><div><strong>{{ event.title }}</strong><span>{{ event.label }}</span><small>{{ formatDateTime(event.date) }}</small></div><span v-if="event.status" class="badge" :class="event.type==='notification_failed'?'failed':'pending'">{{ event.status }}</span></article></div>
      <p v-if="!editing.activity?.recent?.length" class="empty">Aucune activite recente.</p>
    </section>

    <section v-else class="drawer-section">
      <article v-for="effect in editing.diagnostic?.effects||[]" :key="effect.key" class="detail-row">
        <div><strong>{{ effect.label }}</strong><span>{{ effect.detail }}</span></div>
        <span class="badge" :class="effect.ok?'available':'failed'">{{ effect.ok?'OK':'Attention' }}</span>
      </article>
      <p v-if="!editing.diagnostic" class="empty">Aucun diagnostic disponible.</p>
    </section>
  </DrawerShell>
</template>

<script setup>
import MetricCard from '@/components/ui/MetricCard.vue';
import { formatDate, formatDateTime } from '@/utils/format';
import { computed, ref, watch } from 'vue';
import { Download, KeyRound, Languages, Link, Mail, MailCheck, Merge, RefreshCw, Save, Send, Trash2, Unlink } from '@lucide/vue';
import DrawerShell from '@/components/DrawerShell.vue';

const props = defineProps({
  editing: { type: Object, required: true },
  creating: { type: Boolean, default: false },
  form: { type: Object, required: true },
  users: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
  editorError: { type: String, default: '' },
});
const emit = defineEmits(['close', 'save', 'delete', 'test-email', 'user-action', 'unlink-seer', 'merge', 'set-password']);

const editorTabs = ['profile', 'notifications', 'seer', 'activity', 'diagnostic'];
const editorTab = ref('profile');
const mergeTarget = ref('');
const isLocalAccount = ref(false);
const initialPassword = ref('');
const newPassword = ref('');

function onLocalAccountToggle() {
  props.form.source = isLocalAccount.value ? 'local' : null;
}
// Le formulaire est repeuple par fillForm() du parent a chaque ouverture (creation ou
// edition) : on aligne la case a cocher sur la source deja chargee plutot que de la
// piloter uniquement via le toggle (sinon ouvrir un compte local existant l'affiche
// decochee).
watch(() => props.form.source, value => { isLocalAccount.value = value === 'local'; }, { immediate: true });

function submitPassword() {
  emit('set-password', newPassword.value);
  newPassword.value = '';
}

function displayName(user) { return user?.custom_name || user?.display_name || user?.plex_user_id || ''; }
function editorLabel(value) { return ({ profile: 'Profil', notifications: 'Notifications', seer: 'Seer', activity: 'Activite', diagnostic: 'Diagnostic' })[value]; }
function notificationLabel(log){return ({request:'Demande enregistrée',available:'Média disponible',vf_available:'VF disponible'})[log.event]||String(log.event||'Notification').replaceAll('_',' ')}
const activityTimeline=computed(()=>{
  const requests=(props.editing.activity?.recent||[]).map(row=>({key:`request-${row.id}`,type:'request',date:row.requested_at,title:row.title,label:`Demande ${row.role==='co_requester'?'partagée':'principale'} · ${row.source}`,status:row.status}));
  const available=(props.editing.activity?.recent||[]).filter(row=>row.available_at).map(row=>({key:`available-${row.id}`,type:'available',date:row.available_at,title:row.title,label:'Média devenu disponible',status:'Disponible'}));
  const notifications=(props.editing.notification_history||[]).map(log=>({key:`notification-${log.id}`,type:log.success?'notification':'notification_failed',date:log.sent_at,title:log.media_title||notificationLabel(log),label:`${notificationLabel(log)} · ${log.channel}`,status:log.success?'Envoyée':'Échec'}));
  return [...requests,...available,...notifications].filter(event=>event.date).sort((a,b)=>new Date(b.date)-new Date(a.date)).slice(0,20)
});

defineExpose({
  resetTab: () => { editorTab.value = 'profile'; mergeTarget.value = ''; newPassword.value = ''; initialPassword.value = ''; },
  initialPassword,
});
</script>
<style scoped>
.user-drawer-summary{display:flex;align-items:center;gap: var(--space-2);padding:11px;border:1px solid var(--border);border-radius:var(--radius-md);background:var(--surface-2)}.user-drawer-summary>div{display:flex;align-items:center;gap: var(--space-2);margin-right:auto}.user-drawer-summary>div>div{display:grid;gap: var(--space-1)}.user-drawer-summary small{color:var(--muted);font-size:var(--fs-xs)}.user-state-dot{width:9px;height:9px;border-radius:50%;background:var(--muted)}.user-state-dot.active{background:var(--success)}.notification-history{display:grid;gap: var(--space-2);margin-top:16px;padding-top:14px;border-top:1px solid var(--border)}.notification-history h3{margin:0;font-size:var(--fs-md)}.notification-history small{display:block;margin-top:3px}.user-activity-timeline{display:grid}.activity-event{position:relative;display:grid;grid-template-columns:14px 1fr auto;gap: var(--space-2);padding-bottom:15px}.activity-event::before{content:'';position:absolute;top:12px;bottom:0;left:5px;width:2px;background:var(--border)}.activity-event:last-child::before{display:none}.activity-marker{position:relative;z-index:1;width:12px;height:12px;margin-top:3px;border:2px solid var(--accent);border-radius:50%;background:var(--surface)}.activity-event.available .activity-marker,.activity-event.notification .activity-marker{border-color:var(--success)}.activity-event.notification_failed .activity-marker{border-color:var(--danger)}.activity-event>div{display:grid;gap: var(--space-1)}.activity-event span,.activity-event small{color:var(--muted);font-size:var(--fs-xs)}.activity-event strong{font-size:var(--fs-sm)}@media(max-width:520px){.user-drawer-summary{align-items:flex-start;flex-wrap:wrap}.user-drawer-summary>div{width:100%}.activity-event{grid-template-columns:14px 1fr}.activity-event>.badge{grid-column:2;justify-self:start}}
.local-account-toggle{margin-bottom:14px}
.password-section{display:grid;gap: var(--space-2);margin-top:16px;padding-top:14px;border-top:1px solid var(--border)}
.password-section h3{display:flex;align-items:center;gap: var(--space-2);margin:0;font-size:var(--fs-md)}
.password-section h3 svg{width:16px;height:16px}
.password-hint{margin:0;color:var(--muted);font-size:var(--fs-xs)}
.password-row{display:flex;gap: var(--space-2)}
.password-row input{flex:1;min-width:0}
.password-section.muted{opacity:.62}
.notif-group{display:grid;gap: var(--space-2)}
.notif-group h3{display:flex;align-items:center;gap: var(--space-2);margin:0;font-size:var(--fs-md)}
.notif-group h3 svg{width:16px;height:16px}
.notif-group .hint{margin:0;color:var(--muted);font-size:var(--fs-xs)}
</style>
