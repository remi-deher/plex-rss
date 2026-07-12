<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>Dashboard</h1>
        <p>Vue SPA connectee aux endpoints FastAPI asynchrones.</p>
      </div>
      <button class="primary" :disabled="polling" @click="pollNow">
        <RefreshCw :class="{ spin: polling }" />Verifier maintenant
      </button>
    </header>

    <HealthGrid />

    <section class="metric-grid">
      <article v-for="card in statCards" :key="card.label" class="metric-card">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
      </article>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { RefreshCw } from "@lucide/vue";
import HealthGrid from "@/components/HealthGrid.vue";
import { api } from "@/api";

const counts = ref({});
const polling = ref(false);

const statCards = computed(() => [
  { label: "Demandes", value: counts.value.total ?? "-" },
  { label: "Transmises", value: counts.value.sent_to_arr ?? "-" },
  { label: "Disponibles", value: counts.value.available ?? "-" },
  { label: "Echouees", value: counts.value.failed ?? "-" },
]);

async function loadCounts() {
  counts.value = await api("/api/stats/counts");
}

async function pollNow() {
  polling.value = true;
  try {
    await api("/api/requests/poll", { method: "POST" });
    await loadCounts();
  } finally {
    polling.value = false;
  }
}

onMounted(loadCounts);
</script>
