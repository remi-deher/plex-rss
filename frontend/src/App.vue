<template>
  <div class="shell" :class="{'sidebar-collapsed':isSidebarCollapsed}">
    <!-- Desktop Sidebar -->
    <aside class="sidebar desktop-only" :class="{collapsed:isSidebarCollapsed}" :aria-expanded="!isSidebarCollapsed">
      <div class="brand">
        <span class="brand-name">Plexarr</span>
        <button class="sidebar-toggle" type="button" :aria-label="isSidebarCollapsed ? 'Afficher le menu' : 'Réduire le menu'" :title="isSidebarCollapsed ? 'Afficher le menu' : 'Réduire le menu'" @click="toggleSidebar">
          <PanelLeftOpen v-if="isSidebarCollapsed"/><PanelLeftClose v-else/>
        </button>
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
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute } from 'vue-router';
import { Bell, CalendarDays, ChevronDown, Compass, Download, Gauge, Library, LogOut, PanelLeftClose, PanelLeftOpen, Settings, ShieldCheck, UserRound, Users, Wrench, Menu, X } from "@lucide/vue";
import { api } from "@/api";
import { connectRealtime } from "@/events";
const session=ref(null);
const route=useRoute();
const isAdmin=computed(()=>session.value?.is_owner||session.value?.role==='admin');
const isSettingsRoute=computed(()=>route.path==='/settings'&&(!route.query.tab||['overview','connections','webhooks','library','downloads'].includes(route.query.tab)));
const isUsersRoute=computed(()=>route.path.startsWith('/users')||route.path==='/issues'||(route.path==='/library'&&route.query.status==='pending_approval'));
const isNotificationsRoute=computed(()=>route.path==='/notifications'||(route.path==='/settings'&&['notifications-channels','notifications-rules','templates'].includes(route.query.tab)));
const isOperationsRoute=computed(()=>['/logs','/maintenance'].includes(route.path)||(route.path==='/settings'&&['operations','scheduled-tasks','data'].includes(route.query.tab)));
const settingsSections=[{key:'overview',label:'Vue d’ensemble'},{key:'connections',label:'Connexions'},{key:'webhooks',label:'Webhooks'},{key:'library',label:'Bibliotheque'},{key:'downloads',label:'Telechargements'}];
const isMoreOpen=ref(false);
const isSidebarCollapsed=ref(false);
function toggleMoreMenu(){isMoreOpen.value=!isMoreOpen.value}
function closeMoreMenu(){isMoreOpen.value=false}
function toggleSidebar(){isSidebarCollapsed.value=!isSidebarCollapsed.value;localStorage.setItem('plexarr.sidebarCollapsed',String(isSidebarCollapsed.value))}
function handleEscape(event){if(event.key==='Escape'){if(window.innerWidth>640)isSidebarCollapsed.value=true;closeMoreMenu()}}
watch(()=>route.fullPath,closeMoreMenu);
onMounted(async()=>{const saved=localStorage.getItem('plexarr.sidebarCollapsed');isSidebarCollapsed.value=saved===null?window.matchMedia('(max-width:1024px)').matches:saved==='true';window.addEventListener('keydown',handleEscape);session.value=await api('/api/session').catch(()=>null);if(session.value)connectRealtime()});
onUnmounted(()=>window.removeEventListener('keydown',handleEscape));
</script>

<style scoped>
.context-nav-group{display:grid;gap:3px}.context-nav-group>a{width:100%}.context-chevron,.settings-chevron{margin-left:auto;width:14px;transition:transform .2s}.context-nav-group.open .context-chevron,.context-nav-group.open .settings-chevron{transform:rotate(180deg)}.context-sidebar-menu{display:grid;gap:2px;margin:2px 0 6px 22px;padding:5px 5px 5px 12px;border-left:2px solid rgba(229,160,13,.28);border-radius:0 8px 8px 0;background:linear-gradient(90deg,rgba(229,160,13,.055),transparent)}.context-sidebar-menu a{min-height:32px;padding:6px 10px 6px 16px;font-size:11.5px;color:color-mix(in srgb,var(--muted) 88%,white);border-radius:6px}.context-sidebar-menu a::after{content:'';position:absolute;left:5px;width:4px;height:4px;border-radius:50%;background:currentColor;opacity:.45}.context-sidebar-menu a:hover{color:var(--text);background:rgba(255,255,255,.045)}.context-sidebar-menu a.router-link-exact-active{color:var(--accent);background:rgba(229,160,13,.13);box-shadow:inset 0 0 0 1px rgba(229,160,13,.12)}.context-sidebar-menu a.router-link-exact-active::after{opacity:1;box-shadow:0 0 6px currentColor}.sidebar.collapsed .context-sidebar-menu,.sidebar.collapsed .context-chevron,.sidebar.collapsed .settings-chevron{display:none}
</style>
