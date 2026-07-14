<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>Problèmes</h1>
        <p>Gestion des signalements utilisateur et problèmes remontés.</p>
      </div>
      <div class="actions">
        <button class="icon-button" :disabled="loading" title="Actualiser" @click="load">
          <RefreshCw :class="{ spin: loading }" />
        </button>
      </div>
    </header>

    <p v-if="error" class="notice error-text">{{ error }}</p>

    <div class="toolbar wrap">
      <select v-model="statusFilter" @change="load">
        <option value="">Tous les statuts</option>
        <option value="open">Ouverts</option>
        <option value="investigating">En cours</option>
        <option value="closed">Clos</option>
      </select>
    </div>

    <section class="panel table-wrap">
      <table>
        <thead>
          <tr>
            <th>Média / Type</th>
            <th>Message</th>
            <th>Statut</th>
            <th>Date</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="issue in issues" :key="issue.id">
            <td>
              <strong>{{ issue.media_title || issue.issue_type }}</strong>
            </td>
            <td>{{ issue.message || 'Sans commentaire' }}</td>
            <td>
              <span class="badge" :class="issue.status">{{ issue.status }}</span>
            </td>
            <td>{{ formatDate(issue.created_at) }}</td>
            <td class="actions">
              <button class="icon-button" title="Prendre en charge" v-if="issue.status !== 'investigating' && issue.status !== 'closed'" @click="updateIssue(issue, 'investigating')"><ScanSearch /></button>
              <button class="icon-button" title="Relancer" v-if="issue.status !== 'closed'" @click="retryIssue(issue)"><RotateCcw /></button>
              <button class="icon-button success" title="Clore" v-if="issue.status !== 'closed'" @click="updateIssue(issue, 'closed')"><Check /></button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="!loading && !issues.length" class="empty">Aucun signalement.</p>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue';
import { Check, RefreshCw, RotateCcw, ScanSearch } from '@lucide/vue';
import { api } from '@/api';

const issues = ref([]);
const loading = ref(false);
const error = ref('');
const statusFilter = ref('open');

function formatDate(value) {
  return value ? new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '-';
}

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const url = `/api/media/issues${statusFilter.value ? '?status=' + statusFilter.value : ''}`;
    issues.value = await api(url);
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}

async function updateIssue(issue, status) {
  try {
    await api(`/api/media/issues/${issue.id}`, { method: 'PATCH', body: JSON.stringify({ status }) });
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

async function retryIssue(issue) {
  try {
    await api(`/api/media/issues/${issue.id}/retry`, { method: 'POST' });
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

onMounted(load);
</script>
