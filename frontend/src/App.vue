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
        <div class="context-nav-group" :class="{open:isUsersRoute}">
          <RouterLink to="/users" title="Utilisateurs"><Users />Utilisateurs<ChevronDown class="context-chevron"/></RouterLink>
          <div v-if="isUsersRoute" class="context-sidebar-menu"><RouterLink to="/users">Comptes</RouterLink><RouterLink to="/library?status=pending_approval">Approbations</RouterLink><RouterLink to="/issues">Problemes signales</RouterLink></div>
        </div>
        <div class="context-nav-group" :class="{open:isNotificationsRoute}">
          <RouterLink to="/notifications" title="Notifications"><Bell />Notifications<ChevronDown class="context-chevron"/></RouterLink>
          <div v-if="isNotificationsRoute" class="context-sidebar-menu"><RouterLink to="/notifications?tab=history">Journal</RouterLink><RouterLink to="/notifications?tab=pending">File d'attente</RouterLink><RouterLink to="/settings?tab=notifications-channels">Canaux</RouterLink><RouterLink to="/settings?tab=notifications-rules">Regles</RouterLink><RouterLink to="/settings?tab=templates">Modeles d'emails</RouterLink></div>
        </div>
        <div class="context-nav-group" :class="{open:isOperationsRoute}">
          <RouterLink to="/settings?tab=operations" title="Exploitation"><Wrench />Exploitation<ChevronDown class="context-chevron"/></RouterLink>
          <div v-if="isOperationsRoute" class="context-sidebar-menu"><RouterLink to="/settings?tab=operations">Vue d'ensemble</RouterLink><RouterLink to="/settings?tab=scheduled-tasks">Taches planifiees</RouterLink><RouterLink to="/logs">Journaux</RouterLink><RouterLink to="/maintenance">Maintenance</RouterLink><RouterLink to="/settings?tab=data">Donnees</RouterLink></div>
        </div>
        <div class="context-nav-group" :class="{open:isSettingsRoute}">
          <RouterLink to="/settings" title="Parametres"><Settings />Parametres<ChevronDown class="settings-chevron"/></RouterLink>
          <div v-if="isSettingsRoute" class="context-sidebar-menu">
            <RouterLink v-for="item in settingsSections" :key="item.key" :to="`/settings?tab=${item.key}`">{{ item.label }}</RouterLink>
          </div>
        </div>
      </div>

      <div class="menu-section mt-auto">
        <span class="menu-label">Compte</span>
        <RouterLink to="/profile" title="Profil"><UserRound />Profil</RouterLink>
        <a href="/privacy" title="Confidentialite"><ShieldCheck />Confidentialite</a>
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
            
            <div v-if="isAdmin" class="menu-section mobile-admin-groups">
              <span class="menu-label">Administration</span>
              <details><summary><Users/>Utilisateurs</summary><RouterLink to="/users" @click="closeMoreMenu">Comptes</RouterLink><RouterLink to="/library?status=pending_approval" @click="closeMoreMenu">Approbations</RouterLink><RouterLink to="/issues" @click="closeMoreMenu">Problemes signales</RouterLink></details>
              <details><summary><Bell/>Notifications</summary><RouterLink to="/notifications?tab=history" @click="closeMoreMenu">Journal</RouterLink><RouterLink to="/notifications?tab=pending" @click="closeMoreMenu">File d'attente</RouterLink><RouterLink to="/settings?tab=notifications-channels" @click="closeMoreMenu">Canaux</RouterLink><RouterLink to="/settings?tab=notifications-rules" @click="closeMoreMenu">Regles</RouterLink><RouterLink to="/settings?tab=templates" @click="closeMoreMenu">Modeles d'emails</RouterLink></details>
              <details><summary><Wrench/>Exploitation</summary><RouterLink to="/settings?tab=operations" @click="closeMoreMenu">Vue d'ensemble</RouterLink><RouterLink to="/settings?tab=scheduled-tasks" @click="closeMoreMenu">Taches planifiees</RouterLink><RouterLink to="/logs" @click="closeMoreMenu">Journaux</RouterLink><RouterLink to="/maintenance" @click="closeMoreMenu">Maintenance</RouterLink><RouterLink to="/settings?tab=data" @click="closeMoreMenu">Donnees</RouterLink></details>
              <details><summary><Settings/>Parametres</summary><RouterLink v-for="item in settingsSections" :key="item.key" :to="`/settings?tab=${item.key}`" @click="closeMoreMenu">{{ item.label }}</RouterLink></details>
            </div>
            
            <div class="menu-section">
              <span class="menu-label">Compte</span>
              <RouterLink to="/profile" @click="closeMoreMenu"><UserRound />Profil</RouterLink>
              <a href="/privacy"><ShieldCheck />Confidentialite</a>
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
import { useRoute } from 'vue-router';
import { Bell, CalendarDays, ChevronDown, Compass, Download, Gauge, Library, LogOut, ScrollText, Settings, ShieldCheck, UserRound, Users, Wrench, Menu, X } from "@lucide/vue";
import { api } from "@/api";
import { connectRealtime } from "@/events";
const session=ref(null);
const route=useRoute();
const isAdmin=computed(()=>session.value?.is_owner||session.value?.role==='admin');
const isSettingsRoute=computed(()=>route.path==='/settings'&&(!route.query.tab||['connections','webhooks','library','downloads'].includes(route.query.tab)));
const isUsersRoute=computed(()=>route.path.startsWith('/users')||route.path==='/issues'||(route.path==='/library'&&route.query.status==='pending_approval'));
const isNotificationsRoute=computed(()=>route.path==='/notifications'||(route.path==='/settings'&&['notifications-channels','notifications-rules','templates'].includes(route.query.tab)));
const isOperationsRoute=computed(()=>['/logs','/maintenance'].includes(route.path)||(route.path==='/settings'&&['operations','scheduled-tasks','data'].includes(route.query.tab)));
const settingsSections=[{key:'connections',label:'Connexions'},{key:'webhooks',label:'Webhooks'},{key:'library',label:'Bibliotheque'},{key:'downloads',label:'Telechargements'}];
const isMoreOpen=ref(false);
function toggleMoreMenu(){isMoreOpen.value=!isMoreOpen.value}
function closeMoreMenu(){isMoreOpen.value=false}
onMounted(async()=>{session.value=await api('/api/session').catch(()=>null);if(session.value)connectRealtime()});
</script>

<style scoped>
.context-nav-group{display:grid}.context-nav-group>a{width:100%}.context-chevron,.settings-chevron{margin-left:auto;width:14px;transition:transform .2s}.context-nav-group.open .context-chevron,.context-nav-group.open .settings-chevron{transform:rotate(180deg)}.context-sidebar-menu{display:grid;margin:3px 0 2px 28px;padding-left:10px;border-left:1px solid var(--border)}.context-sidebar-menu a{min-height:30px;padding:6px 9px;font-size:11px;color:var(--muted);border-radius:5px}.context-sidebar-menu a.router-link-exact-active{color:var(--accent);background:rgba(229,160,13,.1)}
@media(max-width:1024px){.context-sidebar-menu,.context-chevron,.settings-chevron{display:none}}
</style>
