<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>Demandes</h1>
        <p>Validation, suivi et traitement des demandes.</p>
      </div>
      <div class="actions">
        <button v-if="isAdmin" class="secondary" :disabled="busy" @click="runUtility('/api/requests/poll')">
          <RefreshCw/>Verifier maintenant
        </button>
        <button class="icon-button" :disabled="loading" title="Actualiser" @click="load">
          <RefreshCw :class="{spin:loading}"/>
        </button>
      </div>
    </header>

    <div class="filters-panel">
      <div class="filter-row">
        <input v-model="query" class="search" type="search" placeholder="Rechercher un titre" @input="scheduleLoad">
        <div class="segmented">
          <button :class="{active:view==='grid'}" title="Grille" @click="setView('grid')"><Grid2X2/></button>
          <button :class="{active:view==='list'}" title="Liste" @click="setView('list')"><List/></button>
        </div>
      </div>

      <div class="filter-toolbar">
        <span class="filter-label">Statut:</span>
        <div class="multi-select" :class="{open:statusMenuOpen}">
          <button class="filter-pill dropdown-toggle" @click="toggleMenu('status')">
            {{ statusFilters.length ? statusFilters.map(label).join(', ') : 'Tous les statuts' }}
            <ChevronDown/>
          </button>
          <div v-if="statusMenuOpen" class="multi-select-menu" @click.stop>
            <label v-for="value in statuses" :key="value" class="check">
              <input type="checkbox" :value="value" v-model="statusFilters"> {{ label(value) }}
            </label>
            <button v-if="statusFilters.length" class="text-button clear-selection" @click="statusFilters=[]">Effacer</button>
          </div>
        </div>

        <div class="divider"></div>
        <span class="filter-label">Type:</span>
        <div class="multi-select" :class="{open:typeMenuOpen}">
          <button class="filter-pill dropdown-toggle" @click="toggleMenu('type')">
            {{ typeFilters.length ? typeFilters.map(typeLabel).join(', ') : 'Tous les types' }}
            <ChevronDown/>
          </button>
          <div v-if="typeMenuOpen" class="multi-select-menu" @click.stop>
            <label v-for="value in types" :key="value" class="check">
              <input type="checkbox" :value="value" v-model="typeFilters"> {{ typeLabel(value) }}
            </label>
            <button v-if="typeFilters.length" class="text-button clear-selection" @click="typeFilters=[]">Effacer</button>
          </div>
        </div>

        <template v-if="sources.length">
          <div class="divider"></div>
          <span class="filter-label">Source:</span>
          <div class="multi-select" :class="{open:sourceMenuOpen}">
            <button class="filter-pill dropdown-toggle" @click="toggleMenu('source')">
              {{ sourceFilters.length ? sourceFilters.join(', ') : 'Toutes les sources' }}
              <ChevronDown/>
            </button>
            <div v-if="sourceMenuOpen" class="multi-select-menu" @click.stop>
              <label v-for="value in sources" :key="value" class="check">
                <input type="checkbox" :value="value" v-model="sourceFilters"> {{ value }}
              </label>
              <button v-if="sourceFilters.length" class="text-button clear-selection" @click="sourceFilters=[]">Effacer</button>
            </div>
          </div>
        </template>

        <template v-if="requesters.length > 1">
          <div class="divider"></div>
          <span class="filter-label">Demandeur:</span>
          <div class="multi-select" :class="{open:requesterMenuOpen}">
            <button class="filter-pill dropdown-toggle" @click="toggleMenu('requester')">
              {{ requesterFilters.length ? requesterLabels : 'Tous les demandeurs' }}
              <ChevronDown/>
            </button>
            <div v-if="requesterMenuOpen" class="multi-select-menu" @click.stop>
              <label v-for="r in requesters" :key="r.id" class="check">
                <input type="checkbox" :value="r.id" v-model="requesterFilters"> {{ r.label }}
              </label>
              <button v-if="requesterFilters.length" class="text-button clear-selection" @click="requesterFilters=[]">Effacer</button>
            </div>
          </div>
        </template>
      </div>
    </div>

    <div v-if="isAdmin&&selectedIds.length" class="bulk-bar">
      <strong>{{ selectedIds.length }} selectionnee(s)</strong>
      <button class="secondary" @click="bulk('retry')"><RotateCcw/>Relancer</button>
      <button class="secondary" @click="bulk('mark-processed')"><CheckCheck/>Traiter</button>
      <button class="secondary danger" @click="bulk('delete')"><Trash2/>Supprimer</button>
      <button class="icon-button" title="Annuler" @click="selectedIds=[]"><X/></button>
    </div>

    <p v-if="error" class="notice error-text">{{ error }}</p>

    <section :class="view==='grid'?'media-grid':'media-list'">
      <article v-for="row in filtered" :key="row.id" class="media-card request-card" :class="{list:view==='list'}">
        <div class="poster-shell" @click="detail=row">
          <img v-if="row.poster_url" :src="proxyUrl(row.poster_url)" alt="" @error="$event.target.style.display='none'">
          <div v-else class="poster-fallback"><Film/></div>
          <span v-if="view==='grid'" class="badge status-tag" :class="row.status">{{ label(row.status) }}</span>
          <label v-if="isAdmin&&view==='grid'" class="select-tag" @click.stop>
            <input v-model="selectedIds" type="checkbox" :value="row.id">
          </label>
        </div>
        <div class="request-body">
          <div class="request-title-row">
            <button class="text-button" @click="detail=row">
              <strong>{{ row.title }}</strong>
              <span v-if="row.year">{{ row.year }}</span>
            </button>
            <span v-if="view==='list'" class="badge status-tag" :class="row.status">{{ label(row.status) }}</span>
            <label v-if="isAdmin&&view==='list'" class="select-tag" @click.stop>
              <input v-model="selectedIds" type="checkbox" :value="row.id">
            </label>
          </div>
          <small>
            {{ row.media_type==='show'?'Serie':'Film' }}
            · {{ row.requested_by||row.plex_user||row.plex_user_id||'?' }}
            <template v-if="row.source"> · {{ row.source }}</template>
            · {{ formatDate(row.requested_at) }}
          </small>
          <div class="request-actions">
            <button v-if="row.status==='pending_approval'&&isAdmin" class="icon-button success" title="Approuver" @click="act(row,'approve')"><Check/></button>
            <button v-if="row.status==='pending_approval'&&isAdmin" class="icon-button danger" title="Refuser" @click="reject(row)"><Ban/></button>
            <button v-if="row.arr_id" class="icon-button" title="Rechercher une release" @click="router.push(`/releases/${row.id}`)"><Search/></button>
            <button v-if="row.status==='failed'&&isAdmin" class="icon-button" title="Relancer" @click="act(row,'retry')"><RotateCcw/></button>
            <button v-if="row.status!=='available'" class="icon-button danger" title="Annuler" @click="act(row,'cancel')"><X/></button>
          </div>
        </div>
      </article>
    </section>
    <p v-if="!loading&&!filtered.length" class="empty">Aucune demande.</p>

    <MediaDetailDrawer v-if="detail" :item="detail" mode="request" @close="detail=null" @updated="load"/>
  </div>
</template>
<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { Ban, Check, CheckCheck, ChevronDown, Film, Grid2X2, List, RefreshCw, RotateCcw, Search, Trash2, X } from '@lucide/vue';
import { useRoute, useRouter } from 'vue-router';
import { api } from '@/api';
import { useRealtime } from '@/events';
import MediaDetailDrawer from '@/components/MediaDetailDrawer.vue';

const route = useRoute();
const router = useRouter();

const rows = ref([]);
const query = ref(route.query.query || '');
const statusFilters = ref(route.query.status ? [route.query.status] : []);
const statusMenuOpen = ref(false);
const typeFilters = ref(route.query.type ? [route.query.type] : []);
const typeMenuOpen = ref(false);
const sourceFilters = ref([]);
const sourceMenuOpen = ref(false);
const requesterFilters = ref([]);
const requesterMenuOpen = ref(false);
const selectedIds = ref([]);
const detail = ref(null);
const loading = ref(false);
const busy = ref(false);
const error = ref('');
const isAdmin = ref(false);
const view = ref(localStorage.getItem('requests.view') || 'grid');

let timer, fallback;

const statuses = ['pending_approval', 'pending', 'sent_to_arr', 'available', 'failed', 'rejected'];
const types = ['movie', 'show'];
const sources = computed(() => [...new Set(rows.value.map(x => x.source).filter(Boolean))]);
const requesters = computed(() => {
  const seen = new Map();
  for (const row of rows.value) {
    const id = row.plex_user_id;
    if (!id || seen.has(id)) continue;
    seen.set(id, row.requested_by || row.plex_user || id);
  }
  return [...seen.entries()].map(([id, label]) => ({ id, label })).sort((a, b) => a.label.localeCompare(b.label));
});
const requesterLabels = computed(() => {
  const byId = new Map(requesters.value.map(r => [r.id, r.label]));
  return requesterFilters.value.map(id => byId.get(id) || id).join(', ');
});
const filtered = computed(() => rows.value.filter(row =>
  (!statusFilters.value.length || statusFilters.value.includes(row.status)) &&
  (!typeFilters.value.length || typeFilters.value.includes(row.media_type)) &&
  (!sourceFilters.value.length || sourceFilters.value.includes(row.source)) &&
  (!requesterFilters.value.length || requesterFilters.value.includes(row.plex_user_id))
));

const menus = { status: statusMenuOpen, type: typeMenuOpen, source: sourceMenuOpen, requester: requesterMenuOpen };
function toggleMenu(name) {
  for (const key in menus) menus[key].value = key === name ? !menus[key].value : false;
}
function closeAllMenus() {
  for (const key in menus) menus[key].value = false;
}
function typeLabel(value) {
  return value === 'show' ? 'Series' : 'Films';
}

function label(value) {
  return ({
    pending_approval: 'A approuver',
    pending: 'En attente',
    sent_to_arr: 'Transmise',
    available: 'Disponible',
    failed: 'Echec',
    rejected: 'Refusee'
  })[value] || value;
}

function formatDate(value) {
  return value ? new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium' }).format(new Date(value)) : '-';
}

function proxyUrl(url) {
  if (!url) return url;
  if (url.startsWith('http://') || (url.startsWith('https://') && /\/(192\.168\.|10\.|127\.)/.test(url))) {
    return `/api/image-proxy?url=${encodeURIComponent(url)}`;
  }
  return url;
}

function setView(value) {
  view.value = value;
  localStorage.setItem('requests.view', value);
}

function scheduleLoad() {
  clearTimeout(timer);
  timer = setTimeout(load, 250);
}

async function load() {
  loading.value = true;
  error.value = '';
  try {
    rows.value = await api(`/api/requests${query.value.trim() ? `?query=${encodeURIComponent(query.value.trim())}` : ''}`);
    selectedIds.value = selectedIds.value.filter(id => rows.value.some(x => x.id === id));
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}

async function act(row, action) {
  busy.value = true;
  try {
    if (action === 'cancel' && isAdmin.value) await api(`/api/requests/${row.id}`, { method: 'DELETE' });
    else await api(`/api/requests/${row.id}/${action}`, { method: 'POST' });
    await load();
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}

async function reject(row) {
  const reason = prompt('Motif du refus', 'Demande refusee par un administrateur');
  if (reason === null) return;
  busy.value = true;
  try {
    await api(`/api/requests/${row.id}/reject`, { method: 'POST', body: JSON.stringify({ reason }) });
    await load();
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}

async function bulk(action) {
  if (action === 'delete' && !confirm(`Supprimer ${selectedIds.value.length} demandes ?`)) return;
  busy.value = true;
  try {
    await api(`/api/requests/bulk/${action}`, { method: 'POST', body: JSON.stringify({ ids: selectedIds.value, delete_from_arr: false, delete_files: false }) });
    selectedIds.value = [];
    await load();
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}

async function runUtility(path) {
  busy.value = true;
  try {
    await api(path, { method: 'POST' });
    await load();
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}

function handleOutsideClick(event) {
  if (!event.target.closest('.multi-select')) closeAllMenus();
}

useRealtime(['request.updated'], load);
onMounted(async () => {
  const session = await api('/api/session').catch(() => null);
  isAdmin.value = Boolean(session?.is_owner || session?.role === 'admin');
  await load();
  fallback = setInterval(load, 120000);
  document.addEventListener('click', handleOutsideClick);
});
onUnmounted(() => {
  clearTimeout(timer);
  clearInterval(fallback);
  document.removeEventListener('click', handleOutsideClick);
});
</script>

<style scoped>
.request-card {
  overflow: hidden;
}
.request-card .poster-shell {
  cursor: pointer;
}
.poster-shell .status-tag {
  position: absolute;
  top: 8px;
  left: 8px;
  background: rgba(20, 20, 20, .9);
}
.request-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.request-title-row .status-tag {
  flex-shrink: 0;
}
.poster-shell .select-tag {
  position: absolute;
  top: 8px;
  right: 8px;
  padding: 4px;
  border-radius: 6px;
  background: rgba(20, 20, 20, .9);
}
.select-tag {
  display: flex;
  flex-shrink: 0;
  cursor: pointer;
}
.request-body {
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.request-body .text-button {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.request-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}
.media-card.list .request-body {
  align-self: center;
}
.media-card.list .request-actions {
  margin-top: 4px;
}
</style>
