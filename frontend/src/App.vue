<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">Plexarr</div>
      <RouterLink to="/dashboard"><Gauge />Dashboard</RouterLink>
      <RouterLink to="/discover"><Compass />Decouvrir</RouterLink>
      <RouterLink to="/requests"><ListChecks />Demandes</RouterLink>
      <RouterLink to="/library"><Library />Bibliotheque</RouterLink>
      <RouterLink to="/calendar"><CalendarDays />Calendrier</RouterLink>
      <RouterLink to="/downloads"><Download />Telechargements</RouterLink>
      <RouterLink v-if="isAdmin" to="/users"><Users />Utilisateurs</RouterLink>
      <RouterLink v-if="isAdmin" to="/notifications"><Bell />Notifications</RouterLink>
      <RouterLink v-if="isAdmin" to="/maintenance"><Wrench />Maintenance</RouterLink>
      <RouterLink v-if="isAdmin" to="/settings"><Settings />Parametres</RouterLink>
      <a href="/profile"><UserRound />Profil</a>
      <a href="/logout"><LogOut />Deconnexion</a>
    </aside>
    <main class="main">
      <RouterView />
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { Bell, CalendarDays, Compass, Download, Gauge, Library, ListChecks, LogOut, Settings, UserRound, Users, Wrench } from "@lucide/vue";
import { api } from "@/api";
const session=ref(null);
const isAdmin=computed(()=>session.value?.is_owner||session.value?.role==='admin');
onMounted(async()=>{session.value=await api('/api/session').catch(()=>null)});
</script>
