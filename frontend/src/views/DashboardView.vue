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

    <!-- Configuration Initiale Checklist -->
    <section v-if="onboarding.steps?.length && !onboarding.complete && showOnboarding" class="panel">
      <div class="panel-head">
        <div>
          <h2>Configuration initiale</h2>
          <p>{{ doneSteps }}/{{ onboarding.steps.length }} etapes terminees</p>
        </div>
        <div class="actions">
          <RouterLink class="secondary" to="/settings">Continuer</RouterLink>
          <button class="secondary" @click="dismissOnboarding">
            <X />Masquer
          </button>
        </div>
      </div>
      <div class="checklist">
        <span v-for="step in onboarding.steps" :key="step.id">
          <CheckCircle2 v-if="step.done" class="success-text" />
          <Circle v-else />
          {{ step.label }}
        </span>
      </div>
    </section>

    <!-- Stats summary metrics -->
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
      <!-- Demandes à valider -->
      <section class="panel">
        <div class="panel-head">
          <h2>Demandes a valider</h2>
          <RouterLink to="/requests" class="panel-link">Tout voir</RouterLink>
        </div>
        <article v-for="row in pending" :key="row.id" class="detail-row">
          <div>
            <strong>{{ row.title }}</strong>
            <span>{{ row.requested_by || row.plex_user || row.plex_user_id }}</span>
          </div>
          <div class="actions">
            <button class="icon-button success" title="Approuver" @click="action(row, 'approve')">
              <Check />
            </button>
            <button class="icon-button danger" title="Refuser" @click="action(row, 'reject')">
              <X />
            </button>
          </div>
        </article>
        <p v-if="!pending.length" class="empty">Aucune demande a valider.</p>
      </section>

      <!-- Exécutions récentes -->
      <section class="panel">
        <div class="panel-head">
          <h2>Execution recente</h2>
          <div class="actions">
            <select v-model="pollFilter" class="compact-select">
              <option value="all">Tous</option>
              <option value="errors">Erreurs uniquement</option>
              <option v-for="job in availableJobs" :key="job" :value="job">
                {{ friendlyJobName(job) }}
              </option>
            </select>
            <span v-if="nextPoll.next_run_seconds != null">
              Prochaine dans {{ countdown }}
            </span>
          </div>
        </div>

        <div v-for="run in filteredPolls" :key="run.id" class="detail-row-container">
          <div 
            class="detail-row" 
            :class="{ clickable: run.errors }" 
            @click="run.errors ? toggleError(run.id) : null"
          >
            <div>
              <strong>{{ friendlyJobName(run.job) }}</strong>
              <span>{{ formatDate(run.started_at) }}</span>
            </div>
            <span class="badge" :class="run.errors ? 'failed' : 'available'">
              {{ run.errors ? `${run.errors} erreur(s)` : `${run.items_processed || 0} traites` }}
            </span>
          </div>
          <div v-if="expandedErrors[run.id]" class="error-detail-box">
            <code>{{ run.error_detail }}</code>
          </div>
        </div>
        <p v-if="!filteredPolls.length" class="empty">Aucune execution enregistree.</p>
      </section>

      <!-- Répartition des demandes (Films vs Séries) -->
      <section class="panel">
        <div class="panel-head">
          <h2>Repartition des demandes</h2>
        </div>
        <div class="breakdown-grid">
          <div class="breakdown-card movie-card">
            <div class="breakdown-icon"><Film /></div>
            <div class="breakdown-info">
              <strong>{{ counts.by_type?.movie?.total ?? 0 }}</strong>
              <span>Films</span>
            </div>
            <div class="breakdown-sub">
              <span class="bsub-item"><span class="dot green"></span>{{ counts.by_type?.movie?.available ?? 0 }} dispos</span>
              <span class="bsub-item"><span class="dot yellow"></span>{{ counts.by_type?.movie?.sent_to_arr ?? 0 }} en cours</span>
              <span class="bsub-item"><span class="dot red"></span>{{ counts.by_type?.movie?.failed ?? 0 }} echoues</span>
            </div>
          </div>
          <div class="breakdown-card show-card">
            <div class="breakdown-icon"><Tv /></div>
            <div class="breakdown-info">
              <strong>{{ counts.by_type?.show?.total ?? 0 }}</strong>
              <span>Series</span>
            </div>
            <div class="breakdown-sub">
              <span class="bsub-item"><span class="dot green"></span>{{ counts.by_type?.show?.available ?? 0 }} dispos</span>
              <span class="bsub-item"><span class="dot yellow"></span>{{ counts.by_type?.show?.sent_to_arr ?? 0 }} en cours</span>
              <span class="bsub-item"><span class="dot red"></span>{{ counts.by_type?.show?.failed ?? 0 }} echoues</span>
            </div>
          </div>
        </div>
        <!-- Progress bar -->
        <div v-if="counts.total" class="type-ratio-bar">
          <div
            class="ratio-segment movie-seg"
            :style="{ width: `${(counts.by_type?.movie?.total ?? 0) / counts.total * 100}%` }"
            :title="`Films : ${counts.by_type?.movie?.total ?? 0}`"
          ></div>
          <div
            class="ratio-segment show-seg"
            :style="{ width: `${(counts.by_type?.show?.total ?? 0) / counts.total * 100}%` }"
            :title="`Series : ${counts.by_type?.show?.total ?? 0}`"
          ></div>
        </div>
      </section>

      <!-- File de téléchargement -->
      <section class="panel">
        <div class="panel-head">
          <h2>File de telechargement</h2>
          <RouterLink to="/downloads" class="panel-link">Tout voir</RouterLink>
        </div>
        <article v-for="item in downloadQueue" :key="item.id" class="detail-row">
          <div class="inline-row gap-10">
            <img v-if="item.poster_url" :src="item.poster_url" class="mini-poster" alt="" />
            <div>
              <strong>{{ item.title }}</strong>
              <span>{{ item.instance }} — {{ formatDownloadProgress(item) }}</span>
            </div>
          </div>
          <span class="badge dl-badge">
            <Download style="width:12px;height:12px" />
            {{ item.size_left_label || 'En cours' }}
          </span>
        </article>
        <p v-if="!downloadQueue.length && !loadingQueue" class="empty">Aucun telechargement en cours.</p>
        <p v-if="loadingQueue" class="empty"><LoaderCircle class="spin" style="width:16px;height:16px" /> Chargement...</p>
      </section>

      <!-- Activité sur 30 jours (étalé sur les deux colonnes) -->
      <section class="panel span-two">
        <div class="panel-head">
          <h2>Activite sur 30 jours</h2>
          <strong>{{ timelineTotal }} demandes</strong>
        </div>
        <div class="spark-bars">
          <i 
            v-for="(value, index) in timeline.values || []" 
            :key="index" 
            :style="{ height: `${Math.max(4, value / timelineMax * 100)}%` }" 
            :title="`${timeline.labels[index]} : ${value}`"
          ></i>
        </div>
      </section>

      <!-- Prochaines sorties (full width) -->
      <section v-if="upcoming.length" class="panel span-two">
        <div class="panel-head">
          <h2>Prochaines sorties</h2>
          <RouterLink to="/calendar" class="panel-link">Voir le calendrier</RouterLink>
        </div>
        <div class="upcoming-grid">
          <div v-for="item in upcoming" :key="item.id" class="upcoming-card">
            <div class="upcoming-poster">
              <img v-if="item.poster_url" :src="item.poster_url" alt="" loading="lazy" />
              <div v-else class="poster-fallback-inner"><Film /></div>
              <span class="upcoming-type-badge">{{ item.media_type === 'show' ? 'Série' : 'Film' }}</span>
            </div>
            <div class="upcoming-info">
              <strong>{{ item.title }}</strong>
              <span class="upcoming-label">{{ item.label }}</span>
              <span class="upcoming-date">{{ formatUpcomingDate(item.release_date) }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- Récemment Disponibles (étalé sur les deux colonnes) -->
      <section v-if="recentlyAvailable.length" class="panel span-two">
        <div class="panel-head">
          <h2>Recemment disponibles dans la bibliotheque</h2>
        </div>
        <div class="recently-available-grid">
          <div v-for="item in recentlyAvailable" :key="item.id" class="poster-card">
            <div class="poster-wrap">
              <img v-if="item.poster_url" :src="item.poster_url" alt="Poster" />
              <div v-else class="poster-fallback-inner"><Film /></div>
              <span class="media-type-badge" :class="item.media_type">{{ item.media_type === 'movie' ? 'Film' : 'Série' }}</span>
            </div>
            <strong>{{ item.title }}</strong>
            <span>{{ formatRelativeDate(item.available_at) }}</span>
          </div>
        </div>
      </section>

      <!-- Espace Disque -->
      <section class="panel">
        <div class="panel-head">
          <h2>Espace disque disponible</h2>
        </div>

        <!-- Commun / Shared -->
        <div v-if="categorizedVolumes.common.length" class="volume-group">
          <h3 class="volume-group-title">Espace Commun</h3>
          <article v-for="volume in categorizedVolumes.common" :key="volume.path" class="detail-row flex-column gap-6">
            <div class="inline-row justify-between w-100">
              <strong>{{ volume.path }}</strong>
              <span>{{ formatBytes(volume.free_bytes) }} libres sur {{ formatBytes(volume.total_bytes) }}</span>
            </div>
            <div class="progress-bar-wrap">
              <div class="progress-bar" :style="{ width: `${(volume.total_bytes - volume.free_bytes) / volume.total_bytes * 100}%` }"></div>
            </div>
          </article>
        </div>

        <!-- Sonarr Only -->
        <div v-if="categorizedVolumes.sonarr.length" class="volume-group">
          <h3 class="volume-group-title">Sonarr</h3>
          <article v-for="volume in categorizedVolumes.sonarr" :key="volume.path" class="detail-row flex-column gap-6">
            <div class="inline-row justify-between w-100">
              <strong>{{ volume.path }}</strong>
              <span>{{ formatBytes(volume.free_bytes) }} libres sur {{ formatBytes(volume.total_bytes) }}</span>
            </div>
            <div class="progress-bar-wrap">
              <div class="progress-bar" :style="{ width: `${(volume.total_bytes - volume.free_bytes) / volume.total_bytes * 100}%` }"></div>
            </div>
          </article>
        </div>

        <!-- Radarr Only -->
        <div v-if="categorizedVolumes.radarr.length" class="volume-group">
          <h3 class="volume-group-title">Radarr</h3>
          <article v-for="volume in categorizedVolumes.radarr" :key="volume.path" class="detail-row flex-column gap-6">
            <div class="inline-row justify-between w-100">
              <strong>{{ volume.path }}</strong>
              <span>{{ formatBytes(volume.free_bytes) }} libres sur {{ formatBytes(volume.total_bytes) }}</span>
            </div>
            <div class="progress-bar-wrap">
              <div class="progress-bar" :style="{ width: `${(volume.total_bytes - volume.free_bytes) / volume.total_bytes * 100}%` }"></div>
            </div>
          </article>
        </div>

        <p v-if="!diskSpace.length" class="empty">Aucun disque detecte.</p>
      </section>

      <!-- Top Demandes -->
      <section class="panel">
        <div class="panel-head">
          <h2>Demandes les plus populaires</h2>
        </div>
        <article v-for="item in topRequested" :key="item.id" class="detail-row">
          <div class="inline-row gap-10">
            <img v-if="item.poster_url" :src="item.poster_url" class="mini-poster" alt="" />
            <div v-else class="mini-poster"><Film style="width: 14px; height: 20px; margin: 8px 5px;" /></div>
            <div>
              <strong>{{ item.title }}</strong>
              <span>{{ item.media_type === 'movie' ? 'Film' : 'Série' }}</span>
            </div>
          </div>
          <span class="badge available">{{ item.count }} demandeurs</span>
        </article>
        <p v-if="!topRequested.length" class="empty">Aucune demande multiple.</p>
      </section>

      <!-- Utilisateurs actifs -->
      <section class="panel">
        <div class="panel-head">
          <h2>Utilisateurs actifs</h2>
          <RouterLink to="/users" class="panel-link">Gerer</RouterLink>
        </div>
        <article v-for="user in byUser.slice(0, 6)" :key="user.plex_user_id" class="detail-row">
          <strong>{{ user.display_name }}</strong>
          <span class="badge">{{ user.total }} demande(s)</span>
        </article>
        <p v-if="!byUser.length" class="empty">Aucune activite.</p>
      </section>

      <!-- Notifications récentes -->
      <section class="panel">
        <div class="panel-head">
          <h2>Notifications recentes</h2>
          <RouterLink to="/notifications" class="panel-link">Tout voir</RouterLink>
        </div>
        <article v-for="notif in recentNotifs" :key="notif.id" class="detail-row">
          <div>
            <strong>{{ notif.media_title || '—' }}</strong>
            <span>{{ notif.event_label }} · {{ notif.recipient }}</span>
          </div>
          <span class="badge" :class="notif.success ? 'available' : 'failed'">
            {{ notif.success ? 'Envoyé' : 'Erreur' }}
          </span>
        </article>
        <p v-if="!recentNotifs.length" class="empty">Aucune notification envoyee.</p>
      </section>

      <!-- Scan VF / Sync Plex -->
      <section class="panel span-two">
        <div class="panel-head">
          <h2>Etat des scans</h2>
          <div class="actions">
            <button class="secondary" :disabled="vffScan.status==='running'" @click="triggerVffScan">Scan VF</button>
            <button class="secondary" :disabled="plexSync.status==='running'" @click="triggerPlexSync">Sync Plex</button>
          </div>
        </div>

        <!-- VFF scan -->
        <div class="detail-row flex-column gap-6" style="margin-bottom:8px">
          <div class="inline-row justify-between w-100">
            <strong>Analyse VF</strong>
            <span class="badge" :class="vffScan.status==='running'?'pending':vffScan.status==='failed'?'failed':'available'">
              {{ vffScan.status==='running'?'En cours':vffScan.status==='failed'?'Erreur':'Inactif' }}
            </span>
          </div>
          <div v-if="vffScan.status==='running'" class="progress-bar-wrap">
            <div class="progress-bar animated" :style="{width: vffScan.total_items>0 ? `${Math.round(vffScan.items_scanned/vffScan.total_items*100)}%` : '5%'}"></div>
          </div>
          <span v-if="vffScan.status==='running'" style="font-size:12px;opacity:.6">
            {{ vffScan.items_scanned }} / {{ vffScan.total_items || '?' }} items
          </span>
          <span v-else-if="vffScan.finished_at" style="font-size:12px;opacity:.6">Termine le {{ formatDate(vffScan.finished_at) }}</span>
        </div>

        <!-- Plex sync -->
        <div class="detail-row flex-column gap-6">
          <div class="inline-row justify-between w-100">
            <strong>Synchronisation Plex</strong>
            <span class="badge" :class="plexSync.status==='running'?'pending':plexSync.status==='failed'?'failed':'available'">
              {{ plexSync.status==='running'?'En cours':plexSync.status==='failed'?'Erreur':'Inactif' }}
            </span>
          </div>
          <div v-if="plexSync.status==='running'" class="progress-bar-wrap">
            <div class="progress-bar animated" :style="{width: plexSync.total_items>0 ? `${Math.round(plexSync.items_synced/plexSync.total_items*100)}%` : '5%'}"></div>
          </div>
          <span v-if="plexSync.status==='running'" style="font-size:12px;opacity:.6">
            {{ plexSync.items_synced }} / {{ plexSync.total_items || '?' }} items
          </span>
          <span v-else-if="plexSync.finished_at" style="font-size:12px;opacity:.6">Termine le {{ formatDate(plexSync.finished_at) }}</span>
        </div>

        <!-- VFF counts -->
        <div v-if="vffCounts.vf_available!=null" class="inline-row gap-10" style="margin-top:8px;flex-wrap:wrap">
          <span class="badge available">VF : {{ vffCounts.vf_available }}</span>
          <span class="badge pending">VO en attente : {{ vffCounts.vo_pending }}</span>
          <span class="badge">Non analysé : {{ vffCounts.unchecked }}</span>
        </div>
      </section>

    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { Check, CheckCircle2, Circle, Download, Film, LoaderCircle, RefreshCw, Tv, X } from '@lucide/vue';
import HealthGrid from '@/components/HealthGrid.vue';
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

// Disk Space Categorization
const categorizedVolumes = computed(() => {
  const result = {
    sonarr: [],
    radarr: [],
    common: []
  };
  
  for (const vol of diskSpace.value) {
    const isSonarr = vol.sources.some(s => s.toLowerCase().includes('sonarr'));
    const isRadarr = vol.sources.some(s => s.toLowerCase().includes('radarr'));
    
    if (isSonarr && isRadarr) {
      result.common.push(vol);
    } else if (isSonarr) {
      result.sonarr.push(vol);
    } else if (isRadarr) {
      result.radarr.push(vol);
    }
  }
  return result;
});

// Onboarding Dismissal
const showOnboarding = ref(localStorage.getItem('hide_onboarding') !== 'true');
function dismissOnboarding() {
  localStorage.setItem('hide_onboarding', 'true');
  showOnboarding.value = false;
}

// Execution Filtering
const pollFilter = ref('all');
const availableJobs = computed(() => {
  const jobs = new Set(polls.value.map(p => p.job));
  return Array.from(jobs).filter(Boolean);
});
const filteredPolls = computed(() => {
  if (pollFilter.value === 'all') return polls.value;
  if (pollFilter.value === 'errors') return polls.value.filter(p => p.errors);
  return polls.value.filter(p => p.job === pollFilter.value);
});

// Expandable Job Failure Logs
const expandedErrors = reactive({});
function toggleError(id) {
  expandedErrors[id] = !expandedErrors[id];
}

// Human-friendly job names
function friendlyJobName(job) {
  const mapping = {
    'watchlist_poll': 'Watchlist Plex',
    'arr_sync': 'Sync Sonarr/Radarr',
    'vff_check': 'Analyse VF',
  };
  return mapping[job] || job;
}

// Formatting helpers
function formatBytes(bytes) {
  if (!bytes) return '0 Go';
  const g = bytes / (1024 * 1024 * 1024);
  if (g > 1024) {
    return (g / 1024).toFixed(1) + ' To';
  }
  return g.toFixed(1) + ' Go';
}

function formatRelativeDate(v) {
  if (!v) return '-';
  const diff = Date.now() - new Date(v).getTime();
  const days = Math.floor(diff / (1000 * 60 * 60 * 24));
  if (days === 0) return "Aujourd'hui";
  if (days === 1) return "Hier";
  return `Il y a ${days} jours`;
}

function formatUpcomingDate(v) {
  if (!v) return '-';
  return new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(v));
}

function formatDownloadProgress(item) {
  if (item.status === 'completed') return 'Terminé';
  if (item.size_left != null && item.size != null && item.size > 0) {
    const pct = Math.round((1 - item.size_left / item.size) * 100);
    return `${pct}%`;
  }
  return item.status || 'En cours';
}

const statCards = computed(() => [
  { label: 'Demandes en cours', value: ((counts.value.sent_to_arr ?? 0) + (counts.value.pending ?? 0) + (counts.value.pending_approval ?? 0)) || '-', route: { path: '/requests', query: { status: 'pending,sent_to_arr,pending_approval' } } },
  { label: 'En attente approbation', value: counts.value.pending_approval ?? pending.value.length, route: { path: '/requests', query: { status: 'pending_approval' } } },
  { label: 'Chez Sonarr', value: counts.value.by_type?.show?.sent_to_arr ?? '-', route: { path: '/requests', query: { status: 'sent_to_arr', type: 'show' } } },
  { label: 'Chez Radarr', value: counts.value.by_type?.movie?.sent_to_arr ?? '-', route: { path: '/requests', query: { status: 'sent_to_arr', type: 'movie' } } },
  { label: 'Disponibles', value: counts.value.available ?? '-', route: { path: '/requests', query: { status: 'available' } } },
]);

const doneSteps = computed(() => onboarding.value.steps?.filter(x => x.done).length || 0);
const timelineTotal = computed(() => (timeline.value.values || []).reduce((a, b) => a + b, 0));
const timelineMax = computed(() => Math.max(1, ...(timeline.value.values || [1])));
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
  try { await api('/api/vff/scan', { method: 'POST' }); await loadVffStatus(); } catch(e) {}
}

async function triggerPlexSync() {
  try { await api('/api/vff/sync-plex', { method: 'POST' }); await loadVffStatus(); } catch(e) {}
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
  // Notifications log has pagination wrapper
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

function formatDate(v) {
  return v ? new Intl.DateTimeFormat('fr-FR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(v)) : '-';
}

useRealtime(['request.updated'], load);

onMounted(async () => {
  await load();
  await loadVffStatus();
  timer = setInterval(() => {
    if (seconds.value > 0) seconds.value--;
  }, 1000);
  // Poll VFF status every 5s to update progress bars
  vffTimer = setInterval(loadVffStatus, 5000);
});

onUnmounted(() => { clearInterval(timer); clearInterval(vffTimer); });
</script>
