<template>
  <div class="shell" :class="{'sidebar-collapsed':activeSpaceCollapsed,'discover-shell':isDiscoverRoute||isActivitySpaceRoute||isAdminSpaceRoute}">
    <a class="skip-link" href="#main-content">Aller au contenu principal</a>
    <AdminNavigation v-if="isAdminSpaceRoute" :collapsed="isAdminSidebarCollapsed" @toggle="toggleAdminSidebar" />
    <ActivityNavigation v-else-if="isActivitySpaceRoute" :collapsed="isActivitySidebarCollapsed" @toggle="toggleActivitySidebar" />
    <DiscoverNavigation v-else-if="isDiscoverRoute" :is-admin="isAdmin" :collapsed="isDiscoverSidebarCollapsed" @toggle="toggleDiscoverSidebar" />
    <template v-else>
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
        <RouterLink v-if="isAdmin" to="/dashboard" title="Dashboard"><Gauge />Dashboard</RouterLink>
        <RouterLink to="/discover" title="Decouvrir"><Compass />Decouvrir</RouterLink>
        <RouterLink v-if="canModerate" to="/library" title="Bibliotheque"><Library />Bibliotheque</RouterLink>
        <RouterLink to="/calendar" title="Calendrier"><CalendarDays />Calendrier</RouterLink>
        <RouterLink v-if="isAdmin" to="/downloads" title="Telechargements"><Download />Telechargements</RouterLink>
        <RouterLink v-if="isAdmin" to="/activity" title="Activité &amp; Insights"><Activity />Activité &amp; Insights</RouterLink>
        <RouterLink v-if="isAdmin" to="/users" title="Administration"><Wrench />Administration</RouterLink>
        <RouterLink v-if="canModerate && !isAdmin" to="/issues" title="Problèmes signalés"><MessageSquareWarning />Problèmes signalés</RouterLink>
      </div>

      <div class="menu-section mt-auto">
        <span class="menu-label">Compte</span>
        <RouterLink to="/profile" title="Profil"><UserRound />Profil</RouterLink>
        <a href="/privacy" title="Confidentialite"><ShieldCheck />Confidentialite</a>
        <a href="/logout" title="Deconnexion" @click="clearCache"><LogOut />Deconnexion</a>
      </div>
    </aside>

    <!-- Mobile Navigation Bar -->
    <nav class="mobile-nav-bar mobile-only" aria-label="Navigation principale">
      <RouterLink v-if="isAdmin" to="/dashboard" @click="closeMoreMenu"><Gauge /><span>Dashboard</span></RouterLink>
      <RouterLink to="/discover" @click="closeMoreMenu"><Compass /><span>Decouvrir</span></RouterLink>
      <RouterLink v-if="canModerate" to="/library" @click="closeMoreMenu"><Library /><span>Bibliotheque</span></RouterLink>
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
              <RouterLink v-if="isAdmin" to="/downloads" @click="closeMoreMenu"><Download />Telechargements</RouterLink>
              <RouterLink v-if="isAdmin" to="/activity" @click="closeMoreMenu"><Activity />Activité &amp; Insights</RouterLink>
              <RouterLink v-if="isAdmin" to="/users" @click="closeMoreMenu"><Wrench />Administration</RouterLink>
              <RouterLink v-if="canModerate && !isAdmin" to="/issues" @click="closeMoreMenu"><MessageSquareWarning />Problèmes signalés</RouterLink>
            </div>

            <div class="menu-section">
              <span class="menu-label">Compte</span>
              <RouterLink to="/profile" @click="closeMoreMenu"><UserRound />Profil</RouterLink>
              <a href="/privacy"><ShieldCheck />Confidentialite</a>
              <a href="/logout" @click="clearCache"><LogOut />Deconnexion</a>
            </div>
          </div>
        </div>
      </div>
    </Transition>
    </template>

    <main id="main-content" class="main" tabindex="-1">
      <RouterView />
    </main>
    <ToastStack :toasts="toasts" @dismiss="dismissToast"/>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute } from 'vue-router';
import { Activity, CalendarDays, Compass, Download, Gauge, Library, LogOut, MessageSquareWarning, PanelLeftClose, PanelLeftOpen, ShieldCheck, UserRound, Wrench, Menu, X } from "@lucide/vue";
import { api } from "@/api";
import { clearCache, syncCacheOwner } from "@/cache";
import { connectRealtime } from "@/events";
import ToastStack from "@/components/ui/ToastStack.vue";
import DiscoverNavigation from "@/components/discover/DiscoverNavigation.vue";
import ActivityNavigation from "@/components/activity/ActivityNavigation.vue";
import AdminNavigation from "@/components/admin/AdminNavigation.vue";
import { playbackStartsFromEvent, playbackTitle } from "@/playbackToast";
import { useModalA11y } from "@/composables/useModalA11y";
import { canModerateSession, isAdminSession, loadSession } from "@/composables/useSession";
const session=ref(null);
const route=useRoute();
const isAdmin=computed(()=>isAdminSession(session.value));
const canModerate=computed(()=>canModerateSession(session.value));
const isDiscoverRoute=computed(()=>route.path.startsWith('/discover'));
const isActivitySpaceRoute=computed(()=>['/activity','/analytics'].some(p=>route.path.startsWith(p)));
const isAdminSpaceRoute=computed(()=>['/users','/notifications','/settings','/logs','/maintenance'].some(p=>route.path.startsWith(p)));
const isMoreOpen=ref(false);
const mobileMoreRef=ref(null);
const moreButtonRef=ref(null);
const isSidebarCollapsed=ref(false);
const isDiscoverSidebarCollapsed=ref(false);
const isActivitySidebarCollapsed=ref(false);
const isAdminSidebarCollapsed=ref(false);
const activeSpaceCollapsed=computed(()=>isAdminSpaceRoute.value?isAdminSidebarCollapsed.value:isActivitySpaceRoute.value?isActivitySidebarCollapsed.value:isDiscoverRoute.value?isDiscoverSidebarCollapsed.value:isSidebarCollapsed.value);
const toasts=ref([]);
const seenPlaybackEvents=new Set();
const toastTimers=new Map();
function toggleMoreMenu(){isMoreOpen.value=!isMoreOpen.value}
function closeMoreMenu(){isMoreOpen.value=false}
function toggleSidebar(){isSidebarCollapsed.value=!isSidebarCollapsed.value;localStorage.setItem('plexarr.sidebarCollapsed',String(isSidebarCollapsed.value))}
function toggleDiscoverSidebar(){isDiscoverSidebarCollapsed.value=!isDiscoverSidebarCollapsed.value;localStorage.setItem('plexarr.discoverSidebarCollapsed',String(isDiscoverSidebarCollapsed.value))}
function toggleActivitySidebar(){isActivitySidebarCollapsed.value=!isActivitySidebarCollapsed.value;localStorage.setItem('plexarr.activitySidebarCollapsed',String(isActivitySidebarCollapsed.value))}
function toggleAdminSidebar(){isAdminSidebarCollapsed.value=!isAdminSidebarCollapsed.value;localStorage.setItem('plexarr.adminSidebarCollapsed',String(isAdminSidebarCollapsed.value))}
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
// Un import complet a remplace toute la base : tout ce que cet onglet affiche, et tout ce
// qu'il a mis en cache, reference des lignes qui n'existent plus. On purge et on recharge
// plutot que de laisser l'utilisateur agir sur des donnees fantomes.
function onMigrationCompleted(){clearCache();window.location.reload()}
watch(()=>route.fullPath,closeMoreMenu);
watch(isMoreOpen,open=>{document.body.classList.toggle('modal-open',open)});
useModalA11y(mobileMoreRef,isMoreOpen,closeMoreMenu);
onMounted(async()=>{
  const isNarrow=window.matchMedia('(max-width:1024px)').matches;
  const saved=localStorage.getItem('plexarr.sidebarCollapsed');
  const discoverSaved=localStorage.getItem('plexarr.discoverSidebarCollapsed');
  const activitySaved=localStorage.getItem('plexarr.activitySidebarCollapsed');
  const adminSaved=localStorage.getItem('plexarr.adminSidebarCollapsed');
  isSidebarCollapsed.value=saved===null?isNarrow:saved==='true';
  isDiscoverSidebarCollapsed.value=discoverSaved===null?isNarrow:discoverSaved==='true';
  isActivitySidebarCollapsed.value=activitySaved===null?isNarrow:activitySaved==='true';
  isAdminSidebarCollapsed.value=adminSaved===null?isNarrow:adminSaved==='true';
  window.addEventListener('plexarr:activity.updated',showPlaybackToasts);window.addEventListener('plexarr:migration.completed',onMigrationCompleted);session.value=await loadSession();syncCacheOwner(session.value);if(session.value)connectRealtime()});
onUnmounted(()=>{document.body.classList.remove('modal-open');window.removeEventListener('plexarr:activity.updated',showPlaybackToasts);window.removeEventListener('plexarr:migration.completed',onMigrationCompleted);toastTimers.forEach(clearTimeout)});
</script>

