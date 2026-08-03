<template>
  <div class="page">
    <PageHeader title="Tableau de bord" :description="lastUpdatedLabel">
      <button class="primary" :disabled="polling" @click="pollNow">
        <RefreshCw :class="{ spin: polling }" />Vérifier maintenant
      </button>
    </PageHeader>

    <UiFeedback v-if="error" type="error" title="Actualisation partielle" :message="error" retry @retry="load" />
    <UiFeedback v-if="loading&&!updatedAt" type="loading" message="Chargement du tableau de bord…" />

    <OnboardingChecklist :onboarding="onboarding" :show="showOnboarding" @dismiss="dismissOnboarding" />

    <DashboardActionCenter :pending="pending" :queue="downloadQueue" :failed-count="failedCount" @action="action"/>

    <section class="dashboard-section">
      <header class="dashboard-section-head"><div><span>Activité</span><h2>Situation actuelle</h2><p>Les éléments utiles pour piloter les demandes et les acquisitions.</p></div></header>
      <MetricGrid grid-class="dashboard-metrics">
        <MetricCard
          v-for="card in statCards"
          :key="card.label"
          :label="card.label"
          :value="card.value"
          :detail="card.detail"
          :icon="card.icon"
          :to="card.route"
        />
      </MetricGrid>
      <div class="dashboard-focus-grid">
        <LiveSessionsPanel :sessions="liveActivity.active||[]" :collection-enabled="liveActivity.enabled!==false" interactive @select="selectedSession=$event" />
        <DownloadQueuePanel :queue="downloadQueue" :loading="loadingQueue" />
        <RecentJobsPanel :polls="polls" :next-poll="nextPoll" :countdown="countdown" />
        <ScanStatusPanel :vff-scan="vffScan" :plex-sync="plexSync" :vff-counts="vffCounts" @scan-vff="triggerVffScan" @sync-plex="triggerPlexSync" />
      </div>
    </section>

    <section class="dashboard-section">
      <header class="dashboard-section-head"><div><span>Tendance</span><h2>Activité</h2><p>Demandes, disponibilités et notifications sur la période.</p></div></header>
      <ActivityChartPanel :timeline="timeline" />
    </section>

    <section class="dashboard-section">
      <header class="dashboard-section-head">
        <div><span>Bibliothèque</span><h2>Nouveautés et sorties</h2><p>Ce qui vient d'arriver et ce qui est attendu prochainement.</p></div>
        <nav class="dashboard-view-tabs" aria-label="Vue des nouveautés">
          <button :class="{active:mediaView==='recent'}" :aria-pressed="mediaView==='recent'" @click="mediaView='recent'">Disponibles <span>{{ recentlyAvailable.length }}</span></button>
          <button :class="{active:mediaView==='upcoming'}" :aria-pressed="mediaView==='upcoming'" @click="mediaView='upcoming'">À venir <span>{{ upcoming.length }}</span></button>
        </nav>
      </header>
      <RecentlyAvailablePanel v-if="mediaView==='recent'" :items="recentlyAvailable" />
      <UpcomingReleasesPanel v-else :items="upcoming" />
    </section>

    <details class="dashboard-secondary" :open="supervisionOpen" @toggle="onSupervisionToggle">
      <summary><div><span>Supervision</span><strong>Vue d’ensemble</strong></div><ChevronDown/></summary>
      <div v-if="supervisionLoaded" class="dashboard-secondary-content dashboard-supervision-groups">
        <section><header><span>Santé</span><h3>Infrastructure</h3></header><div class="dashboard-grid"><HealthGrid/><DiskSpacePanel :volumes="diskSpace"/></div></section>
        <section><header><span>Usage</span><h3>Bibliothèque et utilisateurs</h3></header><div class="dashboard-grid"><RequestsBreakdownPanel :counts="counts"/><TopRequestedPanel :items="topRequested"/><ActiveUsersPanel :users="byUser"/></div></section>
        <section><header><span>Communication</span><h3>Derniers envois</h3></header><div class="dashboard-grid"><RecentNotificationsPanel :notifications="recentNotifs"/></div></section>
      </div>
    </details>
    <SessionDetailDrawer v-if="selectedSession" :session="selectedSession" @close="selectedSession=null"/>
  </div>
</template>

<script setup>
import MetricCard from '@/components/ui/MetricCard.vue';
import MetricGrid from '@/components/ui/MetricGrid.vue';
import { computed, onMounted, ref } from 'vue';
import { usePolling } from '@/composables/usePolling';
import { AlertTriangle, CheckCircle2, ChevronDown, Clock3, Download, RefreshCw } from '@lucide/vue';
import HealthGrid from '@/components/HealthGrid.vue';
import OnboardingChecklist from '@/components/dashboard/OnboardingChecklist.vue';
import DashboardActionCenter from '@/components/dashboard/DashboardActionCenter.vue';
import RecentJobsPanel from '@/components/dashboard/RecentJobsPanel.vue';
import RequestsBreakdownPanel from '@/components/dashboard/RequestsBreakdownPanel.vue';
import DownloadQueuePanel from '@/components/dashboard/DownloadQueuePanel.vue';
import ActivityChartPanel from '@/components/dashboard/ActivityChartPanel.vue';
import UpcomingReleasesPanel from '@/components/dashboard/UpcomingReleasesPanel.vue';
import RecentlyAvailablePanel from '@/components/dashboard/RecentlyAvailablePanel.vue';
import DiskSpacePanel from '@/components/dashboard/DiskSpacePanel.vue';
import TopRequestedPanel from '@/components/dashboard/TopRequestedPanel.vue';
import ActiveUsersPanel from '@/components/dashboard/ActiveUsersPanel.vue';
import RecentNotificationsPanel from '@/components/dashboard/RecentNotificationsPanel.vue';
import ScanStatusPanel from '@/components/dashboard/ScanStatusPanel.vue';
import LiveSessionsPanel from '@/components/activity/LiveSessionsPanel.vue';
import SessionDetailDrawer from '@/components/activity/SessionDetailDrawer.vue';
import { api, streamEvents } from '@/api';
import { readCacheEntry, writeCache } from '@/cache';
import { useRealtime } from '@/events';
import { queueCounts } from '@/downloads/queueRules';

const SNAPSHOT_CACHE_KEY = 'dashboard:snapshot';
const SUPERVISION_OPEN_KEY = 'dashboard.supervisionOpen';
const PRIMARY_SECTIONS = [
  'pending', 'polls', 'timeline', 'onboarding', 'recently_available',
  'upcoming', 'next_poll',
];
const SUPERVISION_SECTIONS = ['counts', 'top_requested', 'by_user', 'notifications'];
// Au-dela, mieux vaut l'ecran de chargement qu'un etat qui n'a plus rien a voir.
const SNAPSHOT_CACHE_MAX_AGE_MS = 6 * 60 * 60 * 1000;

const counts = ref({});
const pending = ref([]);
const polls = ref([]);
const timeline = ref({ labels: [], values: [] });
const byUser = ref([]);
const onboarding = ref({});
const nextPoll = ref({});
const polling = ref(false);
const loading = ref(false);
const error = ref('');
const seconds = ref(null);
const diskSpace = ref([]);
const topRequested = ref([]);
const recentlyAvailable = ref([]);
const upcoming = ref([]);
const recentNotifs = ref([]);
const downloadQueue = ref([]);
const liveActivity = ref({ active: [] });
const selectedSession = ref(null);
const loadingQueue = ref(false);
const mediaView = ref('recent');
const updatedAt = ref(null);
const clock = ref(Date.now());
const vffScan = ref({ status: 'idle', items_scanned: 0, total_items: 0, finished_at: null });
const plexSync = ref({ status: 'idle', items_synced: 0, total_items: 0, finished_at: null });
const vffCounts = ref({});
const supervisionOpen = ref(localStorage.getItem(SUPERVISION_OPEN_KEY) === 'true');
const supervisionLoaded = ref(false);
const supervisionLoading = ref(false);

const showOnboarding = ref(localStorage.getItem('hide_onboarding') !== 'true');
function dismissOnboarding() {
  localStorage.setItem('hide_onboarding', 'true');
  showOnboarding.value = false;
}

// "En cours" = sent_to_arr + partially_available (affine cote page Bibliotheque pour
// exclure les series a jour sur tout ce qui est deja diffuse -- voir matchesStatusFilter
// dans LibraryView.vue). Ne passer que "sent_to_arr" ici excluait a tort les series
// comme Face Off/New York police judiciaire (statut partially_available, vrai manque).
const IN_PROGRESS_STATUSES = ['sent_to_arr', 'partially_available'];
const failedCount = computed(() => Number(counts.value.failed || 0));
// Memes regles que la page Telechargements (@/downloads/queueRules) : les trois tuiles
// ci-dessous partitionnent la file sans double compte, et chaque chiffre correspond au
// groupe qu'on trouve en cliquant.
const queueTotals = computed(() => queueCounts(downloadQueue.value));

const statCards = computed(() => [
  { label: 'À approuver', value: counts.value.pending_approval ?? pending.value.length, detail: 'Demandes en attente', icon: Clock3, route: { path: '/library', query: { status: 'pending_approval' } } },
  { label: 'En téléchargement', value: queueTotals.value.downloading, detail: 'Acquisitions actives', icon: Download, route: { path: '/downloads', query: { status: 'downloading' } } },
  { label: 'En attente d’import', value: queueTotals.value.importPending, detail: 'Traitement par *arr', icon: RefreshCw, route: { path: '/downloads', query: { status: 'unmatched' } } },
  { label: 'Bloqués', value: queueTotals.value.blocked + failedCount.value, detail: 'Intervention nécessaire', icon: AlertTriangle, route: { path: '/downloads', query: { status: 'error' } } },
  { label: 'Disponibles', value: counts.value.available ?? '-', detail: 'Dans la bibliothèque', icon: CheckCircle2, route: { path: '/library', query: { status: 'library' } } },
]);

const lastUpdatedLabel = computed(() => {
  if (!updatedAt.value) return 'Chargement de l’état des services et de l’activité récente…';
  const elapsed = Math.max(0, Math.floor((clock.value - updatedAt.value) / 1000));
  const age = elapsed < 5 ? 'à l’instant' : elapsed < 60 ? `il y a ${elapsed} s` : `il y a ${Math.floor(elapsed / 60)} min`;
  return `Mis à jour ${age} · actualisation automatique`;
});

const countdown = computed(() => seconds.value == null ? '-' : seconds.value < 60 ? `${seconds.value}s` : `${Math.floor(seconds.value / 60)} min`);

async function loadDownloadQueue() {
  loadingQueue.value = true;
  try {
    const data = await api('/api/arr/queue');
    downloadQueue.value = Array.isArray(data) ? data : [];
  } finally {
    loadingQueue.value = false;
  }
}

async function loadLiveActivity() {
  const value = await api('/api/playback/live');
  liveActivity.value = value;
  if (selectedSession.value) {
    const fresh = (value.active || []).find(item => item.session_id === selectedSession.value.session_id);
    selectedSession.value = fresh || null;
  }
}

async function loadVffStatus() {
  const [scanData, syncData, countsData] = await Promise.all([
    api('/api/vff/scan-status').catch(() => null),
    api('/api/vff/sync-status').catch(() => null),
    api('/api/vff/counts').catch(() => null),
  ]);
  if (scanData) vffScan.value = scanData;
  if (syncData) plexSync.value = syncData;
  if (countsData) vffCounts.value = countsData;
}

/**
 * Progression poussee par le backend (voir app/services/vff_progress.py). Le payload
 * porte l'etat complet : aucun aller-retour supplementaire n'est necessaire. Les
 * compteurs ne sont joints qu'en fin de scan, les conserver sinon.
 */
function applyVffEvent(detail) {
  const payload = detail?.payload;
  if (!payload) return;
  if (payload.scan) vffScan.value = payload.scan;
  if (payload.sync) plexSync.value = payload.sync;
  if (payload.counts) vffCounts.value = payload.counts;
}

async function triggerVffScan() {
  try { await api('/api/vff/scan', { method: 'POST' }); await loadVffStatus(); } catch (e) { error.value = e.message; }
}

async function triggerPlexSync() {
  try { await api('/api/vff/sync-plex', { method: 'POST' }); await loadVffStatus(); } catch (e) { error.value = e.message; }
}

function applyDashboardSnapshot(snapshot, { savedAt = Date.now() } = {}) {
  const assignments = [
    ['counts', counts], ['pending', pending], ['polls', polls],
    ['timeline', timeline], ['by_user', byUser], ['onboarding', onboarding],
    ['next_poll', nextPoll], ['top_requested', topRequested],
    ['recently_available', recentlyAvailable], ['upcoming', upcoming],
  ];
  assignments.forEach(([key, target]) => {
    if (snapshot[key] !== undefined) target.value = snapshot[key];
  });
  if (snapshot.notifications !== undefined) {
    recentNotifs.value = snapshot.notifications?.items ?? snapshot.notifications ?? [];
  }
  // Uniquement quand la section est presente : le flux envoie les sections une par une, et
  // reappliquer l'ancienne valeur a chaque trame ferait sauter le compte a rebours en
  // arriere, annulant les decrements de la seconde ecoulee.
  if (snapshot.next_poll !== undefined) {
    seconds.value = nextPoll.value?.next_run_seconds ?? null;
  }
  updatedAt.value = savedAt;
}

/**
 * Repeint immediatement le dernier snapshot connu, avant meme le premier aller-retour
 * reseau. `next_poll` est volontairement ecarte : le compte a rebours « prochaine
 * verification dans X » serait faux (il a continue de tourner cote serveur pendant que la
 * page n'etait pas montee) et repartirait a l'envers a l'arrivee de la vraie valeur.
 */
function primeFromCache() {
  const entry = readCacheEntry(SNAPSHOT_CACHE_KEY, { maxAgeMs: SNAPSHOT_CACHE_MAX_AGE_MS });
  if (!entry) return;
  applyDashboardSnapshot({ ...entry.data, next_poll: undefined }, { savedAt: entry.savedAt });
}

/**
 * Fusionne avec l'existant plutot que d'ecraser : `loadDashboardSections` ne renvoie que
 * les sections demandees, et un rafraichissement cible ne doit pas amputer le snapshot
 * mis en cache pour le prochain montage de la page.
 */
function cacheSnapshot(snapshot) {
  const previous = readCacheEntry(SNAPSHOT_CACHE_KEY, { maxAgeMs: SNAPSHOT_CACHE_MAX_AGE_MS })?.data;
  const { errors, ...sections } = snapshot;
  writeCache(SNAPSHOT_CACHE_KEY, { ...(previous || {}), ...sections });
}

async function loadDashboardSections(sections) {
  const snapshot = await api(`/api/dashboard/snapshot?sections=${sections.join(',')}`);
  applyDashboardSnapshot(snapshot);
  cacheSnapshot(snapshot);
}

async function loadSupervision() {
  if (supervisionLoading.value) return;
  supervisionLoaded.value = true;
  supervisionLoading.value = true;
  try {
    await Promise.all([
      loadDashboardSections(SUPERVISION_SECTIONS),
      api('/api/disk-space').then(value => { diskSpace.value = value; }),
    ]);
  } catch (e) {
    error.value = e.message;
  } finally {
    supervisionLoading.value = false;
  }
}

function onSupervisionToggle(event) {
  const open = event.currentTarget.open;
  supervisionOpen.value = open;
  localStorage.setItem(SUPERVISION_OPEN_KEY, String(open));
  if (open && !supervisionLoaded.value) loadSupervision();
}

async function load() {
  if (loading.value) return;
  loading.value = true;
  error.value = '';
  const failures = [];
  const sections = supervisionLoaded.value
    ? [...PRIMARY_SECTIONS, ...SUPERVISION_SECTIONS]
    : PRIMARY_SECTIONS;
  // Chaque section s'affiche des qu'elle arrive, sans attendre la plus lente des dix.
  function applyChunk(chunk) {
    if (chunk.errors?.length) {
      failures.push(...chunk.errors);
      return;
    }
    applyDashboardSnapshot(chunk);
    cacheSnapshot(chunk);
  }

  try {
    await streamEvents(
      `/api/dashboard/snapshot/stream?sections=${sections.join(',')}`,
      applyChunk,
    );
  } catch (streamError) {
    // Repli d'un bloc : proxy qui tamponne, navigateur sans ReadableStream, coupure
    // reseau en cours de flux. Les sections deja recues restent affichees.
    try {
      const snapshot = await api(`/api/dashboard/snapshot?sections=${sections.join(',')}`);
      applyDashboardSnapshot(snapshot);
      cacheSnapshot(snapshot);
      if (snapshot.errors?.length) failures.push(...snapshot.errors);
    } catch (e) {
      failures.push('snapshot du tableau de bord');
    }
  }
  // Les donnees externes completent la vue au fil de l'eau et ne retardent jamais le
  // premier affichage du snapshot local.
  loadDownloadQueue().catch(() => {});
  loadLiveActivity().catch(() => {});
  updatedAt.value = Date.now();
  error.value = failures.length ? `Données indisponibles : ${failures.join(', ')}.` : '';
  loading.value = false;
}

async function pollNow() {
  polling.value = true;
  try {
    await api('/api/requests/poll', { method: 'POST' });
    await load();
  } catch (e) {
    error.value = e.message;
  } finally {
    polling.value = false;
  }
}

async function action(row, type) {
  try {
    if (type === 'reject') {
      const reason = prompt('Motif du refus', 'Demande refusée');
      if (reason === null) return;
      await api(`/api/requests/${row.id}/reject`, { method: 'POST', body: JSON.stringify({ reason }) });
    } else {
      await api(`/api/requests/${row.id}/approve`, { method: 'POST' });
    }
    await load();
  } catch (e) { error.value = e.message; }
}

useRealtime(['request.updated'], (type) => {
  if (!type) return load();
  return loadDashboardSections([
    'pending', 'timeline', 'recently_available', 'upcoming', 'next_poll',
    ...(supervisionLoaded.value ? ['counts', 'by_user', 'top_requested'] : []),
  ]).catch(() => {});
});
useRealtime(['download.updated'], (type) => type ? loadDownloadQueue().catch(() => {}) : load());
useRealtime(['notification.updated'], (type) => type
  ? supervisionLoaded.value && loadDashboardSections(['notifications']).catch(() => {})
  : load());
useRealtime(['activity.updated'], () => loadLiveActivity().catch(() => {}));
// Remplace un sondage a 5 s (3 appels HTTP, soit 36 requetes/minute en permanence, meme
// au repos). `type` absent = retour sur l'onglet apres une possible perte du flux SSE :
// on resynchronise alors par un appel unique.
useRealtime(['vff.updated'], (type, detail) => {
  if (!type) return loadVffStatus().catch(() => {});
  applyVffEvent(detail);
});

// Compte a rebours et horloge : locaux, ils doivent avancer meme onglet masque pour que
// « prochaine verification dans X » soit juste au retour sur l'onglet.
usePolling(() => {
  if (seconds.value > 0) seconds.value--;
  clock.value = Date.now();
}, 1000, { whenVisible: false });
usePolling(load, 60000);

onMounted(async () => {
  primeFromCache();
  await load();
  await loadVffStatus();
  if (supervisionOpen.value) await loadSupervision();
});
</script>
