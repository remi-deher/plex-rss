<template>
  <aside class="sidebar discover-sidebar desktop-only" :class="{ collapsed }" aria-label="Navigation Découverte" :aria-expanded="!collapsed">
    <div class="brand discover-brand">
      <span class="brand-mark"><Compass /></span>
      <span><strong>Plexarr</strong><small>Découverte</small></span>
      <button class="sidebar-toggle" type="button" :aria-label="collapsed ? 'Afficher le menu' : 'Réduire le menu'" :title="collapsed ? 'Afficher le menu' : 'Réduire le menu'" @click="$emit('toggle')">
        <PanelLeftOpen v-if="collapsed"/><PanelLeftClose v-else/>
      </button>
    </div>

    <div class="menu-section discover-primary-nav">
      <span class="menu-label">Découvrir</span>
      <RouterLink to="/discover" active-class="" exact-active-class="router-link-active" title="Accueil"><House />Accueil</RouterLink>
      <RouterLink to="/discover/shows" title="Séries"><Tv />Séries</RouterLink>
      <RouterLink to="/discover/movies" title="Films"><Film />Films</RouterLink>
      <RouterLink to="/discover/requests" title="Demandes"><Inbox />Demandes</RouterLink>
    </div>

    <details class="discover-account desktop-only">
      <summary><CircleUserRound /><span>Plus</span><ChevronUp /></summary>
      <div class="discover-account-popover">
        <RouterLink to="/profile"><UserRound />Profil</RouterLink>
        <RouterLink v-if="isAdmin" to="/dashboard"><LayoutDashboard />Application principale</RouterLink>
        <a href="/logout" @click="clearCache"><LogOut />Déconnexion</a>
      </div>
    </details>
  </aside>

  <nav class="mobile-nav-bar mobile-only discover-mobile-nav" aria-label="Navigation Découverte">
    <RouterLink to="/discover" active-class="" exact-active-class="router-link-active" @click="closeMoreMenu"><House /><span>Accueil</span></RouterLink>
    <RouterLink to="/discover/shows" @click="closeMoreMenu"><Tv /><span>Séries</span></RouterLink>
    <RouterLink to="/discover/movies" @click="closeMoreMenu"><Film /><span>Films</span></RouterLink>
    <RouterLink to="/discover/requests" @click="closeMoreMenu"><Inbox /><span>Demandes</span></RouterLink>
    <button ref="moreButtonRef" type="button" class="more-nav-btn" :class="{ active: isMoreOpen }" aria-controls="discover-mobile-more" :aria-expanded="isMoreOpen" @click="toggleMoreMenu">
      <MoreHorizontal /><span>Plus</span>
    </button>
  </nav>

  <Transition name="slide-up">
    <div v-if="isMoreOpen" class="mobile-more-overlay" @click.self="closeMoreMenu">
      <div id="discover-mobile-more" ref="mobileMoreRef" class="mobile-more-sheet" role="dialog" aria-modal="true" aria-labelledby="discover-menu-title" tabindex="-1">
        <div class="sheet-header">
          <h2 id="discover-menu-title">Compte</h2>
          <button type="button" class="close-sheet-btn" aria-label="Fermer le menu" @click="closeMoreMenu"><X /></button>
        </div>
        <div class="sheet-content">
          <div class="menu-section">
            <RouterLink to="/profile" @click="closeMoreMenu"><UserRound />Profil</RouterLink>
            <RouterLink v-if="isAdmin" to="/dashboard" @click="closeMoreMenu"><LayoutDashboard />Application principale</RouterLink>
            <a href="/logout" @click="clearCache"><LogOut />Déconnexion</a>
          </div>
        </div>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { onUnmounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { ChevronUp, CircleUserRound, Compass, Film, House, Inbox, LayoutDashboard, LogOut, MoreHorizontal, PanelLeftClose, PanelLeftOpen, Tv, UserRound, X } from '@lucide/vue';
import { clearCache } from '@/cache';
import { useModalA11y } from '@/composables/useModalA11y';

defineProps({ isAdmin: { type: Boolean, default: false }, collapsed: { type: Boolean, default: false } });
defineEmits(['toggle']);

const route = useRoute();
const isMoreOpen = ref(false);
const mobileMoreRef = ref(null);
const moreButtonRef = ref(null);

function toggleMoreMenu() { isMoreOpen.value = !isMoreOpen.value; }
function closeMoreMenu() { isMoreOpen.value = false; }

watch(() => route.fullPath, closeMoreMenu);
watch(isMoreOpen, open => document.body.classList.toggle('modal-open', open));
useModalA11y(mobileMoreRef, isMoreOpen, closeMoreMenu);
onUnmounted(() => document.body.classList.remove('modal-open'));
</script>

<style scoped>
.discover-sidebar { background: linear-gradient(180deg, color-mix(in srgb, var(--surface) 88%, #17110a), var(--surface)); }
.discover-brand { align-items: center; }
.discover-brand .sidebar-toggle { margin-left: auto; }
.discover-brand > span:last-child { display: grid; line-height: 1.05; }
.discover-brand strong { font-size: var(--fs-md); }
.discover-brand small { margin-top: 4px; color: var(--accent); font-size: 10px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
.brand-mark { display: grid; flex: none; place-items: center; width: 34px; height: 34px; border-radius: 10px; color: #111; background: var(--accent); box-shadow: 0 8px 24px rgba(229,160,13,.18); }
.brand-mark svg { width: 19px; }
.discover-primary-nav { margin-top: var(--space-2); }
.discover-account { position: relative; margin-top: auto; }
.discover-account summary { display: flex; align-items: center; gap: var(--space-3); min-height: 42px; padding: 0 12px; border-radius: var(--radius-sm); color: var(--muted); font-size: var(--fs-sm); cursor: pointer; list-style: none; }
.discover-account summary::-webkit-details-marker { display: none; }
.discover-account summary:hover, .discover-account[open] summary { color: #fff; background: rgba(255,255,255,.04); }
.discover-account summary svg:last-child { width: 14px; margin-left: auto; transition: transform .2s ease; }
.discover-account[open] summary svg:last-child { transform: rotate(180deg); }
.discover-account-popover { position: absolute; right: 0; bottom: calc(100% + 8px); left: 0; display: grid; gap: 3px; padding: 7px; border: 1px solid var(--border); border-radius: var(--radius-md); background: #17171c; box-shadow: 0 16px 38px rgba(0,0,0,.42); }
.discover-account-popover a { min-height: 38px; }
.discover-sidebar.collapsed .discover-brand > span:not(.brand-mark),
.discover-sidebar.collapsed .discover-account span,
.discover-sidebar.collapsed .discover-account summary svg:last-child { display: none; }
.discover-sidebar.collapsed .discover-brand { justify-content: center; padding-inline: 0; }
.discover-sidebar.collapsed .brand-mark { display: none; }
.discover-sidebar.collapsed .discover-account summary { justify-content: center; padding: 0; }
.discover-sidebar.collapsed .discover-account-popover { position: fixed; bottom: 24px; left: 76px; width: 240px; }
.discover-sidebar.collapsed .discover-account-popover a { justify-content: flex-start; gap: var(--space-3); padding: 0 12px; font-size: var(--fs-sm); }
@media (min-width: 641px) and (max-width: 1024px) {
  .discover-sidebar .brand-mark { margin: auto; }
  .discover-sidebar .discover-brand > span:last-child, .discover-sidebar .menu-label, .discover-sidebar .discover-account span, .discover-sidebar .discover-account summary svg:last-child { display: none; }
  .discover-sidebar .discover-account summary { justify-content: center; padding: 0; }
  .discover-account-popover { position: fixed; bottom: 24px; left: 76px; width: 240px; }
  .discover-account-popover a { justify-content: flex-start; gap: var(--space-3); padding: 0 12px; font-size: var(--fs-sm); }
}
</style>
