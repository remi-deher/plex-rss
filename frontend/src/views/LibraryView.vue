<template>
  <div class="page">
    <PageHeader title="Bibliothèque" description="Catalogue Plex, demandes en cours et suivi des versions.">
        <button v-if="isAdmin" class="secondary" :disabled="busy" @click="runUtility('/api/requests/poll')">
          <RefreshCw/>Vérifier maintenant
        </button>
        <button class="icon-button" :disabled="loading" title="Actualiser" aria-label="Actualiser" @click="load">
          <RefreshCw :class="{spin:loading}"/>
        </button>
    </PageHeader>

    <MetricGrid aria-label="Résumé de la bibliothèque">
      <MetricCard v-for="entry in metrics" :key="entry.label" :label="entry.label" :value="entry.value" :detail="entry.sub"/>
    </MetricGrid>

    <div class="sticky-stack">
      <MediaFiltersBar
        v-model:query="query"
        v-model:view="view"
        v-model:status-filters="statusFilters"
        v-model:type-filters="typeFilters"
        v-model:vf="vf"
        v-model:source-filters="sourceFilters"
        v-model:requester-filters="requesterFilters"
        :sources="sources"
        :requesters="requesters"
        @search="onSearch"
      />

      <div v-if="isAdmin&&selectedIds.length" class="bulk-bar">
        <strong>{{ selectedIds.length }} selectionnee(s)</strong>
        <button class="secondary" @click="bulk('retry')"><RotateCcw/>Relancer</button>
        <button class="secondary" @click="bulk('mark-processed')"><CheckCheck/>Traiter</button>
        <button class="secondary danger" @click="bulk('delete')"><Trash2/>Supprimer</button>
        <button class="icon-button" title="Annuler" aria-label="Annuler" @click="selectedIds=[]"><X/></button>
      </div>
    </div>

    <UiFeedback v-if="error" type="error" title="Impossible de charger la bibliothèque" :message="error" retry @retry="load" />
    <UiFeedback v-if="loading&&!items.length" type="loading" message="Chargement de la bibliothèque…" />
    <p class="library-result-count" aria-live="polite">{{ filtered.length }} média{{ filtered.length>1?'s':'' }} affiché{{ filtered.length>1?'s':'' }}</p>

    <section :class="view==='grid'?'media-grid library-grid':'panel media-list'" :aria-busy="loading">
      <LibraryCard
        v-for="item in filtered"
        :key="`${item._kind}-${item.id}`"
        :item="item"
        :view="view"
        :is-admin="isAdmin"
        :busy="busy"
        :selected="selectedIds.includes(item.id)"
        @open="openDetail"
        @toggle-select="toggleSelect"
        @act="act"
        @delete-orphan="deleteOrphan"
        @error="error = $event"
      />
    </section>

    <p v-if="!loading&&!filtered.length" class="empty">Aucun media.</p>

    <div v-if="hasMoreLibrary" ref="loadMoreSentinel" class="load-more-row">
      <RefreshCw v-if="loadingMore" class="spin"/>
      <button v-else class="secondary" @click="loadMore">Charger plus de médias</button>
    </div>
    <ConfirmModal v-bind="confirmDialog" @cancel="resolveConfirm(false)" @confirm="resolveConfirm(true)" />
  </div>
</template>

<script setup>
import MetricCard from '@/components/ui/MetricCard.vue';
import MetricGrid from '@/components/ui/MetricGrid.vue';
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { CheckCheck, RefreshCw, RotateCcw, Trash2, X } from '@lucide/vue';
import { mediaDetailPath } from '@/mediaUrl';
import { proxyUrl } from '@/utils/mediaImage';
import { api } from '@/api';
import { useRealtime } from '@/events';
import { useConfirm } from '@/composables/useConfirm';
import { useDebounced } from '@/composables/useDebounced';
import { useLatestRequest } from '@/composables/useLatestRequest';
import { usePolling } from '@/composables/usePolling';
import { isAdminSession, loadSession } from '@/composables/useSession';
import MediaFiltersBar from '@/components/media/MediaFiltersBar.vue';
import LibraryCard from '@/components/library/LibraryCard.vue';
import ConfirmModal from '@/components/ConfirmModal.vue';

const route = useRoute();
const router = useRouter();
const { dialog: confirmDialog, askConfirm, resolveConfirm } = useConfirm();
const request = useLatestRequest();

const loadMoreSentinel = ref(null);
let loadMoreObserver = null;
// v-if démonte/remonte la sentinelle avec hasMoreLibrary : on la ré-observe à chaque
// apparition plutôt que de créer un seul IntersectionObserver au montage du composant.
watch(loadMoreSentinel, (el) => {
  loadMoreObserver?.disconnect();
  if (!el) return;
  loadMoreObserver = new IntersectionObserver((entries) => {
    if (entries[0]?.isIntersecting) loadMore();
  }, { rootMargin: '400px' });
  loadMoreObserver.observe(el);
});

function openDetail(item) {
  router.push(mediaDetailPath(item, item._kind));
}

const PAGE_SIZE = 200;

const libraryItemsRaw = ref([]);
const pendingRequests = ref([]);
const allRequestsRaw = ref([]);
const orphans = ref([]);
const rawMetrics = ref({});
const users = ref([]);
const libraryOffset = ref(0);
const hasMoreLibrary = ref(false);
const loadingMore = ref(false);
const selectedIds = ref([]);
const isAdmin = ref(false);
const busy = ref(false);

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
  return [...libraryItems, ...pendingRequests.value, ...orphans.value];
});

const IN_PROGRESS_STATUSES = ['pending_approval', 'pending', 'sent_to_arr', 'partially_available'];
const query = ref(route.query.query || '');
// Filtre par defaut = "Dans Plex" (pas "Tout") a l'arrivee sur la page : Bibliotheque
// doit d'abord montrer ce qui est reellement regardable, pas le melange complet avec
// les demandes en cours/orphelins. Un lien externe avec ?status=xxx (dashboard) garde
// son comportement d'origine.
const statusFilters = ref(
  route.query.status ? (Array.isArray(route.query.status) ? route.query.status : [route.query.status]) : ['library']
);
const typeFilters = ref(route.query.type ? (Array.isArray(route.query.type) ? route.query.type : [route.query.type]) : []);
const vf = ref('');
const sourceFilters = ref([]);
const requesterFilters = ref([]);
const view = ref(localStorage.getItem('library.view') || 'grid');

const loading = ref(false);
const error = ref('');

const sources = computed(() => [...new Set(allRequestsRaw.value.map(x => x.source).filter(Boolean))]);
const requesters = computed(() => {
  const seen = new Map();
  for (const row of allRequestsRaw.value) {
    const id = row.plex_user_id;
    if (!id || seen.has(id)) continue;
    seen.set(id, row.requested_by || row.plex_user || id);
  }
  return [...seen.entries()].map(([id, label]) => ({ id, label })).sort((a, b) => a.label.localeCompare(b.label));
});

// Une serie "partially_available" reste dans ce statut tant qu'elle n'a pas fini de
// diffuser (voir arr_tracker.is_show_partial cote backend), meme quand elle est deja a
// jour sur tout ce qui est reellement sorti -- sans ce filtre, "Partiellement disponible"
// affiche des series qui n'ont en realite rien de manquant cote Sonarr.
function matchesStatusFilter(item) {
  if (!statusFilters.value.length) return true;
  if (item.orphan) return statusFilters.value.includes('orphan');
  // "Dans Plex" couvre les LibraryItem synces, les demandes "disponible" (Radarr/Sonarr
  // a confirme avant le prochain sync Plex quotidien), et desormais aussi les series
  // "partiellement disponible" : au moins un episode est deja regardable, inutile
  // d'attendre que Sonarr ait tout recupere pour la considerer "dans Plex".
  const countsAsLibrary = item._kind === 'library'
    || (item._kind === 'request' && (item.status === 'available' || item.status === 'partially_available'));
  if (countsAsLibrary && statusFilters.value.includes('library')) return true;
  if (!statusFilters.value.includes(item.status)) return false;
  if (item.status !== 'partially_available') return true;
  return Boolean(item.episodes_aired_count) && item.episodes_available_count < item.episodes_aired_count;
}

const filtered = computed(() => items.value.filter(item =>
  matchesStatusFilter(item) &&
  (!typeFilters.value.length || typeFilters.value.includes(item.media_type)) &&
  (vf.value !== 'vf' || item.has_vf === true) &&
  (vf.value !== 'vo' || item.has_vf === false) &&
  (vf.value !== 'unchecked' || item.has_vf == null) &&
  (!sourceFilters.value.length || sourceFilters.value.includes(item.source)) &&
  (!requesterFilters.value.length || requesterFilters.value.includes(item.plex_user_id))
));

const libraryItems = computed(() => items.value.filter(x => x._kind === 'library'));
// Demandes "disponibles" ou "partiellement disponibles" sans LibraryItem affiche (son
// LibraryItem existe mais est exclu du calcul ci-dessus, voir le filtrage de `items` plus
// haut) : comptent comme "Dans Plex" pour les metriques aussi, pas comme "En cours"
// (voir matchesStatusFilter).
const availableUnsynced = computed(() => items.value.filter(x => x._kind === 'request' && !x.orphan && (x.status === 'available' || x.status === 'partially_available')));

// Toutes les demandes (tous statuts confondus, cote arr) -- Radarr gere les films,
// Sonarr les series, d'ou la repartition par media_type plutot qu'un champ "source"
// dedie (source designe l'origine de la demande : Overseerr, formulaire, etc.).
const requestsByArrCount = computed(() => {
  const movies = allRequestsRaw.value.filter(x => x.media_type === 'movie').length;
  const shows = allRequestsRaw.value.filter(x => x.media_type === 'show').length;
  return { movies, shows };
});

const metrics = computed(() => [
  { label: 'Demandes', value: allRequestsRaw.value.length, sub: `${requestsByArrCount.value.movies} Radarr / ${requestsByArrCount.value.shows} Sonarr` },
  { label: 'Dans Plex', value: (rawMetrics.value.total ?? libraryItems.value.length) + availableUnsynced.value.length },
  { label: 'En cours', value: items.value.length - libraryItems.value.length - availableUnsynced.value.length },
  { label: 'En VO', value: rawMetrics.value.vf?.missing ?? libraryItems.value.filter(x => x.has_vf === false).length },
  { label: 'En VF', value: rawMetrics.value.vf?.complete ?? libraryItems.value.filter(x => x.has_vf === true).length }
]);

function toggleSelect(id) {
  selectedIds.value = selectedIds.value.includes(id) ? selectedIds.value.filter(x => x !== id) : [...selectedIds.value, id];
}

watch(view, value => localStorage.setItem('library.view', value));
watch(
  () => route.query,
  value => {
    query.value = value.query || '';
    statusFilters.value = value.status ? (Array.isArray(value.status) ? value.status : [value.status]) : ['library'];
    typeFilters.value = value.type ? (Array.isArray(value.type) ? value.type : [value.type]) : [];
    load();
  },
  { deep: true },
);

// La frappe au clavier abandonne la requete en cours avant d'armer le delai : inutile de
// laisser courir une recherche que l'utilisateur est deja en train de reformuler.
const scheduleLoad = useDebounced(load, 250);
function onSearch() {
  request.abort();
  scheduleLoad();
}

function _libraryParams(offset) {
  const p = new URLSearchParams();
  if (query.value.trim()) p.set('query', query.value.trim());
  if (typeFilters.value.length === 1) p.set('media_type', typeFilters.value[0]);
  p.set('limit', PAGE_SIZE);
  p.set('offset', offset);
  return p;
}

async function load() {
  const { signal, isCurrent } = request.begin();
  const options = { signal };
  error.value = '';
  libraryOffset.value = 0;
  loading.value = true;

  // Chargement priorise (facon Seerr) : la bibliotheque (lecture DB pure, rapide)
  // s'affiche des qu'elle arrive, sans attendre demandes/orphelins/metriques -- ces
  // derniers completent la vue ensuite au fil de l'eau. Les orphelins en particulier
  // interrogent Sonarr/Radarr en direct (cache court cote backend, voir
  // arr_orphans.py) : avant, tout restait bloque derriere ce seul appel via
  // Promise.all, donnant l'impression d'un rechargement complet a chaque visite.
  try {
    const library = await api(`/api/library?${_libraryParams(0)}`, options);
    if (!isCurrent()) return;
    libraryItemsRaw.value = library.map(x => ({ ...x, _kind: 'library' }));
    libraryOffset.value = library.length;
    hasMoreLibrary.value = library.length === PAGE_SIZE;
  } catch (e) {
    if (!request.isAbort(e) && isCurrent()) error.value = e.message;
  } finally {
    if (isCurrent()) loading.value = false;
  }

  if (!isCurrent()) return;
  try {
    const q = query.value.trim();
    const [requests, orphanRows, stats] = await Promise.all([
      api(`/api/requests${q ? `?query=${encodeURIComponent(q)}` : ''}`, options),
      api('/api/requests/orphans', options).catch(e => request.isAbort(e) ? Promise.reject(e) : []),
      api(`/api/library-metrics${typeFilters.value.length === 1 ? `?media_type=${typeFilters.value[0]}` : ''}`, options).catch(e => request.isAbort(e) ? Promise.reject(e) : {}),
    ]);
    if (!isCurrent()) return;

    allRequestsRaw.value = requests;
    const pending = requests
      // Toute demande sans LibraryItem doit rester visible, MEME "disponible" : Radarr/
      // Sonarr peut confirmer le telechargement (et declencher la notification) bien
      // avant le prochain sync Plex (une fois par jour) qui cree reellement le
      // LibraryItem -- sans ce filtre elargi, un media "disponible" mais pas encore
      // synchronise disparaissait de la Bibliotheque jusqu'au sync suivant (jusqu'a 24h).
      // Une demande partiellement disponible reste "en cours" meme une fois liee a un
      // LibraryItem (library_item_id pose des qu'un episode est indexe), pour ne pas
      // disparaitre avant d'etre reellement complete.
      .filter(x => !x.library_item_id || x.status === 'partially_available')
      .map(x => ({ ...x, _kind: 'request', poster_url: proxyUrl(x.poster_url) }));

    const matchingOrphans = q ? orphanRows.filter(o => o.title?.toLowerCase().includes(q.toLowerCase())) : orphanRows;

    pendingRequests.value = pending;
    orphans.value = matchingOrphans.map(x => ({ ...x, _kind: 'request' }));
    rawMetrics.value = stats;
    selectedIds.value = selectedIds.value.filter(id => items.value.some(x => x.id === id));
  } catch (e) {
    if (!request.isAbort(e) && isCurrent()) error.value = e.message;
  }
}

async function loadMore() {
  if (loading.value || loadingMore.value || !hasMoreLibrary.value) return;
  loadingMore.value = true;
  try {
    const library = await api(`/api/library?${_libraryParams(libraryOffset.value)}`);
    const known = new Set(libraryItemsRaw.value.map(x => x.id));
    libraryItemsRaw.value = [...libraryItemsRaw.value, ...library.filter(x => !known.has(x.id)).map(x => ({ ...x, _kind: 'library' }))];
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

async function deleteOrphan(row) {
  const source = row.orphan_source === 'sonarr' ? 'Sonarr' : 'Radarr';
  if (!await askConfirm({
    title: `Supprimer directement de ${source} ?`,
    message: `"${row.title}" ne sera plus suivi(e) par ${source}. Cette action est irreversible.`,
    confirmLabel: 'Supprimer',
    danger: true,
  })) return;
  // Les fichiers deja telecharges (le cas echeant) restent sur le disque -- et donc
  // visibles dans Plex jusqu'a son prochain scan -- sauf choix explicite ici.
  const deleteFiles = confirm(
    `Supprimer aussi les fichiers deja telecharges pour "${row.title}" ?\n\n` +
    `Sans cela, ${source} arrete le suivi mais laisse les fichiers en place (toujours visibles dans Plex).`
  );
  busy.value = true;
  try {
    await api(`/api/requests/orphans/${row.orphan_source}/${row.arr_instance_id}/${row.arr_id}?delete_files=${deleteFiles}`, { method: 'DELETE' });
    await load();
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
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

async function bulk(action) {
  if (action === 'delete' && !await askConfirm({ title: 'Supprimer les demandes sélectionnées ?', message: `${selectedIds.value.length} demande(s) seront supprimée(s) définitivement.`, confirmLabel: 'Supprimer', danger: true })) return;
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

useRealtime(['request.updated'], load);
// Filet de securite si le flux SSE se perd ; le garde de visibilite de usePolling evite
// de rafraichir un onglet en arriere-plan (ce que l'ancien setInterval nu faisait).
usePolling(load, 120000);
onMounted(async () => {
  isAdmin.value = isAdminSession(await loadSession());
  await load();
  loadUsers();
});
onUnmounted(() => loadMoreObserver?.disconnect());
</script>

<style scoped>
.metric-card small {
  display: block;
  color: var(--text-muted);
  font-size: 0.75rem;
}

.load-more-row {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 40px;
  margin-top: 1rem;
}

.library-result-count {
  margin: 0;
  color: var(--muted);
  font-size: .75rem;
  text-align: right;
}

/* Plafonne a 4 colonnes sur cette page (le reste du responsive -- 4/3/2 colonnes en
   dessous de 1200px -- vient deja de .media-grid, partage avec Decouvrir) : sans ce
   plafond .media-grid passe a 5 colonnes au-dela de 1200px. */
@media (min-width: 1201px) {
  .library-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}
</style>
