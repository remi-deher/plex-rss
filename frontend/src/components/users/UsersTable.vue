<template>
  <div v-if="selectedIds.length" class="bulk-bar">
    <strong>{{ selectedIds.length }} selectionne(s)</strong>
    <button class="secondary" @click="$emit('bulk-status',true)"><Power/>Activer</button>
    <button class="secondary" @click="$emit('bulk-status',false)"><PowerOff/>Desactiver</button>
    <select v-model="bulkNotifyField"><option v-for="f in bulkNotifyFields" :key="f.value" :value="f.value">{{ f.label }}</option></select>
    <button class="secondary" @click="$emit('bulk-notify',bulkNotifyField,true)"><Bell/>Activer</button>
    <button class="secondary" @click="$emit('bulk-notify',bulkNotifyField,false)"><BellOff/>Desactiver</button>
    <select v-model="bulkRole"><option value="user">Utilisateur</option><option value="admin">Administrateur</option></select>
    <button class="secondary" @click="$emit('bulk-permissions',{role:bulkRole})"><Shield/>Appliquer le rôle</button>
    <button class="secondary" @click="$emit('bulk-permissions',{can_login:true})"><LogIn/>Autoriser la connexion</button>
    <button class="secondary" @click="$emit('bulk-permissions',{can_login:false})"><LogOut/>Bloquer la connexion</button>
    <button class="secondary danger" @click="$emit('bulk-delete')"><Trash2/>Supprimer</button>
    <button class="icon-button" title="Désélectionner" aria-label="Désélectionner" @click="selectedIds=[]"><X/></button>
  </div>

  <section class="panel table-wrap table-cards rich">
    <table>
      <thead>
        <tr><th><input type="checkbox" :checked="allSelected" @change="toggleAll"></th><th>Utilisateur</th><th>Notifications</th><th>Source</th><th>Role</th><th>Demandes</th><th>Dernière activité</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="user in rows" :key="user.id">
          <td class="card-select"><input v-model="selectedIds" type="checkbox" :value="user.id"></td>
          <td class="card-title"><button class="text-button" @click="$emit('open',user.id)"><strong>{{ displayName(user) }}</strong><small>{{ user.plex_user_id }} · {{ user.enabled?'Actif':'Désactivé' }}</small></button></td>
          <td data-label="Notifications"><div class="user-notification-cell"><span :class="['status-dot',notificationState(user)]"></span><div>{{ user.notification_email||user.plex_email||user.notify_admin?'Via administrateur':'Aucun destinataire' }}<small v-if="user.has_notification_error">Échec récent</small></div></div></td>
          <td data-label="Source">{{ user.source||'plex' }}</td>
          <td data-label="Role"><span class="badge" :class="user.role==='admin'?'available':'pending'">{{ user.role }}</span></td>
          <td data-label="Demandes"><strong>{{ user.stats?.total??user.request_count??0 }}</strong><small v-if="user.stats?.pending_approval" class="pending-copy">{{ user.stats.pending_approval }} à approuver</small></td>
          <td data-label="Dernière activité">{{ formatDate(user.last_requested_at) }}<small>{{ user.can_login?'Connexion autorisée':'Connexion bloquée' }}</small></td>
          <td class="card-actions"><button class="icon-button" :title="user.enabled?'Desactiver':'Activer'" :aria-label="user.enabled?'Desactiver':'Activer'" @click="$emit('toggle',user)"><Power/></button></td>
        </tr>
      </tbody>
    </table>
    <p v-if="!loading&&!rows.length" class="empty">Aucun utilisateur.</p>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue';
import { Bell, BellOff, LogIn, LogOut, Power, PowerOff, Shield, Trash2, X } from '@lucide/vue';

const props = defineProps({
  rows: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
});
defineEmits(['open', 'toggle', 'bulk-status', 'bulk-notify', 'bulk-permissions', 'bulk-delete']);

const selectedIds = ref([]);
const bulkNotifyField = ref('notify_on_request');
const bulkRole=ref('user');
const bulkNotifyFields = [
  { value: 'notify_on_request', label: 'Notif. demande' },
  { value: 'notify_on_available', label: 'Notif. disponibilite' },
  { value: 'notify_digest', label: 'Digest' },
  { value: 'notify_admin', label: "Copie a l'administrateur" },
  { value: 'notify_vf_movie', label: 'VF films' },
  { value: 'notify_vf_series', label: 'VF series' },
  { value: 'notify_vf_anime', label: 'VF animes' },
];
const allSelected = computed(() => props.rows.length && props.rows.every(x => selectedIds.value.includes(x.id)));

function displayName(user) { return user?.custom_name || user?.display_name || user?.plex_user_id || ''; }
function notificationState(user){return user.has_notification_error?'error':user.notification_email||user.plex_email||user.notify_admin?'active':'missing'}
function formatDate(value){return value?new Intl.DateTimeFormat('fr-FR',{dateStyle:'short'}).format(new Date(value)):'Aucune'}
function toggleAll(event) { selectedIds.value = event.target.checked ? props.rows.map(x => x.id) : []; }

defineExpose({ selectedIds });
</script>
<style scoped>
.user-notification-cell{display:flex;align-items:center;gap:7px}.user-notification-cell>div{display:grid;gap:2px}.user-notification-cell small,.card-title small,td>small{display:block;color:var(--muted);font-size:9px}.status-dot{width:7px;height:7px;border-radius:50%;background:var(--muted)}.status-dot.active{background:var(--success)}.status-dot.error{background:var(--danger)}.status-dot.missing{background:var(--accent)}.pending-copy{color:var(--accent)}.bulk-bar{overflow-x:auto;padding-bottom:max(8px,env(safe-area-inset-bottom))}
</style>
