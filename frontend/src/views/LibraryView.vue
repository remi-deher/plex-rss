<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>Bibliotheque</h1>
        <p>Catalogue Plex, demandes en cours et suivi des versions.</p>
      </div>
      <button class="icon-button" :disabled="loading" title="Actualiser" @click="load">
        <RefreshCw :class="{spin:loading}"/>
      </button>
    </header>
    
    <section class="metric-grid compact-metrics">
      <article v-for="entry in metrics" :key="entry.label" class="metric-card">
        <span>{{ entry.label }}</span>
        <strong>{{ entry.value }}</strong>
      </article>
    </section>

    <div class="filters-panel">
      <div class="filter-row">
        <input v-model="query" class="search" type="search" placeholder="Rechercher" @input="scheduleLoad">
        <div class="segmented">
          <button :class="{active:view==='grid'}" title="Grille" @click="setView('grid')">
            <Grid2X2/>
          </button>
          <button :class="{active:view==='list'}" title="Liste" @click="setView('list')">
            <List/>
          </button>
        </div>
      </div>
      
      <div class="filter-pills-scroll">
        <span class="filter-label">Type:</span>
        <button class="filter-pill" :class="{active:type===''}" @click="setType('')">Tout</button>
        <button class="filter-pill" :class="{active:type==='movie'}" @click="setType('movie')">Films</button>
        <button class="filter-pill" :class="{active:type==='show'}" @click="setType('show')">Séries</button>

        <div class="divider"></div>
        <span class="filter-label">Statut:</span>
        <button class="filter-pill" :class="{active:status===''}" @click="status=''">Tout</button>
        <button class="filter-pill" :class="{active:status==='library'}" @click="status='library'">Dans Plex</button>
        <button class="filter-pill" :class="{active:status==='request'}" @click="status='request'">En cours</button>

        <div class="divider"></div>
        <span class="filter-label">Audio:</span>
        <button class="filter-pill" :class="{active:vf===''}" @click="vf=''">Toutes</button>
        <button class="filter-pill" :class="{active:vf==='vf'}" @click="vf='vf'">VF</button>
        <button class="filter-pill" :class="{active:vf==='vo'}" @click="vf='vo'">VO</button>
        <button class="filter-pill" :class="{active:vf==='unchecked'}" @click="vf='unchecked'">Non analysée</button>

        <template v-if="users.length > 0">
          <div class="divider"></div>
          <span class="filter-label">Utilisateur:</span>
          <select v-model="userFilter" class="filter-select" title="Filtre pour les demandes en cours">
            <option value="">Tous</option>
            <option v-for="u in users" :key="u.id" :value="u.plex_user_id || u.custom_name || u.display_name">{{ u.custom_name || u.display_name || u.plex_user_id }}</option>
          </select>
        </template>
      </div>
    </div>

    <p v-if="error" class="notice error-text">{{ error }}</p>
    
    <section :class="view==='grid'?'media-grid':'panel media-list'">
      <div v-for="item in filtered" :key="`${item._kind}-${item.id}`" class="media-card interactive" :class="{list:view==='list'}" role="button" tabindex="0" @click="selected=item" @keydown.enter="selected=item">
        <div class="poster-shell">
          <img v-if="item.poster_url" :src="item.poster_url" alt="" @error="$event.target.style.display='none'">
          <div v-else class="poster-fallback">
            <Film/>
          </div>
          <span class="language-tag" :class="item.has_vf===true?'vf':item.has_vf===false?'vo':'unknown'">{{ item.has_vf===true?'VF':item.has_vf===false?'VO':'?' }}</span>
        </div>
        <div>
          <strong>{{ item.title }}</strong>
          <span>{{ item.media_type==='show'?'Serie':'Film'  }}<template v-if="item.year"> · {{ item.year }}</template></span>
          <span v-if="item.custom_name || item.requested_by || item.plex_user || item.plex_user_id" style="font-size: 0.85em; opacity: 0.8; margin-top: 2px;">
            👤 {{ item.custom_name || item.requested_by || item.plex_user || item.plex_user_id }}
          </span>
          <small v-if="item._kind==='request'">
            {{ requestLabel(item.status) }}<template v-if="item.overview"> — {{ item.overview }}</template>
            <button class="manage-link" @click.stop="goToRequest(item)">Gerer la demande <ArrowRight/></button>
          </small>
          <small v-else-if="item.overview">{{ item.overview }}</small>
        </div>
      </div>
    </section>
    
    <p v-if="!loading&&!filtered.length" class="empty">Aucun media.</p>

    <div v-if="hasMoreLibrary" class="load-more-row">
      <button class="secondary" :disabled="loadingMore" @click="loadMore">
        <RefreshCw v-if="loadingMore" class="spin"/>
        {{ loadingMore ? 'Chargement...' : 'Charger plus' }}
      </button>
    </div>

    <MediaDetailDrawer v-if="selected" :item="selected" :mode="selected._kind==='request'?'request':'library'" @close="selected=null" @updated="load"/>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { ArrowRight, Film, Grid2X2, List, RefreshCw } from '@lucide/vue';
import { useRouter } from 'vue-router';
import { api } from '@/api';
import MediaDetailDrawer from '@/components/MediaDetailDrawer.vue';

const router = useRouter();

function goToRequest(item) {
  router.push({ path: '/requests', query: { query: item.title } });
}

const PAGE_SIZE = 200;

const libraryItemsRaw = ref([]);
const pendingRequests = ref([]);
const rawMetrics = ref({});
const users = ref([]);
const libraryOffset = ref(0);
const hasMoreLibrary = ref(false);
const loadingMore = ref(false);

const items = computed(() => [...libraryItemsRaw.value, ...pendingRequests.value]);

const query = ref('');
const type = ref('');
const vf = ref('');
const status = ref('');
const userFilter = ref('');
const view = ref(localStorage.getItem('library.view') || 'grid');

const selected = ref(null);
const loading = ref(false);
const error = ref('');

let timer;

const filtered = computed(() => {
  return items.value.filter(item => {
    // Audio filter
    if (vf.value === 'vf' && item.has_vf !== true) return false;
    if (vf.value === 'vo' && item.has_vf !== false) return false;
    if (vf.value === 'unchecked' && item.has_vf != null) return false;
    
    // Status filter
    if (status.value === 'library' && item._kind !== 'library') return false;
    if (status.value === 'request' && item._kind !== 'request') return false;
    
    // User filter (only applies to requests)
    if (userFilter.value) {
      if (item._kind !== 'request') return false;
      if (item.plex_user_id !== userFilter.value && item.requested_by !== userFilter.value) return false;
    }
    
    return true;
  });
});

const libraryItems = computed(() => items.value.filter(x => x._kind === 'library'));

const metrics = computed(() => [
  { label: 'Dans Plex', value: rawMetrics.value.total ?? libraryItems.value.length },
  { label: 'En cours', value: items.value.length - libraryItems.value.length },
  { label: 'En VO', value: rawMetrics.value.vf?.missing ?? libraryItems.value.filter(x => x.has_vf === false).length },
  { label: 'En VF', value: rawMetrics.value.vf?.complete ?? libraryItems.value.filter(x => x.has_vf === true).length }
]);

function proxyUrl(url) {
  if (!url) return url;
  if (url.startsWith('http://') || (url.startsWith('https://') && /\/(192\.168\.|10\.|127\.)/.test(url))) {
    return `/api/image-proxy?url=${encodeURIComponent(url)}`;
  }
  return url;
}

function setType(value) {
  type.value = value;
  load();
}

function setView(value) {
  view.value = value;
  localStorage.setItem('library.view', value);
}

function scheduleLoad() {
  clearTimeout(timer);
  timer = setTimeout(load, 250);
}

function requestLabel(s) {
  return ({
    pending_approval: 'A approuver',
    pending: 'En attente',
    sent_to_arr: 'Transmise a Sonarr/Radarr',
    failed: 'Echec'
  })[s] || s;
}

function _libraryParams(offset) {
  const p = new URLSearchParams();
  if (query.value.trim()) p.set('query', query.value.trim());
  if (type.value) p.set('media_type', type.value);
  p.set('limit', PAGE_SIZE);
  p.set('offset', offset);
  return p;
}

async function load() {
  loading.value = true;
  error.value = '';
  libraryOffset.value = 0;

  try {
    const [library, requests, stats] = await Promise.all([
      api(`/api/library?${_libraryParams(0)}`),
      api(`/api/requests${query.value.trim() ? `?query=${encodeURIComponent(query.value.trim())}` : ''}`),
      api(`/api/library-metrics${type.value ? `?media_type=${type.value}` : ''}`).catch(() => ({}))
    ]);

    const pending = requests
      .filter(x => x.status !== 'available' && !x.library_item_id && (!type.value || x.media_type === type.value))
      .map(x => ({ ...x, _kind: 'request', poster_url: proxyUrl(x.poster_url) }));

    libraryItemsRaw.value = library.map(x => ({ ...x, _kind: 'library' }));
    pendingRequests.value = pending;
    libraryOffset.value = library.length;
    hasMoreLibrary.value = library.length === PAGE_SIZE;
    rawMetrics.value = stats;
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}

async function loadMore() {
  if (loadingMore.value || !hasMoreLibrary.value) return;
  loadingMore.value = true;
  try {
    const library = await api(`/api/library?${_libraryParams(libraryOffset.value)}`);
    libraryItemsRaw.value = [...libraryItemsRaw.value, ...library.map(x => ({ ...x, _kind: 'library' }))];
    libraryOffset.value += library.length;
    hasMoreLibrary.value = library.length === PAGE_SIZE;
  } catch (e) {
    error.value = e.message;
  } finally {
    loadingMore.value = false;
  }
}

async function loadUsers() {
  try {
    users.value = await api('/api/users');
  } catch (e) {
    console.warn("Failed to load users for filter", e);
  }
}

onMounted(() => {
  load();
  loadUsers();
});
</script>

<style scoped>
.manage-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 4px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--accent);
  font-size: 0.85rem;
  cursor: pointer;
}
.manage-link:hover {
  text-decoration: underline;
}
.manage-link svg {
  width: 14px;
  height: 14px;
}
.load-more-row {
  display: flex;
  justify-content: center;
  margin-top: 1rem;
}
</style>
