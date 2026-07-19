<template>
  <div class="page">
    <PageHeader title="Maintenance" description="Opérations contrôlées et progression en direct." eyebrow="Exploitation">
      <button class="icon-button" :disabled="loading" title="Actualiser" @click="load">
        <RefreshCw :class="{spin:loading}"/>
      </button>
    </PageHeader>
    <UiFeedback v-if="error" type="error" :message="error" retry @retry="load" />
    <section class="action-grid">
      <article v-for="(meta, key) in actions" :key="key" class="panel action-card">
        <div>
          <h2>{{ meta.label || key }}</h2>
          <p>{{ meta.description }}</p>
          <p v-if="!meta.enabled" class="text-sm error-text mt-2" style="font-size: 0.85em; color: var(--error);">
            <i class="bi bi-exclamation-triangle"></i> {{ meta.disabled_reason }}
          </p>
        </div>
        <button class="primary" :disabled="running || meta.enabled === false" @click="run(key)">
          <Play/>Executer
        </button>
      </article>
    </section>
    <section v-if="current" class="panel run-panel">
      <div class="panel-head">
        <h2>{{ current.action }}</h2>
        <StatusBadge :status="current.status" />
      </div>
      <progress :value="current.progress" max="100"></progress>
      <pre>{{ (current.logs || []).join('\n') }}</pre>
    </section>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import { Play, RefreshCw } from "@lucide/vue";
import { api } from "@/api";
import { useRealtime } from "@/events";

const actions = ref({});
const current = ref(null);
const loading = ref(false);
const running = ref(false);
const error = ref('');
let timer, runId;

async function load() {
  loading.value = true;
  try {
    actions.value = await api('/api/maintenance/actions');
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}

async function run(action) {
  running.value = true;
  error.value = '';
  try {
    const data = await api(`/api/maintenance/run/${action}`, { method: 'POST' });
    runId = data.run_id;
    poll(runId);
  } catch (e) {
    error.value = e.message;
    running.value = false;
  }
}

async function poll(id) {
  clearTimeout(timer);
  try {
    current.value = await api(`/api/maintenance/run/${id}`);
    if (['done', 'error'].includes(current.value.status)) {
      running.value = false;
      return;
    }
    timer = setTimeout(() => poll(id), 10000);
  } catch (e) {
    error.value = e.message;
    running.value = false;
  }
}

useRealtime(['job.updated'], (_, event) => {
  if (runId && event?.payload?.run_id === runId) poll(runId);
});

onMounted(load);
onUnmounted(() => clearTimeout(timer));
</script>
