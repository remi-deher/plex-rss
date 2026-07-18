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

    <LibraryFiltersBar
      v-model:query="query"
      v-model:type="type"
      v-model:vf="vf"
      v-model:status="status"
      v-model:user-filter="userFilter"
      v-model:view="view"
      :users="users"
      @search="scheduleLoad"
      @update:type="load"
    />

    <p v-if="error" class="notice error-text">{{ error }}</p>

    <section :class="view==='grid'?'media-grid library-grid':'panel media-list'">
      <LibraryCard
        v-for="item in filtered"
        :key="`${item._kind}-${item.id}`"
        :item="item"
        :view="view"
        @open="openDetail"
        @go-to-request="goToRequest"
      />
    </section>

    <p v-if="!loading&&!filtered.length" class="empty">Aucun media.</p>

    <div v-if="hasMoreLibrary" class="load-more-row">
      <button class="secondary" :disabled="loadingMore" @click="loadMore">
        <RefreshCw v-if="loadingMore" class="spin"/>
        {{ loadingMore ? 'Chargement...' : 'Charger plus' }}
      </button>
    </div>

  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { RefreshCw } from '@lucide/vue';
import { mediaDetailPath } from '@/mediaUrl';
import { api } from '@/api';
import LibraryFiltersBar from '@/components/library/LibraryFiltersBar.vue';
import LibraryCard from '@/components/library/LibraryCard.vue';

const router = useRouter();

function goToRequest(item) {
  router.push({ path: '/requests', query: { query: item.title } });
}

function openDetail(item) {
  router.push(mediaDetailPath(item, item._kind));
}

const PAGE_SIZE = 200;

const libraryItemsRaw = ref([]);
const pendingRequests = ref([]);
const rawMetrics = ref({});
const users = ref([]);
const libraryOffset = ref(0);
const hasMoreLibrary = ref(false);
const loadingMore = ref(false);

// Une demande partiellement disponible garde son library_item_id une fois indexee cote
// Plex : on exclut le LibraryItem correspondant pour ne pas l'afficher deux fois (une
// carte "en cours" avec son statut de progression suffit tant que ce n'est pas complet).
const items = computed(() => {
  const partialLibraryIds = new Set(
    pendingRequests.value.filter(x => x.status === 'partially_available' && x.library_item_id).map(x => x.library_item_id)
  );
  const libraryItems = partialLibraryIds.size
    ? libraryItemsRaw.value.filter(x => !partialLibraryIds.has(x.id))
    : libraryItemsRaw.value;
  return [...libraryItems, ...pendingRequests.value];
});

const query = ref('');
const type = ref('');
const vf = ref('');
const status = ref('');
const userFilter = ref('');
const view = ref(localStorage.getItem('library.view') || 'grid');

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
    if (status.value === 'partial' && item.status !== 'partially_available') return false;

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

watch(view, value => localStorage.setItem('library.view', value));

function scheduleLoad() {
  clearTimeout(timer);
  timer = setTimeout(load, 250);
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
      // Une demande partiellement disponible reste affichee comme "en cours" meme une
      // fois synchronisee cote Plex (library_item_id pose des qu'un episode est indexe) :
      // sinon elle disparaissait silencieusement de la vue une fois le premier episode
      // present, avant d'etre reellement complete.
      .filter(x => (x.status !== 'available' && !x.library_item_id) || x.status === 'partially_available')
      .filter(x => !type.value || x.media_type === type.value)
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
.load-more-row {
  display: flex;
  justify-content: center;
  margin-top: 1rem;
}

/* Plafonne a 4 colonnes sur cette page (le reste du responsive -- 4/3/2 colonnes en
   dessous de 1200px -- vient deja de .media-grid, partage avec Demandes/Decouvrir) :
   sans ce plafond .media-grid passe a 5 colonnes au-dela de 1200px. */
@media (min-width: 1201px) {
  .library-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}
</style>
