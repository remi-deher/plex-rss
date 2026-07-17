<template>
  <div v-if="selectedIds.length" class="bulk-bar">
    <strong>{{ selectedIds.length }} selectionne(s)</strong>
    <button class="secondary" @click="$emit('bulk-status',true)"><Power/>Activer</button>
    <button class="secondary" @click="$emit('bulk-status',false)"><PowerOff/>Desactiver</button>
    <select v-model="bulkNotifyField"><option v-for="f in bulkNotifyFields" :key="f.value" :value="f.value">{{ f.label }}</option></select>
    <button class="secondary" @click="$emit('bulk-notify',bulkNotifyField,true)"><Bell/>Activer</button>
    <button class="secondary" @click="$emit('bulk-notify',bulkNotifyField,false)"><BellOff/>Desactiver</button>
    <button class="secondary danger" @click="$emit('bulk-delete')"><Trash2/>Supprimer</button>
    <button class="icon-button" @click="selectedIds=[]"><X/></button>
  </div>

  <section class="panel table-wrap table-cards rich">
    <table>
      <thead>
        <tr><th><input type="checkbox" :checked="allSelected" @change="toggleAll"></th><th>Utilisateur</th><th>Email</th><th>Source</th><th>Role</th><th>Demandes</th><th>Connexion</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="user in rows" :key="user.id">
          <td class="card-select"><input v-model="selectedIds" type="checkbox" :value="user.id"></td>
          <td class="card-title"><button class="text-button" @click="$emit('open',user.id)"><strong>{{ displayName(user) }}</strong><small>{{ user.plex_user_id }}</small></button></td>
          <td data-label="Email">{{ user.notification_email||user.plex_email||'-' }}</td>
          <td data-label="Source">{{ user.source||'plex' }}</td>
          <td data-label="Role"><span class="badge" :class="user.role==='admin'?'available':'pending'">{{ user.role }}</span></td>
          <td data-label="Demandes">{{ user.stats?.total??user.request_count??'-' }}</td>
          <td data-label="Connexion">{{ user.can_login?'Autorisee':'Bloquee' }}</td>
          <td class="card-actions"><button class="icon-button" :title="user.enabled?'Desactiver':'Activer'" @click="$emit('toggle',user)"><Power/></button></td>
        </tr>
      </tbody>
    </table>
    <p v-if="!loading&&!rows.length" class="empty">Aucun utilisateur.</p>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue';
import { Bell, BellOff, Power, PowerOff, Trash2, X } from '@lucide/vue';

const props = defineProps({
  rows: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
});
defineEmits(['open', 'toggle', 'bulk-status', 'bulk-notify', 'bulk-delete']);

const selectedIds = ref([]);
const bulkNotifyField = ref('notify_on_request');
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
function toggleAll(event) { selectedIds.value = event.target.checked ? props.rows.map(x => x.id) : []; }

defineExpose({ selectedIds });
</script>
