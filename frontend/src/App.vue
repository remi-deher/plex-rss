<template>
  <div class="shell" :class="{'sidebar-collapsed':isSidebarCollapsed}">
    <a class="skip-link" href="#main-content">Aller au contenu principal</a>
    <!-- Desktop Sidebar -->
    <aside class="sidebar desktop-only" :class="{collapsed:isSidebarCollapsed}" aria-label="Navigation principale" :aria-expanded="!isSidebarCollapsed">
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
        <div v-if="isAdmin" class="context-nav-group" :class="{open:isActivityRoute}">
          <RouterLink to="/activity" title="Activité Plex"><Activity />Activité Plex<ChevronDown class="context-chevron"/></RouterLink>
          <div v-if="isActivityRoute" class="context-sidebar-menu">
            <RouterLink to="/activity">Vue d’ensemble</RouterLink>
            <RouterLink to="/activity?view=live">En direct</RouterLink>
            <RouterLink to="/activity?view=history">Historique</RouterLink>
            <RouterLink to="/activity?view=stats">Statistiques</RouterLink>
            <RouterLink to="/activity?view=quality">Qualité des flux</RouterLink>
            <RouterLink to="/activity?view=users">Utilisateurs</RouterLink>
          </div>
        </div>
        <RouterLink v-if="isAdmin" to="/analytics" title="Insights médiathèque"><ChartNoAxesCombined />Insights médiathèque</RouterLink>
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
    <nav class="mobile-nav-bar mobile-only" aria-label="Navigation principale">
      <RouterLink to="/dashboard" @click="closeMoreMenu"><Gauge /><span>Dashboard</span></RouterLink>
      <RouterLink to="/discover" @click="closeMoreMenu"><Compass /><span>Decouvrir</span></RouterLink>
      <RouterLink to="/library" @click="closeMoreMenu"><Library /><span>Bibliotheque</span></RouterLink>
      <RouterLink to="/calendar" @click="closeMoreMenu"><CalendarDays /><span>Calendrier</span></RouterLink>
      <button ref="moreButtonRef" type="button" class="more-nav-btn" :class="{ active: isMoreOpen }" aria-controls="mobile-more-menu" :aria-expanded="isMoreOpen" @click="toggleMoreMenu">
        <Menu />
        <span>Plus</span>
      </button>
    </nav>

    <!-- Mobile More Menu Overlay -->
    <Transition name="slide-up">
      <div v-if="isMoreOpen" class="mobile-more-overlay" @click.self="closeMoreMenu">
        <div id="mobile-more-menu" ref="mobileMoreRef" class="mobile-more-sheet" role="dialog" aria-modal="true" aria-labelledby="mobile-menu-title" tabindex="-1">
          <div class="sheet-header">
            <h2 id="mobile-menu-title">Menu</h2>
            <button type="button" class="close-sheet-btn" aria-label="Fermer le menu" @click="closeMoreMenu"><X /></button>
          </div>
          <div class="sheet-content">
            <div class="menu-section">
              <span class="menu-label">Principal</span>
              <RouterLink to="/downloads" @click="closeMoreMenu"><Download />Telechargements</RouterLink>
              <details v-if="isAdmin" class="mobile-activity-group" :open="isActivityRoute"><summary><Activity/>Activité Plex</summary><RouterLink to="/activity" @click="closeMoreMenu">Vue d’ensemble</RouterLink><RouterLink to="/activity?view=live" @click="closeMoreMenu">En direct</RouterLink><RouterLink to="/activity?view=history" @click="closeMoreMenu">Historique</RouterLink><RouterLink to="/activity?view=stats" @click="closeMoreMenu">Statistiques</RouterLink><RouterLink to="/activity?view=quality" @click="closeMoreMenu">Qualité des flux</RouterLink><RouterLink to="/activity?view=users" @click="closeMoreMenu">Utilisateurs</RouterLink></details>
              <RouterLink v-if="isAdmin" to="/analytics" @click="closeMoreMenu"><ChartNoAxesCombined />Insights médiathèque</RouterLink>
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

    <main id="main-content" class="main" tabindex="-1">
      <RouterView />
    </main>
    <ToastStack :toasts="toasts" @dismiss="dismissToast"/>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute } from 'vue-router';
import { Activity, Bell, CalendarDays, ChartNoAxesCombined, ChevronDown, Compass, Download, Gauge, Library, LogOut, PanelLeftClose, PanelLeftOpen, Settings, ShieldCheck, UserRound, Users, Wrench, Menu, X } from "@lucide/vue";
import { api } from "@/api";
import { connectRealtime } from "@/events";
import ToastStack from "@/components/ui/ToastStack.vue";
import { playbackStartsFromEvent, playbackTitle } from "@/playbackToast";
import { useModalA11y } from "@/composables/useModalA11y";
const session=ref(null);
const route=useRoute();
const isAdmin=computed(()=>session.value?.is_owner||session.value?.role==='admin');
const isActivityRoute=computed(()=>route.path==='/activity');
const isSettingsRoute=computed(()=>route.path==='/settings'&&(!route.query.tab||['overview','connections','webhooks','library','downloads'].includes(route.query.tab)));
const isUsersRoute=computed(()=>route.path.startsWith('/users')||route.path==='/issues'||(route.path==='/library'&&route.query.status==='pending_approval'));
const isNotificationsRoute=computed(()=>route.path==='/notifications'||(route.path==='/settings'&&['notifications-channels','notifications-rules','templates'].includes(route.query.tab)));
const isOperationsRoute=computed(()=>['/logs','/maintenance'].includes(route.path)||(route.path==='/settings'&&['operations','scheduled-tasks','data'].includes(route.query.tab)));
const settingsSections=[{key:'overview',label:'Vue d’ensemble'},{key:'connections',label:'Connexions'},{key:'webhooks',label:'Webhooks'},{key:'library',label:'Bibliotheque'},{key:'downloads',label:'Telechargements'}];
const isMoreOpen=ref(false);
const mobileMoreRef=ref(null);
const moreButtonRef=ref(null);
const isSidebarCollapsed=ref(false);
const toasts=ref([]);
const seenPlaybackEvents=new Set();
const toastTimers=new Map();
function toggleMoreMenu(){isMoreOpen.value=!isMoreOpen.value}
function closeMoreMenu(){isMoreOpen.value=false}
function toggleSidebar(){isSidebarCollapsed.value=!isSidebarCollapsed.value;localStorage.setItem('plexarr.sidebarCollapsed',String(isSidebarCollapsed.value))}
function dismissToast(id){toasts.value=toasts.value.filter(toast=>toast.id!==id);clearTimeout(toastTimers.get(id));toastTimers.delete(id)}
function showPlaybackToasts(event){
  const started=playbackStartsFromEvent(event);
  for(const session of started){
    const fingerprint=`${event.detail.id||''}:${session.session_id||session.id||playbackTitle(session)}`;
    if(seenPlaybackEvents.has(fingerprint))continue;
    seenPlaybackEvents.add(fingerprint);
    const id=`playback-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    toasts.value=[...toasts.value.slice(-3),{id,type:'playback',title:`${session.user_name||'Un utilisateur'} lance une lecture`,message:playbackTitle(session),image:session.thumb_url||''}];
    toastTimers.set(id,setTimeout(()=>dismissToast(id),7000));
  }
}
watch(()=>route.fullPath,closeMoreMenu);
watch(isMoreOpen,open=>{document.body.classList.toggle('modal-open',open)});
useModalA11y(mobileMoreRef,isMoreOpen,closeMoreMenu);
onMounted(async()=>{const saved=localStorage.getItem('plexarr.sidebarCollapsed');isSidebarCollapsed.value=saved===null?window.matchMedia('(max-width:1024px)').matches:saved==='true';window.addEventListener('plexarr:activity.updated',showPlaybackToasts);session.value=await api('/api/session').catch(()=>null);if(session.value)connectRealtime()});
onUnmounted(()=>{document.body.classList.remove('modal-open');window.removeEventListener('plexarr:activity.updated',showPlaybackToasts);toastTimers.forEach(clearTimeout)});
</script>

<style scoped>
.context-nav-group{display:grid;gap:3px}.context-nav-group>a{width:100%}.context-chevron,.settings-chevron{margin-left:auto;width:14px;transition:transform .2s}.context-nav-group.open .context-chevron,.context-nav-group.open .settings-chevron{transform:rotate(180deg)}.context-sidebar-menu{display:grid;gap:2px;margin:2px 0 6px 22px;padding:5px 5px 5px 12px;border-left:2px solid rgba(229,160,13,.28);border-radius:0 8px 8px 0;background:linear-gradient(90deg,rgba(229,160,13,.055),transparent)}.context-sidebar-menu a{min-height:32px;padding:6px 10px 6px 16px;font-size:11.5px;color:color-mix(in srgb,var(--muted) 88%,white);border-radius:6px}.context-sidebar-menu a::after{content:'';position:absolute;left:5px;width:4px;height:4px;border-radius:50%;background:currentColor;opacity:.45}.context-sidebar-menu a:hover{color:var(--text);background:rgba(255,255,255,.045)}.context-sidebar-menu a.router-link-exact-active{color:var(--accent);background:rgba(229,160,13,.13);box-shadow:inset 0 0 0 1px rgba(229,160,13,.12)}.context-sidebar-menu a.router-link-exact-active::after{opacity:1;box-shadow:0 0 6px currentColor}.sidebar.collapsed .context-sidebar-menu,.sidebar.collapsed .context-chevron,.sidebar.collapsed .settings-chevron{display:none}
.mobile-activity-group{overflow:hidden;border:1px solid rgba(255,255,255,.06);border-radius:10px}.mobile-activity-group summary{display:flex;align-items:center;gap:12px;min-height:48px;padding:10px 14px;color:var(--muted);font-size:13px;cursor:pointer;list-style:none}.mobile-activity-group summary::-webkit-details-marker{display:none}.mobile-activity-group summary svg{width:18px}.mobile-activity-group[open] summary{color:#fff;border-bottom:1px solid rgba(255,255,255,.06)}.mobile-activity-group a{margin:4px 8px;min-height:42px;padding-left:44px;background:transparent}
</style>
