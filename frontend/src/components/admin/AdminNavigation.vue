<template>
  <aside class="sidebar admin-sidebar desktop-only" :class="{ collapsed }" aria-label="Navigation Administration" :aria-expanded="!collapsed">
    <div class="brand admin-brand">
      <span class="brand-mark"><Wrench /></span>
      <span><strong>Plexarr</strong></span>
      <button class="sidebar-toggle" type="button" :aria-label="collapsed ? 'Afficher le menu' : 'Réduire le menu'" :title="collapsed ? 'Afficher le menu' : 'Réduire le menu'" @click="$emit('toggle')">
        <PanelLeftOpen v-if="collapsed"/><PanelLeftClose v-else/>
      </button>
    </div>

    <div class="menu-section admin-home-nav">
      <RouterLink to="/dashboard" title="Accueil"><House />Accueil</RouterLink>
    </div>

    <div class="menu-section admin-primary-nav">
      <span class="menu-label">Administration</span>
      <RouterLink to="/users" title="Utilisateurs"><Users />Utilisateurs</RouterLink>
      <div class="context-nav-group" :class="{open:isNotificationsRoute}">
        <RouterLink to="/notifications" title="Notifications"><Bell />Notifications<ChevronDown class="context-chevron"/></RouterLink>
        <div v-if="isNotificationsRoute" class="context-sidebar-menu"><RouterLink to="/notifications?tab=history">Journal</RouterLink><RouterLink to="/notifications?tab=pending">File d'attente</RouterLink><RouterLink to="/settings?tab=notifications-channels">Canaux</RouterLink><RouterLink to="/settings?tab=notifications-rules">Regles</RouterLink><RouterLink to="/settings?tab=templates">Modeles d'emails</RouterLink></div>
      </div>
      <div class="context-nav-group" :class="{open:isOperationsRoute}">
        <RouterLink to="/settings?tab=operations" title="Exploitation"><Wrench />Exploitation<ChevronDown class="context-chevron"/></RouterLink>
        <div v-if="isOperationsRoute" class="context-sidebar-menu"><RouterLink to="/settings?tab=operations">Vue d'ensemble</RouterLink><RouterLink to="/settings?tab=scheduled-tasks">Taches planifiees</RouterLink><RouterLink to="/settings?tab=conflicts">Conflits</RouterLink><RouterLink to="/settings?tab=acquisitions">Acquisitions</RouterLink><RouterLink to="/logs">Journaux</RouterLink><RouterLink to="/maintenance">Maintenance</RouterLink><RouterLink to="/settings?tab=data">Donnees</RouterLink></div>
      </div>
      <div class="context-nav-group" :class="{open:isSettingsRoute}">
        <RouterLink to="/settings" title="Parametres"><Settings />Parametres<ChevronDown class="settings-chevron"/></RouterLink>
        <div v-if="isSettingsRoute" class="context-sidebar-menu">
          <RouterLink v-for="item in settingsSections" :key="item.key" :to="`/settings?tab=${item.key}`">{{ item.label }}</RouterLink>
        </div>
      </div>
    </div>

    <details class="admin-account desktop-only">
      <summary><CircleUserRound /><span>Plus</span><ChevronUp /></summary>
      <div class="admin-account-popover">
        <RouterLink to="/profile"><UserRound />Profil</RouterLink>
        <RouterLink to="/discover"><Compass />Application principale</RouterLink>
        <a href="/logout" @click="clearCache"><LogOut />Déconnexion</a>
      </div>
    </details>
  </aside>

  <nav class="mobile-nav-bar mobile-only admin-mobile-nav" aria-label="Navigation Administration">
    <RouterLink to="/users" @click="closeMoreMenu"><Users /><span>Utilisateurs</span></RouterLink>
    <RouterLink to="/notifications" @click="closeMoreMenu"><Bell /><span>Notifications</span></RouterLink>
    <RouterLink to="/settings?tab=operations" @click="closeMoreMenu"><Wrench /><span>Exploitation</span></RouterLink>
    <RouterLink to="/settings" @click="closeMoreMenu"><Settings /><span>Parametres</span></RouterLink>
    <button ref="moreButtonRef" type="button" class="more-nav-btn" :class="{ active: isMoreOpen }" aria-controls="admin-mobile-more" :aria-expanded="isMoreOpen" @click="toggleMoreMenu">
      <MoreHorizontal /><span>Plus</span>
    </button>
  </nav>

  <Transition name="slide-up">
    <div v-if="isMoreOpen" class="mobile-more-overlay" @click.self="closeMoreMenu">
      <div id="admin-mobile-more" ref="mobileMoreRef" class="mobile-more-sheet" role="dialog" aria-modal="true" aria-labelledby="admin-menu-title" tabindex="-1">
        <div class="sheet-header">
          <h2 id="admin-menu-title">Menu</h2>
          <button type="button" class="close-sheet-btn" aria-label="Fermer le menu" @click="closeMoreMenu"><X /></button>
        </div>
        <div class="sheet-content">
          <div class="menu-section">
            <RouterLink to="/dashboard" @click="closeMoreMenu"><House />Accueil</RouterLink>
          </div>
          <div class="menu-section mobile-admin-groups">
            <span class="menu-label">Administration</span>
            <RouterLink to="/users" @click="closeMoreMenu"><Users/>Utilisateurs</RouterLink>
            <details><summary><Bell/>Notifications</summary><RouterLink to="/notifications?tab=history" @click="closeMoreMenu">Journal</RouterLink><RouterLink to="/notifications?tab=pending" @click="closeMoreMenu">File d'attente</RouterLink><RouterLink to="/settings?tab=notifications-channels" @click="closeMoreMenu">Canaux</RouterLink><RouterLink to="/settings?tab=notifications-rules" @click="closeMoreMenu">Regles</RouterLink><RouterLink to="/settings?tab=templates" @click="closeMoreMenu">Modeles d'emails</RouterLink></details>
            <details><summary><Wrench/>Exploitation</summary><RouterLink to="/settings?tab=operations" @click="closeMoreMenu">Vue d'ensemble</RouterLink><RouterLink to="/settings?tab=scheduled-tasks" @click="closeMoreMenu">Taches planifiees</RouterLink><RouterLink to="/settings?tab=conflicts" @click="closeMoreMenu">Conflits</RouterLink><RouterLink to="/settings?tab=acquisitions" @click="closeMoreMenu">Acquisitions</RouterLink><RouterLink to="/logs" @click="closeMoreMenu">Journaux</RouterLink><RouterLink to="/maintenance" @click="closeMoreMenu">Maintenance</RouterLink><RouterLink to="/settings?tab=data" @click="closeMoreMenu">Donnees</RouterLink></details>
            <details><summary><Settings/>Parametres</summary><RouterLink v-for="item in settingsSections" :key="item.key" :to="`/settings?tab=${item.key}`" @click="closeMoreMenu">{{ item.label }}</RouterLink></details>
          </div>
          <div class="menu-section">
            <span class="menu-label">Compte</span>
            <RouterLink to="/profile" @click="closeMoreMenu"><UserRound />Profil</RouterLink>
            <RouterLink to="/discover" @click="closeMoreMenu"><Compass />Application principale</RouterLink>
            <a href="/logout" @click="clearCache"><LogOut />Déconnexion</a>
          </div>
        </div>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { Bell, ChevronDown, ChevronUp, CircleUserRound, Compass, House, LogOut, MoreHorizontal, PanelLeftClose, PanelLeftOpen, Settings, UserRound, Users, Wrench, X } from '@lucide/vue';
import { clearCache } from '@/cache';
import { useModalA11y } from '@/composables/useModalA11y';

defineProps({ collapsed: { type: Boolean, default: false } });
defineEmits(['toggle']);

const route = useRoute();
const isMoreOpen = ref(false);
const mobileMoreRef = ref(null);
const moreButtonRef = ref(null);

const isSettingsRoute = computed(() => route.path === '/settings' && (!route.query.tab || ['overview', 'connections', 'webhooks', 'library', 'downloads'].includes(route.query.tab)));
const isNotificationsRoute = computed(() => route.path === '/notifications' || (route.path === '/settings' && ['notifications-channels', 'notifications-rules', 'templates'].includes(route.query.tab)));
const isOperationsRoute = computed(() => ['/logs', '/maintenance'].includes(route.path) || (route.path === '/settings' && ['operations', 'scheduled-tasks', 'conflicts', 'acquisitions', 'data'].includes(route.query.tab)));
const settingsSections = [
  { key: 'overview', label: 'Vue d’ensemble' },
  { key: 'connections', label: 'Connexions' },
  { key: 'webhooks', label: 'Webhooks' },
  { key: 'library', label: 'Bibliotheque' },
  { key: 'downloads', label: 'Telechargements' },
];

function toggleMoreMenu() { isMoreOpen.value = !isMoreOpen.value; }
function closeMoreMenu() { isMoreOpen.value = false; }

watch(() => route.fullPath, closeMoreMenu);
watch(isMoreOpen, open => document.body.classList.toggle('modal-open', open));
useModalA11y(mobileMoreRef, isMoreOpen, closeMoreMenu);
onUnmounted(() => document.body.classList.remove('modal-open'));
</script>

<style scoped>
.admin-sidebar { background: linear-gradient(180deg, color-mix(in srgb, var(--surface) 88%, #17110a), var(--surface)); }
.admin-brand { align-items: center; }
.admin-brand .sidebar-toggle { margin-left: auto; }
.admin-brand > span:last-child { display: grid; line-height: 1.05; }
.admin-brand strong { font-size: var(--fs-md); }
.brand-mark { display: grid; flex: none; place-items: center; width: 34px; height: 34px; border-radius: 10px; color: #111; background: var(--accent); box-shadow: 0 8px 24px rgba(229,160,13,.18); }
.brand-mark svg { width: 19px; }
.admin-primary-nav { margin-top: var(--space-2); }
.admin-account { position: relative; margin-top: auto; }
.admin-account summary { display: flex; align-items: center; gap: var(--space-3); min-height: 42px; padding: 0 12px; border-radius: var(--radius-sm); color: var(--muted); font-size: var(--fs-sm); cursor: pointer; list-style: none; }
.admin-account summary::-webkit-details-marker { display: none; }
.admin-account summary:hover, .admin-account[open] summary { color: #fff; background: rgba(255,255,255,.04); }
.admin-account summary svg:last-child { width: 14px; margin-left: auto; transition: transform .2s ease; }
.admin-account[open] summary svg:last-child { transform: rotate(180deg); }
.admin-account-popover { position: absolute; right: 0; bottom: calc(100% + 8px); left: 0; display: grid; gap: 3px; padding: 7px; border: 1px solid var(--border); border-radius: var(--radius-md); background: #17171c; box-shadow: 0 16px 38px rgba(0,0,0,.42); }
.admin-account-popover a { min-height: 38px; }

/* Repris de App.vue (context-nav-group vivait auparavant uniquement dans son <style scoped>) */
.context-nav-group{display:grid;gap: var(--space-1)}.context-nav-group>a{width:100%}.context-chevron,.settings-chevron{margin-left:auto;width:14px;transition:transform .2s}.context-nav-group.open .context-chevron,.context-nav-group.open .settings-chevron{transform:rotate(180deg)}.context-sidebar-menu{display:grid;gap: var(--space-1);margin:2px 0 6px 22px;padding:5px 5px 5px 12px;border-left:2px solid rgba(229,160,13,.28);border-radius:0 8px 8px 0;background:linear-gradient(90deg,rgba(229,160,13,.055),transparent)}.context-sidebar-menu a{min-height:32px;padding:6px 10px 6px 16px;font-size:var(--fs-xs);color:color-mix(in srgb,var(--muted) 88%,white);border-radius:var(--radius-sm)}.context-sidebar-menu a::after{content:'';position:absolute;left:5px;width:4px;height:4px;border-radius:50%;background:currentColor;opacity:.45}.context-sidebar-menu a:hover{color:var(--text);background:rgba(255,255,255,.045)}.context-sidebar-menu a.router-link-exact-active{color:var(--accent);background:rgba(229,160,13,.13);box-shadow:inset 0 0 0 1px rgba(229,160,13,.12)}.context-sidebar-menu a.router-link-exact-active::after{opacity:1;box-shadow:0 0 6px currentColor}

.admin-sidebar.collapsed .context-sidebar-menu,.admin-sidebar.collapsed .context-chevron,.admin-sidebar.collapsed .settings-chevron{display:none}
.admin-sidebar.collapsed .admin-brand > span:not(.brand-mark),
.admin-sidebar.collapsed .admin-account span,
.admin-sidebar.collapsed .admin-account summary svg:last-child { display: none; }
.admin-sidebar.collapsed .admin-brand { justify-content: center; padding-inline: 0; }
.admin-sidebar.collapsed .brand-mark { display: none; }
.admin-sidebar.collapsed .admin-account summary { justify-content: center; padding: 0; }
.admin-sidebar.collapsed .admin-account-popover { position: fixed; bottom: 24px; left: 76px; width: 240px; }
.admin-sidebar.collapsed .admin-account-popover a { justify-content: flex-start; gap: var(--space-3); padding: 0 12px; font-size: var(--fs-sm); }
@media (min-width: 641px) and (max-width: 1024px) {
  .admin-sidebar .brand-mark { margin: auto; }
  .admin-sidebar .admin-brand > span:last-child, .admin-sidebar .menu-label, .admin-sidebar .admin-account span, .admin-sidebar .admin-account summary svg:last-child { display: none; }
  .admin-sidebar .admin-account summary { justify-content: center; padding: 0; }
  .admin-account-popover { position: fixed; bottom: 24px; left: 76px; width: 240px; }
  .admin-account-popover a { justify-content: flex-start; gap: var(--space-3); padding: 0 12px; font-size: var(--fs-sm); }
}
</style>
