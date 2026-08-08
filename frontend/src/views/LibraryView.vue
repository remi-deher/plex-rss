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

    <div class="sticky-stack">
      <MediaFiltersBar
        v-model:query="query"
        v-model:view="view"
        v-model:status-filters="statusFilters"
        v-model:type-filters="typeFilters"
        v-model:vf="vf"
        v-model:source-filters="sourceFilters"
        v-model:requester-filters="requesterFilters"
        v-model:decade="decade"
        v-model:sort="sort"
        v-model:genre="genre"
        v-model:audio-format="audioFormat"
        v-model:release-type="releaseType"
        v-model:hi-res="hiRes"
        :sources="sources"
        :requesters="requesters"
        @search="onSearch"
      />

      <div v-if="canModerate&&selectedIds.length" class="bulk-bar">
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
        :can-moderate="canModerate"
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
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { CheckCheck, Film, Layers, Music2, RefreshCw, RotateCcw, Trash2, Tv, X } from '@lucide/vue';
import { mediaDetailPath } from '@/mediaUrl';
import { proxyUrl } from '@/utils/mediaImage';
import { api } from '@/api';
import { readCache, writeCache } from '@/cache';
import { useRealtime } from '@/events';
import { useConfirm } from '@/composables/useConfirm';
import { useDebounced } from '@/composables/useDebounced';
import { useLatestRequest } from '@/composables/useLatestRequest';
import { usePolling } from '@/composables/usePolling';
import { canModerateSession, isAdminSession, loadSession } from '@/composables/useSession';
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

// Une page de 200 cartes represente ~47 ecrans de defilement sur un telephone (mesure
// a 375x812) : le chargement incremental existe, mais son grain etait pense pour un
// grand ecran. Le lot est reduit sous 640px, la sentinelle de defilement se chargeant
// d'enchainer. Fige au montage : changer la taille de lot en cours de session
// desalignerait les offsets deja demandes.
const PAGE_SIZE = window.matchMedia('(max-width: 640px)').matches ? 60 : 200;

const libraryItemsRaw = ref([]);
const pendingRequests = ref([]);
const allRequestsRaw = ref([]);
const requestSummary = ref({ total: 0, facets: { by_type: {}, sources: [], requesters: [] } });
const orphans = ref([]);
const rawMetrics = ref({});
const users = ref([]);
const libraryOffset = ref(0);
const hasMoreLibrary = ref(false);
const loadingMore = ref(false);
const selectedIds = ref([]);
const isAdmin = ref(false);
const canModerate = ref(false);
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
const decade = ref('');
const sort = ref('');
const genre = ref('');
const audioFormat = ref('');
const releaseType = ref('');
const hiRes = ref('');
const view = ref(localStorage.getItem('library.view') || 'grid');

const loading = ref(false);
const error = ref('');

const sources = computed(() => requestSummary.value.facets?.sources || []);
const requesters = computed(() => {
  if (requestSummary.value.facets?.requesters?.length) return requestSummary.value.facets.requesters;
  const seen = new Map();
  for (const row of allRequestsRaw.value) {
    const id = row.plex_user_id;
    if (!id || seen.has(id)) continue;
    seen.set(id, row.requested_by || row.plex_user || id);
  }
  return [...seen.entries()].map(([id, label]) => ({ id, label })).sort((a, b) => a.label.localeCompare(b.label));
});

// La bibliotheque n'est concernee que si le filtre de statut inclut « Dans Plex » (ou
// n'en selectionne aucun). Un LibraryItem n'a par ailleurs pas de `source` -- c'est un
// media Plex, pas une demande : des qu'un filtre par source est actif, aucun ne peut
// correspondre, autant ne pas demander la page du tout.
const wantsLibraryItems = computed(() =>
  (!statusFilters.value.length || statusFilters.value.includes('library'))
  && !sourceFilters.value.length
);

// Les medias Plex et les demandes sont desormais filtres en SQL (voir _libraryParams et
// _requestListParams) : les refiltrer ici ne changerait rien au mieux, et donnait un
// resultat faux des que la liste depassait une page -- « VF uniquement » ne filtrait que
// les 200 premiers medias charges et masquait tout le reste de la bibliotheque.
//
// Les orphelins restent filtres localement : ils viennent de Sonarr/Radarr en un seul
// bloc, sans pagination, donc le filtrage client y est exact.
function matchesOrphanFilters(item) {
  if (statusFilters.value.length && !statusFilters.value.includes('orphan')) return false;
  if (typeFilters.value.length && !typeFilters.value.includes(item.media_type)) return false;
  if (vf.value === 'vf' && item.has_vf !== true) return false;
  if (vf.value === 'vo' && item.has_vf !== false) return false;
  if (vf.value === 'unchecked' && item.has_vf != null) return false;
  if (sourceFilters.value.length && !sourceFilters.value.includes(item.source)) return false;
  if (requesterFilters.value.length && !requesterFilters.value.includes(item.plex_user_id)) return false;
  return true;
}

const filtered = computed(() => items.value.filter(item => {
  if (typeFilters.value.length && !typeFilters.value.includes(item.media_type)) return false;
  if (item.orphan) return matchesOrphanFilters(item);
  return true;
}));

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
// `vf` fait partie de la liste depuis que le filtre est applique en SQL : tant qu'il ne
// servait qu'au filtrage client, le changer suffisait a recalculer `filtered` sans
// rechargement -- ce n'est plus le cas.
watch([statusFilters, typeFilters, sourceFilters, requesterFilters, vf, decade, sort, genre, audioFormat, releaseType, hiRes], () => load(), { deep: true });

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
  if (typeFilters.value.length) p.set('media_types', typeFilters.value.join(','));
  if (vf.value) p.set('vf', vf.value);
  if (requesterFilters.value.length) p.set('requesters', requesterFilters.value.join(','));
  if (decade.value) p.set('decade', decade.value);
  if (sort.value) p.set('sort', sort.value);
  if (genre.value) p.set('genre', genre.value);
  if (audioFormat.value) p.set('audio_format', audioFormat.value);
  if (releaseType.value) p.set('release_type', releaseType.value);
  if (hiRes.value) p.set('hi_res', hiRes.value);
  p.set('limit', PAGE_SIZE);
  p.set('offset', offset);
  return p;
}

function _requestListParams() {
  const p = new URLSearchParams({ limit: '500' });
  const q = query.value.trim();
  if (q) p.set('query', q);
  // « Dans Plex » couvre les LibraryItem synces, les demandes « disponible » (Radarr/Sonarr
  // a confirme avant le prochain sync Plex quotidien) et les series « partiellement
  // disponible » : au moins un episode est deja regardable.
  const selectedStatuses = statusFilters.value.includes('library')
    ? [...new Set([...statusFilters.value.filter(value => value !== 'library'), 'available', 'partially_available'])]
    : statusFilters.value;
  if (selectedStatuses.length) p.set('statuses', selectedStatuses.join(','));
  // Une serie garde le statut « partiellement disponible » tant qu'elle n'a pas fini de
  // diffuser, meme a jour sur tout ce qui est sorti. Ce raffinement ne s'applique que si
  // l'utilisateur a explicitement choisi ce statut : sous « Dans Plex », une serie a jour
  // doit rester visible.
  if (statusFilters.value.includes('partially_available') && !statusFilters.value.includes('library')) {
    p.set('strict_partial', 'true');
  }
  if (typeFilters.value.length) p.set('media_types', typeFilters.value.join(','));
  if (sourceFilters.value.length) p.set('sources', sourceFilters.value.join(','));
  if (requesterFilters.value.length) p.set('requesters', requesterFilters.value.join(','));
  if (vf.value) p.set('vf', vf.value);
  return p;
}

// Le cache SWR est indexe sur les parametres reellement envoyes : les charges utiles
// dependent des filtres, repeindre celles d'un autre filtre serait faux.
const CACHE_MAX_AGE_MS = 6 * 60 * 60 * 1000;
function _cacheKey() {
  return `library:${_libraryParams(0)}|${_requestListParams()}`;
}

function applyRequestData(requests, stats) {
  if (!requests) return;
  requestSummary.value = requests;
  allRequestsRaw.value = requests.items || [];
  pendingRequests.value = allRequestsRaw.value
    .filter(x => !x.library_item_id || x.status === 'partially_available')
    .map(x => ({ ...x, _kind: 'request', poster_url: proxyUrl(x.poster_url) }));
  rawMetrics.value = stats || {};
  selectedIds.value = selectedIds.value.filter(id => items.value.some(x => x.id === id));
}

function applyOrphans(orphanRows) {
  const searchQuery = query.value.trim().toLowerCase();
  const matching = searchQuery
    ? orphanRows.filter(row => row.title?.toLowerCase().includes(searchQuery))
    : orphanRows;
  orphans.value = matching.map(x => ({ ...x, _kind: 'request' }));
}

function applyLibraryPage(library) {
  libraryItemsRaw.value = library.map(x => ({ ...x, _kind: 'library' }));
  libraryOffset.value = library.length;
  hasMoreLibrary.value = wantsLibraryItems.value && library.length === PAGE_SIZE;
}

/** Repeint la derniere vue connue pour ces filtres, avant le premier aller-retour reseau. */
function primeFromCache() {
  const cached = readCache(_cacheKey(), { maxAgeMs: CACHE_MAX_AGE_MS });
  if (!cached?.requests) return;
  applyLibraryPage(cached.library || []);
  applyRequestData(cached.requests, cached.stats);
  applyOrphans(cached.orphans || []);
}

async function refreshRequestData() {
  const [requests, stats] = await Promise.all([
    api(`/api/requests-list?${_requestListParams()}`),
    api(`/api/library-metrics${typeFilters.value.length === 1 ? `?media_type=${typeFilters.value[0]}` : ''}`).catch(() => ({})),
  ]);
  applyRequestData(requests, stats);
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
  let libraryPage = null;
  try {
    // Aucun media Plex ne peut correspondre aux filtres courants : on economise l'appel
    // plutot que de charger une page qui serait entierement ecartee.
    const library = wantsLibraryItems.value
      ? await api(`/api/library?${_libraryParams(0)}`, options)
      : [];
    if (!isCurrent()) return;
    libraryPage = library;
    applyLibraryPage(library);
  } catch (e) {
    if (!request.isAbort(e) && isCurrent()) error.value = e.message;
  } finally {
    if (isCurrent()) loading.value = false;
  }

  if (!isCurrent()) return;
  try {
    const [requests, orphanRows, stats] = await Promise.all([
      api(`/api/requests-list?${_requestListParams()}`, options),
      api('/api/requests/orphans', options).catch(e => request.isAbort(e) ? Promise.reject(e) : []),
      api(`/api/library-metrics${typeFilters.value.length === 1 ? `?media_type=${typeFilters.value[0]}` : ''}`, options).catch(e => request.isAbort(e) ? Promise.reject(e) : {}),
    ]);
    if (!isCurrent()) return;

    applyRequestData(requests, stats);
    applyOrphans(orphanRows);
    // Ecrit une fois les deux vagues arrivees : le cache represente ainsi une page
    // complete, jamais un etat intermediaire sans demandes ni orphelins.
    if (libraryPage) writeCache(_cacheKey(), { library: libraryPage, requests, stats, orphans: orphanRows });
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
    if (action === 'cancel' && canModerate.value) await api(`/api/requests/${row.id}`, { method: 'DELETE' });
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

useRealtime(['request.updated'], (type, event) => {
  if (!type || ['plex-sync', 'plex-sync-recent'].includes(event?.job) || event?.library_changed) {
    return load();
  }
  return refreshRequestData().catch(() => {});
});
// Filet de securite si le flux SSE se perd ; le garde de visibilite de usePolling evite
// de rafraichir un onglet en arriere-plan (ce que l'ancien setInterval nu faisait).
usePolling(load, 120000);
onMounted(async () => {
  primeFromCache();
  const session = await loadSession();
  isAdmin.value = isAdminSession(session);
  canModerate.value = canModerateSession(session);
  await load();
  loadUsers();
});
onUnmounted(() => loadMoreObserver?.disconnect());
</script>

<style scoped>
.metric-card small {
  display: block;
  color: var(--text-muted);
  font-size: var(--fs-sm);
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
  font-size: var(--fs-sm);
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
