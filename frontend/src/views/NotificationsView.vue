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

  <!-- Filtres Personnalises (Uniquement Historique) -->
  <div v-if="tab==='history'" class="filter-pills-scroll">
    <span class="filter-label">Etat:</span>
    <div class="multi-select" :class="{open:activeDropdown==='state'}" v-click-outside="() => { if (activeDropdown === 'state') activeDropdown = null }">
      <button class="filter-pill dropdown-toggle" @click="activeDropdown = activeDropdown === 'state' ? null : 'state'">
        {{ state === 'success' ? 'Envoyees' : state === 'error' ? 'Erreurs' : 'Tous les etats' }}
        <ChevronDown/>
      </button>
      <div v-if="activeDropdown === 'state'" class="multi-select-menu" @click.stop>
        <label class="check"><input type="radio" v-model="state" value=""> Tous les etats</label>
        <label class="check"><input type="radio" v-model="state" value="success"> Envoyees</label>
        <label class="check"><input type="radio" v-model="state" value="error"> Erreurs</label>
      </div>
    </div>

    <div class="divider"></div>
    <span class="filter-label">Types:</span>
    <div class="multi-select" :class="{open:activeDropdown==='types'}" v-click-outside="() => { if (activeDropdown === 'types') activeDropdown = null }">
      <button class="filter-pill dropdown-toggle" @click="activeDropdown = activeDropdown === 'types' ? null : 'types'">
        {{ selectedTypes.length ? selectedTypes.map(v=>typeOptions.find(o=>o.value===v)?.label||v).join(', ') : 'Tous les types' }}
        <ChevronDown/>
      </button>
      <div v-if="activeDropdown === 'types'" class="multi-select-menu" @click.stop>
        <label class="check" v-for="typeOpt in typeOptions" :key="typeOpt.value"><input type="checkbox" v-model="selectedTypes" :value="typeOpt.value"> {{ typeOpt.label }}</label>
        <button v-if="selectedTypes.length" class="text-button clear-selection" @click="selectedTypes=[]">Effacer</button>
      </div>
    </div>

    <div class="divider"></div>
    <span class="filter-label">Utilisateurs:</span>
    <div class="multi-select" :class="{open:activeDropdown==='users'}" v-click-outside="() => { if (activeDropdown === 'users') activeDropdown = null }">
      <button class="filter-pill dropdown-toggle" @click="activeDropdown = activeDropdown === 'users' ? null : 'users'">
        {{ selectedUsers.length ? `${selectedUsers.length} selectionne(s)` : 'Tous les utilisateurs' }}
        <ChevronDown/>
      </button>
      <div v-if="activeDropdown === 'users'" class="multi-select-menu" @click.stop>
        <label class="check" v-for="user in users" :key="user.id"><input type="checkbox" v-model="selectedUsers" :value="user.id"> {{ user.custom_name || user.display_name || user.plex_user_id }}</label>
        <p v-if="!users.length" class="empty">Aucun utilisateur.</p>
        <button v-if="selectedUsers.length" class="text-button clear-selection" @click="selectedUsers=[]">Effacer</button>
      </div>
    </div>
  </div>

  <p v-if="error" class="notice error-text">{{ error }}</p>

  <section class="panel table-wrap">
    <table>
      <thead>
        <tr>
          <th><input v-if="tab==='pending'" type="checkbox" :checked="allSelected" @change="toggleAll"></th>
          <th>Date</th>
          <th>Evenement</th>
          <th>Media</th>
          <th>Destinataires</th>
          <th>Etat</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.id">
          <td><input v-if="tab==='pending'" v-model="selected" type="checkbox" :value="row.id"></td>
          <td>{{ formatDate(row.sent_at||row.created_at) }}</td>
          <td>
            <strong>{{ row.event_label||row.event }}</strong>
            <small class="table-detail">{{ context(row) }}</small>
          </td>
          <td>{{ row.media_title||'-' }}</td>
          <td>{{ row.recipient||(row.recipients||[]).join(', ')||'-' }}</td>
          <td>
            <span class="badge" :class="row.success===false||row.valid===false?'failed':tab==='pending'?'pending':'available'">
              {{ row.success===false?'Erreur':row.valid===false?'Invalide':tab==='pending'?'En attente':'Envoyee' }}
            </span>
            <small v-if="row.error_msg" class="table-detail error-text">{{ row.error_msg }}</small>
          </td>
          <td>
            <button v-if="tab==='history'&&!row.success" class="icon-button" title="Renvoyer" @click="resend(row)"><Send/></button>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="!loading&&!rows.length" class="empty">Aucune notification.</p>
  </section>

  <div v-if="tab==='history'&&total>limit" class="pagination">
    <button class="secondary" :disabled="offset===0" @click="page(-1)"><ChevronLeft/>Precedent</button>
    <span>{{ offset+1 }}-{{ Math.min(offset+limit,total) }} sur {{ total }}</span>
    <button class="secondary" :disabled="offset+limit>=total" @click="page(1)">Suivant<ChevronRight/></button>
  </div>
</div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { CheckCheck, ChevronLeft, ChevronRight, RefreshCw, Send, Trash2, ChevronDown } from '@lucide/vue';
import { api } from '@/api';
import { useRealtime } from '@/events';

// --- Directive custom pour fermer les menus au clic exterieur ---
const vClickOutside = {
  mounted(el, binding) {
    el.clickOutsideEvent = function(event) {
      if (!(el === event.target || el.contains(event.target))) {
        binding.value(event);
      }
    };
    document.addEventListener('click', el.clickOutsideEvent);
  },
  unmounted(el) {
    document.removeEventListener('click', el.clickOutsideEvent);
  }
};

const rows = ref([]);
const users = ref([]);
const tab = ref('history');
const loading = ref(false);
const error = ref('');
const search = ref('');
const state = ref('');
const selectedTypes = ref([]);
const selectedUsers = ref([]);
const activeDropdown = ref(null);

const typeOptions = [
  { value: 'request', label: 'Demandes' },
  { value: 'available', label: 'Disponibilites' },
  { value: 'upgrade', label: 'Améliorations (VF)' },
  { value: 'correction', label: 'Corrections' },
  { value: 'failed', label: 'Erreurs systeme' }
];

const selected = ref([]);
const total = ref(0);
const pendingTotal = ref(0);
const offset = ref(0);
const limit = 50;

const allSelected = computed(() => rows.value.length && rows.value.every(x => selected.value.includes(x.id)));

function formatDate(v) {
  return v ? new Intl.DateTimeFormat('fr-FR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(v)) : '-';
}

function context(row) {
  const c = row.context || {};
  return [c.scope, c.language, c.is_upgrade ? 'amelioration' : ''].filter(Boolean).join(' - ') || row.event_description || '';
}

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
  const ids = selected.value;
  if (!confirm(`Purger ${ids.length ? ids.length : 'toute la file'} notification(s) ?`)) return;
  await api('/api/notifications/pending/purge', { method: 'POST', body: JSON.stringify({ ids, mark_handled: markHandled }) });
  selected.value = [];
  await load();
}

function toggleAll(e) {
  selected.value = e.target.checked ? rows.value.map(x => x.id) : [];
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
