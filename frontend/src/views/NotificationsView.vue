<template>
<div class="page">
  <header class="page-head">
    <div>
      <h1>Notifications</h1>
      <p>Historique des envois et file de distribution.</p>
    </div>
    <button class="icon-button" :disabled="loading" title="Actualiser" @click="load">
      <RefreshCw :class="{spin:loading}"/>
    </button>
  </header>

  <nav class="detail-tabs">
    <button :class="{active:tab==='history'}" @click="tab='history';offset=0;load()">Historique</button>
    <button :class="{active:tab==='pending'}" @click="tab='pending';offset=0;load()">En attente <span v-if="pendingTotal" class="badge">{{ pendingTotal }}</span></button>
  </nav>

  <div class="toolbar wrap">
    <input v-model="search" class="search" type="search" placeholder="Media, destinataire ou evenement">

    <!-- Actions "En attente" -->
    <div v-if="tab==='pending'&&rows.length" class="actions">
      <button class="secondary" @click="purge(true)"><CheckCheck/>Purger et marquer traitees</button>
      <button class="secondary danger" @click="purge(false)"><Trash2/>Purger</button>
    </div>
  </div>

  <NotificationsFiltersBar
    v-if="tab==='history'"
    v-model:state="state"
    v-model:selected-types="selectedTypes"
    v-model:selected-users="selectedUsers"
    :users="users"
    :type-options="typeOptions"
  />

  <p v-if="error" class="notice error-text">{{ error }}</p>

  <NotificationsTable ref="tableRef" :rows="rows" :tab="tab" :loading="loading" @resend="resend"/>

  <div v-if="tab==='history'&&total>limit" class="pagination">
    <button class="secondary" :disabled="offset===0" @click="page(-1)"><ChevronLeft/>Precedent</button>
    <span>{{ offset+1 }}-{{ Math.min(offset+limit,total) }} sur {{ total }}</span>
    <button class="secondary" :disabled="offset+limit>=total" @click="page(1)">Suivant<ChevronRight/></button>
  </div>
</div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue';
import { CheckCheck, ChevronLeft, ChevronRight, RefreshCw, Trash2 } from '@lucide/vue';
import { api } from '@/api';
import { useRealtime } from '@/events';
import NotificationsFiltersBar from '@/components/notifications/NotificationsFiltersBar.vue';
import NotificationsTable from '@/components/notifications/NotificationsTable.vue';

const rows = ref([]);
const users = ref([]);
const tab = ref('history');
const loading = ref(false);
const error = ref('');
const search = ref('');
const state = ref('');
const selectedTypes = ref([]);
const selectedUsers = ref([]);
const tableRef = ref(null);

const typeOptions = [
  { value: 'request', label: 'Demandes' },
  { value: 'available', label: 'Disponibilites' },
  { value: 'upgrade', label: 'Améliorations (VF)' },
  { value: 'correction', label: 'Corrections' },
  { value: 'failed', label: 'Erreurs systeme' }
];

const total = ref(0);
const pendingTotal = ref(0);
const offset = ref(0);
const limit = 50;

async function loadUsers() {
  try {
    const data = await api('/api/users');
    users.value = data || [];
  } catch(e) {
    console.error("Erreur chargement utilisateurs", e);
  }
}

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const q = new URLSearchParams({ limit, offset: offset.value });
    if (state.value) q.append('state', state.value);
    if (selectedTypes.value.length) q.append('types', selectedTypes.value.join(','));
    if (selectedUsers.value.length) q.append('users', selectedUsers.value.join(','));
    if (search.value) q.append('search', search.value);

    const data = tab.value === 'history'
      ? await api(`/api/notifications/log?${q.toString()}`)
      : await api('/api/notifications/pending');

    rows.value = data.items || [];
    total.value = data.total || 0;

    if (tab.value === 'pending') {
      pendingTotal.value = data.total || 0;
    } else {
      api('/api/notifications/pending').then(x => pendingTotal.value = x.total).catch(() => {});
    }
  } catch(e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}

async function resend(row) {
  await api(`/api/notifications/${row.id}/resend`, { method: 'POST' });
  await load();
}

async function purge(markHandled) {
  const ids = tableRef.value?.selected || [];
  if (!confirm(`Purger ${ids.length ? ids.length : 'toute la file'} notification(s) ?`)) return;
  await api('/api/notifications/pending/purge', { method: 'POST', body: JSON.stringify({ ids, mark_handled: markHandled }) });
  if (tableRef.value) tableRef.value.selected = [];
  await load();
}

function page(delta) {
  offset.value = Math.max(0, offset.value + delta * limit);
  load();
}

// Relance auto sur modif des filtres (avec reset de l'offset)
watch([state, selectedTypes, selectedUsers], () => {
  offset.value = 0;
  load();
}, { deep: true });

let searchTimeout;
watch(search, () => {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(() => {
    offset.value = 0;
    load();
  }, 300);
});

useRealtime(['notification.updated'], load);

onMounted(() => {
  loadUsers();
  load();
});
</script>
