<template>
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
</template>

<script setup>
import { computed, reactive, ref } from 'vue';

const props = defineProps({
  polls: { type: Array, default: () => [] },
  nextPoll: { type: Object, default: () => ({}) },
  countdown: { type: String, default: '-' },
});

const pollFilter = ref('all');
const availableJobs = computed(() => {
  const jobs = new Set(props.polls.map(p => p.job));
  return Array.from(jobs).filter(Boolean);
});
const filteredPolls = computed(() => {
  if (pollFilter.value === 'all') return props.polls;
  if (pollFilter.value === 'errors') return props.polls.filter(p => p.errors);
  return props.polls.filter(p => p.job === pollFilter.value);
});

const expandedErrors = reactive({});
function toggleError(id) {
  expandedErrors[id] = !expandedErrors[id];
}

function friendlyJobName(job) {
  const mapping = {
    'watchlist_poll': 'Watchlist Plex',
    'arr_sync': 'Sync Sonarr/Radarr',
    'vff_check': 'Analyse VF',
  };
  return mapping[job] || job;
}

function formatDate(v) {
  return v ? new Intl.DateTimeFormat('fr-FR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(v)) : '-';
}
</script>
