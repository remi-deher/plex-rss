<template>
  <div class="shell">
    <!-- Desktop Sidebar -->
    <aside class="sidebar desktop-only">
      <div class="brand">
        Plexarr
      </div>
      
      <div class="menu-section">
        <span class="menu-label">Principal</span>
        <RouterLink to="/dashboard" title="Dashboard"><Gauge />Dashboard</RouterLink>
        <RouterLink to="/discover" title="Decouvrir"><Compass />Decouvrir</RouterLink>
        <RouterLink to="/library" title="Bibliotheque"><Library />Bibliotheque</RouterLink>
        <RouterLink to="/calendar" title="Calendrier"><CalendarDays />Calendrier</RouterLink>
        <RouterLink to="/downloads" title="Telechargements"><Download />Telechargements</RouterLink>
      </div>

      <div v-if="isAdmin" class="menu-section">
        <span class="menu-label">Administration</span>
        <RouterLink to="/users" title="Utilisateurs"><Users />Utilisateurs</RouterLink>
        <RouterLink to="/notifications" title="Notifications"><Bell />Notifications</RouterLink>
        <RouterLink to="/issues" title="Problemes"><Flag />Problemes</RouterLink>
        <RouterLink to="/logs" title="Journaux"><ScrollText />Journaux</RouterLink>
        <RouterLink to="/maintenance" title="Maintenance"><Wrench />Maintenance</RouterLink>
        <RouterLink to="/settings" title="Parametres"><Settings />Parametres</RouterLink>
      </div>

      <div class="menu-section mt-auto">
        <span class="menu-label">Compte</span>
        <RouterLink to="/profile" title="Profil"><UserRound />Profil</RouterLink>
        <a href="/logout" title="Deconnexion"><LogOut />Deconnexion</a>
      </div>
    </aside>

    <!-- Mobile Navigation Bar -->
    <nav class="mobile-nav-bar mobile-only">
      <RouterLink to="/dashboard" @click="closeMoreMenu"><Gauge /><span>Dashboard</span></RouterLink>
      <RouterLink to="/discover" @click="closeMoreMenu"><Compass /><span>Decouvrir</span></RouterLink>
      <RouterLink to="/library" @click="closeMoreMenu"><Library /><span>Bibliotheque</span></RouterLink>
      <RouterLink to="/calendar" @click="closeMoreMenu"><CalendarDays /><span>Calendrier</span></RouterLink>
      <button class="more-nav-btn" :class="{ active: isMoreOpen }" @click="toggleMoreMenu">
        <Menu />
        <span>Plus</span>
      </button>
    </nav>

    <!-- Mobile More Menu Overlay -->
    <Transition name="slide-up">
      <div v-if="isMoreOpen" class="mobile-more-overlay" @click.self="closeMoreMenu">
        <div class="mobile-more-sheet">
          <div class="sheet-header">
            <h3>Menu</h3>
            <button class="close-sheet-btn" @click="closeMoreMenu"><X /></button>
          </div>
          <div class="sheet-content">
            <div class="menu-section">
              <span class="menu-label">Principal</span>
              <RouterLink to="/downloads" @click="closeMoreMenu"><Download />Telechargements</RouterLink>
            </div>
            
            <div v-if="isAdmin" class="menu-section">
              <span class="menu-label">Administration</span>
              <RouterLink to="/users" @click="closeMoreMenu"><Users />Utilisateurs</RouterLink>
              <RouterLink to="/notifications" @click="closeMoreMenu"><Bell />Notifications</RouterLink>
              <RouterLink to="/issues" @click="closeMoreMenu"><Flag />Problemes</RouterLink>
              <RouterLink to="/logs" @click="closeMoreMenu"><ScrollText />Journaux</RouterLink>
              <RouterLink to="/maintenance" @click="closeMoreMenu"><Wrench />Maintenance</RouterLink>
              <RouterLink to="/settings" @click="closeMoreMenu"><Settings />Parametres</RouterLink>
            </div>
            
            <div class="menu-section">
              <span class="menu-label">Compte</span>
              <RouterLink to="/profile" @click="closeMoreMenu"><UserRound />Profil</RouterLink>
              <a href="/logout"><LogOut />Deconnexion</a>
            </div>
          </div>
        </div>
      </div>
    </Transition>

    <main class="main">
      <RouterView />
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { Bell, CalendarDays, Compass, Download, Gauge, Library, LogOut, ScrollText, Settings, UserRound, Users, Wrench, Menu, X } from "@lucide/vue";
import { api } from "@/api";
import { connectRealtime } from "@/events";
const session=ref(null);
const isAdmin=computed(()=>session.value?.is_owner||session.value?.role==='admin');
const isMoreOpen=ref(false);
function toggleMoreMenu(){isMoreOpen.value=!isMoreOpen.value}
function closeMoreMenu(){isMoreOpen.value=false}
onMounted(async()=>{session.value=await api('/api/session').catch(()=>null);if(session.value)connectRealtime()});
</script>
