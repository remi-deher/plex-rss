<template>
  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>Sante des services</h2>
        <p>{{ updatedLabel }}</p>
      </div>
      <button class="icon-button" :disabled="loading" @click="refresh" title="Actualiser" aria-label="Actualiser">
        <RefreshCw :class="{ spin: loading }" />
      </button>
    </div>
    <div class="health-grid">
      <article v-for="item in cards" :key="item.key" class="health-card" :class="item.state">
        <component :is="item.icon" />
        <div>
          <strong>{{ item.label }}</strong>
          <span>{{ item.message }}</span>
        </div>
        <small v-if="item.response_ms != null">{{ item.response_ms }} ms</small>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { Compass, Mail, RefreshCw, Rss, Search, Server, Tv, Video } from "@lucide/vue";
import { api, cachedResource } from "@/api";
import { useRealtime } from "@/events";

const CACHE_KEY = "plexarr.vue.health";
const loading = ref(false);
const health = ref(null);
const checkedAt = ref(null);

const meta = {
  sonarr: ["Sonarr", Tv],
  radarr: ["Radarr", Video],
  prowlarr: ["Prowlarr", Search],
  plex: ["Plex API", Server],
  seer: ["Seer", Compass],
  smtp: ["Email", Mail],
  rss: ["Flux RSS", Rss],
};

const cards = computed(() => Object.entries(meta).map(([key, [label, icon]]) => {
  const info = health.value?.services?.[key] || {};
  return {
    key,
    label,
    icon,
    state: info.state || "loading",
    message: info.message || "Chargement conserve en arriere-plan",
    response_ms: info.response_ms,
  };
}));

const updatedLabel = computed(() => {
  if (!checkedAt.value) return "Anciennes donnees conservees pendant le chargement";
  const seconds = Math.max(0, Math.floor((Date.now() - checkedAt.value.getTime()) / 1000));
  if (seconds < 60) return "Verifie a l'instant";
  if (seconds < 3600) return `Verifie il y a ${Math.floor(seconds / 60)} min`;
  return `Verifie il y a ${Math.floor(seconds / 3600)} h`;
});

async function refresh() {
  loading.value = true;
  try {
    const data = await api("/api/health");
    health.value = data;
    checkedAt.value = data.checked_at ? new Date(data.checked_at) : new Date();
    localStorage.setItem(CACHE_KEY, JSON.stringify({ savedAt: Date.now(), data }));
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  const { cached, refresh: refreshPromise } = cachedResource(CACHE_KEY, 120000, () => api("/api/health"));
  if (cached) {
    health.value = cached;
    checkedAt.value = cached.checked_at ? new Date(cached.checked_at) : null;
  } else {
    loading.value = true;
  }
  refreshPromise.then((data) => {
    health.value = data;
    checkedAt.value = data.checked_at ? new Date(data.checked_at) : new Date();
  }).finally(() => {
    loading.value = false;
  });
});
useRealtime(["health.updated"], refresh);
</script>
