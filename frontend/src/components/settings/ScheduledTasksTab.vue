<template>
  <div class="settings-grid">
    <div class="settings-cards span-two">
      <SettingsCard
        v-for="task in tasks"
        :key="task.job"
        :title="task.label"
        :subtitle="task.description"
        :icon="Clock"
        :status="cardStatus(task)"
        :status-text="cardStatusText(task)"
      >
        <template #actions>
          <button class="secondary" @click.stop="toggleHistory(task.job)">
            <History/>{{ openHistory === task.job ? 'Masquer' : 'Historique' }}
          </button>
        </template>

        <div class="scheduled-task-info">
          <div class="scheduled-task-row">
            <span>Intervalle actuel</span>
            <strong>{{ formatInterval(task.interval_seconds) }}</strong>
          </div>
          <div v-if="task.fixed_schedule" class="scheduled-task-row">
            <span>Planification</span>
            <strong>{{ task.fixed_schedule }}</strong>
          </div>
          <div v-if="task.state?.finished_at" class="scheduled-task-row">
            <span>Derniere execution</span>
            <strong>{{ formatDate(task.state.finished_at) }} ({{ formatDuration(task.state.duration_ms) }})</strong>
          </div>
          <div v-if="task.state?.status === 'failed' && task.state?.last_error" class="scheduled-task-error">
            {{ task.state.last_error }}
          </div>
        </div>

        <label v-if="task.job === 'arr-statuses'">
          Intervalle de verification (minutes)
          <input v-model.number="form.arr_poll_interval_minutes" type="number" min="1">
        </label>
        <p v-else-if="task.settings_field" class="hint">
          Modifiable depuis l'onglet Automatisation.
        </p>

        <div v-if="openHistory === task.job" class="scheduled-task-history">
          <p v-if="historyLoading" class="notice">Chargement...</p>
          <ul v-else-if="history.length">
            <li v-for="row in history" :key="row.id" :class="row.status">
              <span class="history-status">{{ row.status === 'complete' ? 'OK' : 'Echec' }}</span>
              <span>{{ formatDate(row.started_at) }}</span>
              <span>{{ formatDuration(row.duration_ms) }}</span>
              <span v-if="row.error" class="scheduled-task-error">{{ row.error }}</span>
            </li>
          </ul>
          <p v-else class="empty">Aucun historique.</p>
        </div>
      </SettingsCard>
    </div>
  </div>
</template>
<script setup>
import { onMounted, ref } from 'vue';
import { Clock, History } from '@lucide/vue';
import { api } from '@/api';
import { form } from '@/settingsForm';
import SettingsCard from './SettingsCard.vue';

const tasks = ref([]);
const openHistory = ref(null);
const history = ref([]);
const historyLoading = ref(false);

function cardStatus(task) {
  const status = task.state?.status;
  if (status === 'failed') return 'error';
  if (status === 'complete') return 'active';
  return 'neutral';
}

function cardStatusText(task) {
  const status = task.state?.status;
  if (status === 'failed') return 'Echec';
  if (status === 'complete') return 'OK';
  if (status === 'running') return 'En cours';
  return 'Jamais execute';
}

function formatInterval(seconds) {
  if (!seconds) return '-';
  if (seconds < 60) return `${seconds} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h`;
  return `${Math.round(seconds / 86400)} j`;
}

function formatDuration(ms) {
  if (ms == null) return '-';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function formatDate(value) {
  return value ? new Intl.DateTimeFormat('fr-FR', { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(value)) : '-';
}

async function loadTasks() {
  tasks.value = await api('/api/scheduled-tasks');
}

async function toggleHistory(job) {
  if (openHistory.value === job) {
    openHistory.value = null;
    return;
  }
  openHistory.value = job;
  historyLoading.value = true;
  try {
    history.value = await api(`/api/scheduled-tasks/${job}/history`);
  } finally {
    historyLoading.value = false;
  }
}

onMounted(loadTasks);
</script>
<style scoped>
.scheduled-task-info {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
}
.scheduled-task-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--muted);
}
.scheduled-task-row strong {
  color: var(--text);
  font-weight: 500;
  text-align: right;
}
.scheduled-task-error {
  font-size: 12px;
  color: var(--red);
  word-break: break-word;
}
.scheduled-task-history {
  border-top: 1px solid var(--border);
  padding-top: 12px;
  margin-top: 4px;
}
.scheduled-task-history ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.scheduled-task-history li {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  font-size: 12px;
  padding: 6px 8px;
  border-radius: 6px;
  background: var(--surface-2);
}
.scheduled-task-history li.failed {
  background: rgba(239, 68, 68, 0.08);
}
.history-status {
  font-weight: 600;
  min-width: 42px;
}
.scheduled-task-history li.failed .history-status {
  color: var(--red);
}
.scheduled-task-history li:not(.failed) .history-status {
  color: var(--green);
}
</style>
