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

    <div class="sticky-stack">
      <RequestFiltersBar
        v-model:query="query"
        v-model:view="view"
        v-model:status-filters="statusFilters"
        v-model:type-filters="typeFilters"
        v-model:source-filters="sourceFilters"
        v-model:requester-filters="requesterFilters"
        :sources="sources"
        :requesters="requesters"
        @search="scheduleLoad"
      />

      <div v-if="isAdmin&&selectedIds.length" class="bulk-bar">
        <strong>{{ selectedIds.length }} selectionnee(s)</strong>
        <button class="secondary" @click="bulk('retry')"><RotateCcw/>Relancer</button>
        <button class="secondary" @click="bulk('mark-processed')"><CheckCheck/>Traiter</button>
        <button class="secondary danger" @click="bulk('delete')"><Trash2/>Supprimer</button>
        <button class="icon-button" title="Annuler" @click="selectedIds=[]"><X/></button>
      </div>
    </div>

    <p v-if="error" class="notice error-text">{{ error }}</p>

    <section :class="view==='grid'?'media-grid':'media-list'">
      <RequestCard
        v-for="row in filtered"
        :key="row.id"
        :row="row"
        :view="view"
        :is-admin="isAdmin"
        :selected="selectedIds.includes(row.id)"
        @toggle-select="toggleSelect(row.id)"
        @act="act"
        @reject="reject"
        @delete-orphan="deleteOrphan"
      />
    </section>
    <p v-if="!loading&&!filtered.length" class="empty">Aucune demande.</p>
    <ConfirmModal v-bind="confirmDialog" @cancel="resolveConfirm(false)" @confirm="resolveConfirm(true)" />
  </div>
</template>
<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { CheckCheck, RefreshCw, RotateCcw, Trash2, X } from '@lucide/vue';
import { useRoute } from 'vue-router';
import { api } from '@/api';
import { useRealtime } from '@/events';
import RequestFiltersBar from '@/components/requests/RequestFiltersBar.vue';
import RequestCard from '@/components/requests/RequestCard.vue';
import ConfirmModal from '@/components/ConfirmModal.vue';
import { useConfirm } from '@/composables/useConfirm';

const route = useRoute();
const { dialog: confirmDialog, askConfirm, resolveConfirm } = useConfirm();

const IN_PROGRESS_STATUSES = ['pending_approval', 'pending', 'sent_to_arr', 'partially_available'];

const rows = ref([]);
const query = ref(route.query.query || '');
// Par defaut, seules les demandes non traitees sont affichees (le gros des demandes
// deja disponibles/refusees/en echec noierait sinon celles qui ont besoin d'attention) --
// un lien externe avec ?status=xxx (ex: dashboard) garde son comportement d'origine.
const statusFilters = ref(route.query.status ? [route.query.status] : [...IN_PROGRESS_STATUSES]);
const typeFilters = ref(route.query.type ? [route.query.type] : []);
const sourceFilters = ref([]);
const requesterFilters = ref([]);
const selectedIds = ref([]);
const loading = ref(false);
const busy = ref(false);
const error = ref('');
const isAdmin = ref(false);
const view = ref(localStorage.getItem('requests.view') || 'grid');

let timer, fallback;

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
// Une serie "partially_available" reste dans ce statut tant qu'elle n'a pas fini de
// diffuser (voir arr_tracker.is_show_partial cote backend), meme quand elle est deja a
// jour sur tout ce qui est reellement sorti (ex: South Park, Yuru Camp) -- sans ce
// filtre, la liste "En cours" affiche des series qui n'ont en realite rien de manquant
// cote Sonarr. Meme logique que _is_show_genuinely_incomplete (app/routers/metrics_api.py).
function matchesStatusFilter(row) {
  if (!statusFilters.value.length) return true;
  if (!statusFilters.value.includes(row.status)) return false;
  if (row.status !== 'partially_available') return true;
  return Boolean(row.episodes_aired_count) && row.episodes_available_count < row.episodes_aired_count;
}

const filtered = computed(() => rows.value.filter(row =>
  matchesStatusFilter(row) &&
  (!typeFilters.value.length || typeFilters.value.includes(row.media_type)) &&
  (!sourceFilters.value.length || sourceFilters.value.includes(row.source)) &&
  (!requesterFilters.value.length || requesterFilters.value.includes(row.plex_user_id))
));

function toggleSelect(id) {
  selectedIds.value = selectedIds.value.includes(id) ? selectedIds.value.filter(x => x !== id) : [...selectedIds.value, id];
}

watch(view, value => localStorage.setItem('requests.view', value));

function scheduleLoad() {
  clearTimeout(timer);
  timer = setTimeout(load, 250);
}

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const q = query.value.trim();
    const [requests, orphans] = await Promise.all([
      api(`/api/requests${q ? `?query=${encodeURIComponent(q)}` : ''}`),
      api('/api/requests/orphans').catch(() => []),
    ]);
    const matchingOrphans = q ? orphans.filter(o => o.title?.toLowerCase().includes(q.toLowerCase())) : orphans;
    rows.value = [...requests, ...matchingOrphans];
    selectedIds.value = selectedIds.value.filter(id => rows.value.some(x => x.id === id));
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
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
onMounted(async () => {
  const session = await api('/api/session').catch(() => null);
  isAdmin.value = Boolean(session?.is_owner || session?.role === 'admin');
  await load();
  fallback = setInterval(load, 120000);
});
onUnmounted(() => {
  clearTimeout(timer);
  clearInterval(fallback);
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
