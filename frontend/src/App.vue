<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">Plexarr</div>
      <RouterLink to="/dashboard"><Gauge />Dashboard</RouterLink>
      <RouterLink to="/discover"><Compass />Decouvrir</RouterLink>
      <RouterLink to="/downloads"><Download />Telechargements</RouterLink>
      <a href="/library"><Library />Jinja: Bibliotheque</a>
      <a href="/settings"><Settings />Jinja: Parametres</a>
    </aside>
    <main class="main">
      <RouterView />
    </main>
  </div>
</template>

<script setup>
import { Compass, Download, Gauge, Library, Settings } from "@lucide/vue";
</script>
