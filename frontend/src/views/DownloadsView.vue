<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>Telechargements</h1>
        <p>Files Sonarr/Radarr et clients directs agregees.</p>
      </div>
      <button class="icon-button" :disabled="loading" @click="load"><RefreshCw :class="{ spin: loading }" /></button>
    </header>

    <section class="panel list">
      <article v-for="row in rows" :key="rowKey(row)" class="queue-row">
        <Download />
        <div>
          <strong>{{ row.title || "Telechargement" }}</strong>
          <span>{{ row.instance || row.download_client || row.status || "En cours" }}</span>
        </div>
        <small v-if="row.progress != null">{{ Math.round(row.progress) }}%</small>
      </article>
      <p v-if="!loading && rows.length === 0" class="empty">Aucun telechargement actif.</p>
    </section>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import { Download, RefreshCw } from "@lucide/vue";
import { api } from "@/api";
import { useRealtime } from "@/events";

const rows = ref([]);
const loading = ref(false);

function rowKey(row) {
  return `${row.instance_id || row.instance || "direct"}:${row.queue_id || row.download_id || row.title}`;
}

async function load() {
  loading.value = true;
  try {
    const [arr, direct] = await Promise.all([
      api("/api/arr/queue").catch(() => []),
      api("/api/downloads/direct").catch(() => []),
    ]);
    rows.value = [...arr, ...direct];
  } finally {
    loading.value = false;
  }
}

let fallback;
useRealtime(["download.updated"], load);
onMounted(()=>{load();fallback=setInterval(load,60000)});
onUnmounted(()=>clearInterval(fallback));
</script>
