<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>Dashboard</h1>
        <p>Etat des services et activite recente.</p>
      </div>
      <button class="primary" :disabled="polling" @click="pollNow">
        <RefreshCw :class="{ spin: polling }" />Verifier maintenant
      </button>
    </header>

    <HealthGrid />

    <OnboardingChecklist :onboarding="onboarding" :show="showOnboarding" @dismiss="dismissOnboarding" />

    <section class="metric-grid">
      <component
        v-for="card in statCards"
        :key="card.label"
        :is="card.route ? 'RouterLink' : 'article'"
        :to="card.route"
        class="metric-card"
        :style="card.route ? 'text-decoration: none; color: inherit;' : ''"
      >
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
      </component>
    </section>

    <div class="dashboard-grid">
      <PendingRequestsPanel :pending="pending" @action="action" />
      <RecentJobsPanel :polls="polls" :next-poll="nextPoll" :countdown="countdown" />
      <RequestsBreakdownPanel :counts="counts" />
      <DownloadQueuePanel :queue="downloadQueue" :loading="loadingQueue" />
      <ActivityChartPanel :timeline="timeline" />
      <UpcomingReleasesPanel :items="upcoming" />
      <RecentlyAvailablePanel :items="recentlyAvailable" />
      <DiskSpacePanel :volumes="diskSpace" />
      <TopRequestedPanel :items="topRequested" />
      <ActiveUsersPanel :users="byUser" />
      <RecentNotificationsPanel :notifications="recentNotifs" />
      <ScanStatusPanel :vff-scan="vffScan" :plex-sync="plexSync" :vff-counts="vffCounts" @scan-vff="triggerVffScan" @sync-plex="triggerPlexSync" />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { RefreshCw } from '@lucide/vue';
import HealthGrid from '@/components/HealthGrid.vue';
import OnboardingChecklist from '@/components/dashboard/OnboardingChecklist.vue';
import PendingRequestsPanel from '@/components/dashboard/PendingRequestsPanel.vue';
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
import { api } from '@/api';
import { useRealtime } from '@/events';

const counts = ref({});
const pending = ref([]);
const polls = ref([]);
const timeline = ref({ labels: [], values: [] });
const byUser = ref([]);
const onboarding = ref({});
const nextPoll = ref({});
const polling = ref(false);
const seconds = ref(null);
const diskSpace = ref([]);
const topRequested = ref([]);
const recentlyAvailable = ref([]);
const upcoming = ref([]);
const recentNotifs = ref([]);
const downloadQueue = ref([]);
const loadingQueue = ref(false);
const vffScan = ref({ status: 'idle', items_scanned: 0, total_items: 0, finished_at: null });
const plexSync = ref({ status: 'idle', items_synced: 0, total_items: 0, finished_at: null });
const vffCounts = ref({});
let timer;
let vffTimer;

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

const statCards = computed(() => [
  { label: 'Demandes en cours', value: counts.value.sent_to_arr || '-', route: { path: '/library', query: { status: IN_PROGRESS_STATUSES } } },
  { label: 'En attente approbation', value: counts.value.pending_approval ?? pending.value.length, route: { path: '/library', query: { status: 'pending_approval' } } },
  { label: 'Chez Sonarr', value: counts.value.by_type?.show?.sent_to_arr ?? '-', route: { path: '/library', query: { status: IN_PROGRESS_STATUSES, type: 'show' } } },
  { label: 'Chez Radarr', value: counts.value.by_type?.movie?.sent_to_arr ?? '-', route: { path: '/library', query: { status: IN_PROGRESS_STATUSES, type: 'movie' } } },
]);

const countdown = computed(() => seconds.value == null ? '-' : seconds.value < 60 ? `${seconds.value}s` : `${Math.floor(seconds.value / 60)} min`);

async function loadDownloadQueue() {
  loadingQueue.value = true;
  try {
    const data = await api('/api/arr/queue').catch(() => []);
    downloadQueue.value = (Array.isArray(data) ? data : []).slice(0, 5);
  } finally {
    loadingQueue.value = false;
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

async function triggerVffScan() {
  try { await api('/api/vff/scan', { method: 'POST' }); await loadVffStatus(); } catch (e) {}
}

async function triggerPlexSync() {
  try { await api('/api/vff/sync-plex', { method: 'POST' }); await loadVffStatus(); } catch (e) {}
}

async function load() {
  const results = await Promise.allSettled([
    api('/api/stats/counts'),
    api('/api/requests/pending'),
    api('/api/poll-history?limit=6'),
    api('/api/stats/timeline'),
    api('/api/stats/by-user'),
    api('/api/onboarding'),
    api('/api/next-poll'),
    api('/api/disk-space'),
    api('/api/stats/top-requested'),
    api('/api/stats/recently-available'),
    api('/api/upcoming?limit=8'),
    api('/api/notifications/log?limit=5'),
  ]);
  const refs = [counts, pending, polls, timeline, byUser, onboarding, nextPoll, diskSpace, topRequested, recentlyAvailable, upcoming];
  results.forEach((r, i) => {
    if (r.status === 'fulfilled' && refs[i]) refs[i].value = r.value;
  });
  if (results[11].status === 'fulfilled') {
    recentNotifs.value = results[11].value?.items ?? results[11].value ?? [];
  }
  seconds.value = nextPoll.value.next_run_seconds;
  await loadDownloadQueue();
}

async function pollNow() {
  polling.value = true;
  try {
    await api('/api/requests/poll', { method: 'POST' });
    await load();
  } finally {
    polling.value = false;
  }
}

async function action(row, type) {
  if (type === 'reject') {
    const reason = prompt('Motif du refus', 'Demande refusee');
    if (reason === null) return;
    await api(`/api/requests/${row.id}/reject`, { method: 'POST', body: JSON.stringify({ reason }) });
  } else {
    await api(`/api/requests/${row.id}/approve`, { method: 'POST' });
  }
  await load();
}

useRealtime(['request.updated'], load);

onMounted(async () => {
  await load();
  await loadVffStatus();
  timer = setInterval(() => {
    if (seconds.value > 0) seconds.value--;
  }, 1000);
  vffTimer = setInterval(loadVffStatus, 5000);
});

onUnmounted(() => { clearInterval(timer); clearInterval(vffTimer); });
</script>
