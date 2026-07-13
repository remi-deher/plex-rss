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
      <article v-for="card in statCards" :key="card.label" class="metric-card">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
      </article>
    </section>

    <div class="dashboard-grid">
      <!-- Demandes à valider -->
      <section class="panel">
        <div class="panel-head">
          <h2>Demandes a valider</h2>
          <RouterLink to="/requests">Tout voir</RouterLink>
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
          <RouterLink to="/users">Gerer</RouterLink>
        </div>
        <article v-for="user in byUser.slice(0, 6)" :key="user.plex_user_id" class="detail-row">
          <strong>{{ user.display_name }}</strong>
          <span class="badge">{{ user.total }} demande(s)</span>
        </article>
        <p v-if="!byUser.length" class="empty">Aucune activite.</p>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { Check, CheckCircle2, Circle, Film, RefreshCw, X } from '@lucide/vue';
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
let timer;

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

const statCards = computed(() => [
  { label: 'Demandes', value: counts.value.total ?? '-' },
  { label: 'A valider', value: counts.value.pending_approval ?? pending.value.length },
  { label: 'Disponibles', value: counts.value.available ?? '-' },
  { label: 'Echouees', value: counts.value.failed ?? '-' }
]);

const doneSteps = computed(() => onboarding.value.steps?.filter(x => x.done).length || 0);
const timelineTotal = computed(() => (timeline.value.values || []).reduce((a, b) => a + b, 0));
const timelineMax = computed(() => Math.max(1, ...(timeline.value.values || [1])));
const countdown = computed(() => seconds.value == null ? '-' : seconds.value < 60 ? `${seconds.value}s` : `${Math.floor(seconds.value / 60)} min`);

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
    api('/api/stats/recently-available')
  ]);
  const refs = [counts, pending, polls, timeline, byUser, onboarding, nextPoll, diskSpace, topRequested, recentlyAvailable];
  results.forEach((r, i) => {
    if (r.status === 'fulfilled') refs[i].value = r.value;
  });
  seconds.value = nextPoll.value.next_run_seconds;
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
  timer = setInterval(() => {
    if (seconds.value > 0) seconds.value--;
  }, 1000);
});

onUnmounted(() => clearInterval(timer));
</script>
