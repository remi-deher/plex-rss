<template>
  <aside class="sidebar activity-sidebar desktop-only" :class="{ collapsed }" aria-label="Navigation Activité &amp; Insights" :aria-expanded="!collapsed">
    <div class="brand activity-brand">
      <span class="brand-mark"><Activity /></span>
      <span><strong>Plexarr</strong></span>
      <button class="sidebar-toggle" type="button" :aria-label="collapsed ? 'Afficher le menu' : 'Réduire le menu'" :title="collapsed ? 'Afficher le menu' : 'Réduire le menu'" @click="$emit('toggle')">
        <PanelLeftOpen v-if="collapsed"/><PanelLeftClose v-else/>
      </button>
    </div>

    <div class="menu-section activity-home-nav">
      <RouterLink to="/dashboard" title="Accueil"><House />Accueil</RouterLink>
    </div>

    <div class="menu-section activity-primary-nav">
      <span class="menu-label">Activité &amp; Insights</span>
      <RouterLink to="/activity" active-class="" exact-active-class="router-link-active" title="Vue d’ensemble"><LayoutDashboard />Vue d’ensemble</RouterLink>
      <RouterLink to="/activity?view=live" title="En direct"><Radio />En direct</RouterLink>
      <RouterLink to="/activity?view=history" title="Historique"><History />Historique</RouterLink>
      <RouterLink to="/activity?view=stats" title="Statistiques"><BarChart3 />Statistiques</RouterLink>
      <RouterLink to="/activity?view=quality" title="Qualité des flux"><Gauge />Qualité des flux</RouterLink>
      <RouterLink to="/activity?view=users" title="Utilisateurs"><Users />Utilisateurs</RouterLink>
      <RouterLink to="/analytics" title="Insights médiathèque"><ChartNoAxesCombined />Insights médiathèque</RouterLink>
    </div>

    <details class="activity-account desktop-only">
      <summary><CircleUserRound /><span>Plus</span><ChevronUp /></summary>
      <div class="activity-account-popover">
        <RouterLink to="/profile"><UserRound />Profil</RouterLink>
        <RouterLink to="/discover"><Compass />Application principale</RouterLink>
        <a href="/logout" @click="clearCache"><LogOut />Déconnexion</a>
      </div>
    </details>
  </aside>

  <nav class="mobile-nav-bar mobile-only activity-mobile-nav" aria-label="Navigation Activité &amp; Insights">
    <RouterLink to="/activity" active-class="" exact-active-class="router-link-active" @click="closeMoreMenu"><LayoutDashboard /><span>Vue d’ensemble</span></RouterLink>
    <RouterLink to="/activity?view=live" @click="closeMoreMenu"><Radio /><span>En direct</span></RouterLink>
    <RouterLink to="/activity?view=history" @click="closeMoreMenu"><History /><span>Historique</span></RouterLink>
    <RouterLink to="/analytics" @click="closeMoreMenu"><ChartNoAxesCombined /><span>Insights</span></RouterLink>
    <button ref="moreButtonRef" type="button" class="more-nav-btn" :class="{ active: isMoreOpen }" aria-controls="activity-mobile-more" :aria-expanded="isMoreOpen" @click="toggleMoreMenu">
      <MoreHorizontal /><span>Plus</span>
    </button>
  </nav>

  <Transition name="slide-up">
    <div v-if="isMoreOpen" class="mobile-more-overlay" @click.self="closeMoreMenu">
      <div id="activity-mobile-more" ref="mobileMoreRef" class="mobile-more-sheet" role="dialog" aria-modal="true" aria-labelledby="activity-menu-title" tabindex="-1">
        <div class="sheet-header">
          <h2 id="activity-menu-title">Menu</h2>
          <button type="button" class="close-sheet-btn" aria-label="Fermer le menu" @click="closeMoreMenu"><X /></button>
        </div>
        <div class="sheet-content">
          <div class="menu-section">
            <RouterLink to="/dashboard" @click="closeMoreMenu"><House />Accueil</RouterLink>
          </div>
          <div class="menu-section">
            <span class="menu-label">Activité &amp; Insights</span>
            <RouterLink to="/activity?view=stats" @click="closeMoreMenu"><BarChart3 />Statistiques</RouterLink>
            <RouterLink to="/activity?view=quality" @click="closeMoreMenu"><Gauge />Qualité des flux</RouterLink>
            <RouterLink to="/activity?view=users" @click="closeMoreMenu"><Users />Utilisateurs</RouterLink>
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
import { onUnmounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { Activity, BarChart3, ChartNoAxesCombined, ChevronUp, CircleUserRound, Compass, Gauge, History, House, LayoutDashboard, LogOut, MoreHorizontal, PanelLeftClose, PanelLeftOpen, Radio, UserRound, Users, X } from '@lucide/vue';
import { clearCache } from '@/cache';
import { useModalA11y } from '@/composables/useModalA11y';

defineProps({ collapsed: { type: Boolean, default: false } });
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
.activity-sidebar { background: linear-gradient(180deg, color-mix(in srgb, var(--surface) 88%, #17110a), var(--surface)); }
.activity-brand { align-items: center; }
.activity-brand .sidebar-toggle { margin-left: auto; }
.activity-brand > span:last-child { display: grid; line-height: 1.05; }
.activity-brand strong { font-size: var(--fs-md); }
.brand-mark { display: grid; flex: none; place-items: center; width: 34px; height: 34px; border-radius: 10px; color: #111; background: var(--accent); box-shadow: 0 8px 24px rgba(229,160,13,.18); }
.brand-mark svg { width: 19px; }
.activity-primary-nav { margin-top: var(--space-2); }
.activity-account { position: relative; margin-top: auto; }
.activity-account summary { display: flex; align-items: center; gap: var(--space-3); min-height: 42px; padding: 0 12px; border-radius: var(--radius-sm); color: var(--muted); font-size: var(--fs-sm); cursor: pointer; list-style: none; }
.activity-account summary::-webkit-details-marker { display: none; }
.activity-account summary:hover, .activity-account[open] summary { color: #fff; background: rgba(255,255,255,.04); }
.activity-account summary svg:last-child { width: 14px; margin-left: auto; transition: transform .2s ease; }
.activity-account[open] summary svg:last-child { transform: rotate(180deg); }
.activity-account-popover { position: absolute; right: 0; bottom: calc(100% + 8px); left: 0; display: grid; gap: 3px; padding: 7px; border: 1px solid var(--border); border-radius: var(--radius-md); background: #17171c; box-shadow: 0 16px 38px rgba(0,0,0,.42); }
.activity-account-popover a { min-height: 38px; }
.activity-sidebar.collapsed .activity-brand > span:not(.brand-mark),
.activity-sidebar.collapsed .activity-account span,
.activity-sidebar.collapsed .activity-account summary svg:last-child { display: none; }
.activity-sidebar.collapsed .activity-brand { justify-content: center; padding-inline: 0; }
.activity-sidebar.collapsed .brand-mark { display: none; }
.activity-sidebar.collapsed .activity-account summary { justify-content: center; padding: 0; }
.activity-sidebar.collapsed .activity-account-popover { position: fixed; bottom: 24px; left: 76px; width: 240px; }
.activity-sidebar.collapsed .activity-account-popover a { justify-content: flex-start; gap: var(--space-3); padding: 0 12px; font-size: var(--fs-sm); }
@media (min-width: 641px) and (max-width: 1024px) {
  .activity-sidebar .brand-mark { margin: auto; }
  .activity-sidebar .activity-brand > span:last-child, .activity-sidebar .menu-label, .activity-sidebar .activity-account span, .activity-sidebar .activity-account summary svg:last-child { display: none; }
  .activity-sidebar .activity-account summary { justify-content: center; padding: 0; }
  .activity-account-popover { position: fixed; bottom: 24px; left: 76px; width: 240px; }
  .activity-account-popover a { justify-content: flex-start; gap: var(--space-3); padding: 0 12px; font-size: var(--fs-sm); }
}
</style>
