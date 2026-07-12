<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>Decouvrir</h1>
        <p>Recherche TMDB et demandes sans bloquer le reste de l'interface.</p>
      </div>
      <input v-model="query" class="search" type="search" placeholder="Rechercher un film ou une serie" @input="scheduleSearch" />
    </header>

    <section class="media-grid">
      <article v-for="item in items" :key="item.id || item.tmdb_id" class="media-card">
        <img v-if="item.poster_url" :src="item.poster_url" alt="" />
        <div v-else class="poster-fallback"><Film /></div>
        <div>
          <strong>{{ item.title || item.name }}</strong>
          <span>{{ item.media_type === "show" ? "Serie" : "Film" }}<template v-if="item.year"> - {{ item.year }}</template></span>
        </div>
      </article>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { Film } from "@lucide/vue";
import { api } from "@/api";

const items = ref([]);
const query = ref("");
let timer = null;

async function loadTrending() {
  items.value = await api("/api/discover/trending");
}

function scheduleSearch() {
  clearTimeout(timer);
  timer = setTimeout(async () => {
    const q = query.value.trim();
    items.value = q ? await api(`/api/discover/search?query=${encodeURIComponent(q)}`) : await api("/api/discover/trending");
  }, 250);
}

onMounted(loadTrending);
</script>
