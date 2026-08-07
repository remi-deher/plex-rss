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
      <RouterLink to="/notifications" title="Notifications" :class="{ 'router-link-active': isNotificationsRoute }"><Bell />Notifications</RouterLink>
      <RouterLink to="/settings" title="Parametres"><Settings />Parametres</RouterLink>
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
            <RouterLink to="/notifications" @click="closeMoreMenu"><Bell/>Notifications</RouterLink>
            <RouterLink to="/settings" @click="closeMoreMenu"><Settings/>Parametres</RouterLink>
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
import { Bell, ChevronUp, CircleUserRound, Compass, House, LogOut, MoreHorizontal, PanelLeftClose, PanelLeftOpen, Settings, UserRound, Users, Wrench, X } from '@lucide/vue';
import { clearCache } from '@/cache';
import { useModalA11y } from '@/composables/useModalA11y';

defineProps({ collapsed: { type: Boolean, default: false } });
defineEmits(['toggle']);

const route = useRoute();
const isMoreOpen = ref(false);
const mobileMoreRef = ref(null);
const moreButtonRef = ref(null);

const isNotificationsRoute = computed(() => route.path === '/notifications');

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
