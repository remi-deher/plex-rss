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

  <div class="segmented page-tabs">
    <button :class="{active:tab==='history'}" @click="tab='history';offset=0;load()">Historique</button>
    <button :class="{active:tab==='pending'}" @click="tab='pending';offset=0;load()">En attente <span v-if="pendingTotal" class="badge">{{ pendingTotal }}</span></button>
  </div>

  <div class="toolbar wrap">
    <input v-model="search" class="search" type="search" placeholder="Media, destinataire ou evenement">
    
    <!-- Filtres Personnalises (Uniquement Historique) -->
    <div v-if="tab==='history'" class="filters-wrap">
      
      <!-- Filtre Etat -->
      <div class="custom-dropdown" v-click-outside="() => { if (activeDropdown === 'state') activeDropdown = null }">
        <button class="secondary" @click="activeDropdown = activeDropdown === 'state' ? null : 'state'" :class="{active: state}">
          Etat <span class="badge" v-if="state">{{ state === 'success' ? 'Envoyees' : 'Erreurs' }}</span> <ChevronDown class="dropdown-icon" />
        </button>
        <div class="dropdown-menu" v-if="activeDropdown === 'state'">
          <label class="dropdown-item">
            <input type="radio" v-model="state" value=""> Tous les etats
          </label>
          <label class="dropdown-item">
            <input type="radio" v-model="state" value="success"> Envoyees
          </label>
          <label class="dropdown-item">
            <input type="radio" v-model="state" value="error"> Erreurs
          </label>
        </div>
      </div>

      <!-- Filtre Types (Choix Multiple) -->
      <div class="custom-dropdown" v-click-outside="() => { if (activeDropdown === 'types') activeDropdown = null }">
        <button class="secondary" @click="activeDropdown = activeDropdown === 'types' ? null : 'types'" :class="{active: selectedTypes.length > 0}">
          Types <span class="badge" v-if="selectedTypes.length">{{ selectedTypes.length }}</span> <ChevronDown class="dropdown-icon" />
        </button>
        <div class="dropdown-menu" v-if="activeDropdown === 'types'">
          <label class="dropdown-item" v-for="typeOpt in typeOptions" :key="typeOpt.value">
            <input type="checkbox" v-model="selectedTypes" :value="typeOpt.value"> {{ typeOpt.label }}
          </label>
        </div>
      </div>

      <!-- Filtre Utilisateurs (Choix Multiple) -->
      <div class="custom-dropdown" v-click-outside="() => { if (activeDropdown === 'users') activeDropdown = null }">
        <button class="secondary" @click="activeDropdown = activeDropdown === 'users' ? null : 'users'" :class="{active: selectedUsers.length > 0}">
          Utilisateurs <span class="badge" v-if="selectedUsers.length">{{ selectedUsers.length }}</span> <ChevronDown class="dropdown-icon" />
        </button>
        <div class="dropdown-menu scrollable" v-if="activeDropdown === 'users'">
          <label class="dropdown-item" v-for="user in users" :key="user.id">
            <input type="checkbox" v-model="selectedUsers" :value="user.id"> {{ user.custom_name || user.display_name || user.plex_user_id }}
          </label>
          <div v-if="!users.length" class="empty-dropdown">Aucun utilisateur.</div>
        </div>
      </div>

    </div>

    <!-- Actions "En attente" -->
    <div v-if="tab==='pending'&&rows.length" class="actions">
      <button class="secondary" @click="purge(true)"><CheckCheck/>Purger et marquer traitees</button>
      <button class="secondary danger" @click="purge(false)"><Trash2/>Purger</button>
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
  { value: 'system', label: 'Erreurs systeme' }
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

<style scoped>
.filters-wrap {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.custom-dropdown {
  position: relative;
}

.custom-dropdown button {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 20px;
  background: var(--bg-modifier);
  border: 1px solid var(--border-color);
  color: var(--text-color);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.custom-dropdown button:hover,
.custom-dropdown button.active {
  background: var(--bg-modifier-hover);
  border-color: var(--primary-color);
}

.custom-dropdown button .dropdown-icon {
  width: 14px;
  height: 14px;
  opacity: 0.7;
}

.custom-dropdown .badge {
  background: var(--primary-color);
  color: #fff;
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 10px;
}

.dropdown-menu {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.5);
  min-width: 200px;
  z-index: 100;
  padding: 8px 0;
}

.dropdown-menu.scrollable {
  max-height: 300px;
  overflow-y: auto;
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  cursor: pointer;
  font-size: 13px;
  transition: background 0.1s;
}

.dropdown-item:hover {
  background: rgba(255, 255, 255, 0.05);
}

.dropdown-item input {
  margin: 0;
  cursor: pointer;
}

.empty-dropdown {
  padding: 8px 16px;
  font-size: 13px;
  color: var(--text-muted);
  text-align: center;
}
</style>
