<template>
  <aside class="sidebar settings-sidebar desktop-only" :class="{ collapsed }" aria-label="Navigation Paramètres" :aria-expanded="!collapsed">
    <div class="brand settings-brand">
      <span class="brand-mark"><Settings /></span>
      <span><strong>Plexarr</strong></span>
      <button class="sidebar-toggle" type="button" :aria-label="collapsed ? 'Afficher le menu' : 'Réduire le menu'" :title="collapsed ? 'Afficher le menu' : 'Réduire le menu'" @click="$emit('toggle')">
        <PanelLeftOpen v-if="collapsed"/><PanelLeftClose v-else/>
      </button>
    </div>

    <div class="menu-section settings-primary-nav">
      <span class="menu-label">Paramètres</span>
      <RouterLink :to="{ path: '/settings', query: { tab: 'overview' } }" title="Vue d’ensemble"><ServerCog/>Vue d’ensemble</RouterLink>
      <details v-for="group in settingsGroups" :key="group.label" :open="group.label === activeGroupLabel">
        <summary>{{ group.label }}</summary>
        <RouterLink v-for="item in group.items" :key="item.key" :to="item.to || { path: '/settings', query: { tab: item.key } }">{{ item.label }}</RouterLink>
      </details>
    </div>

    <details class="settings-account desktop-only">
      <summary><CircleUserRound /><span>Plus</span><ChevronUp /></summary>
      <div class="settings-account-popover">
        <RouterLink to="/profile"><UserRound />Profil</RouterLink>
        <RouterLink to="/users"><Users />Administration</RouterLink>
        <a href="/logout" @click="clearCache"><LogOut />Déconnexion</a>
      </div>
    </details>
  </aside>

  <nav class="mobile-nav-bar mobile-only settings-mobile-nav" aria-label="Navigation Paramètres">
    <RouterLink :to="{ path: '/settings', query: { tab: 'overview' } }" @click="closeMoreMenu"><ServerCog/><span>Vue d’ensemble</span></RouterLink>
    <button ref="moreButtonRef" type="button" class="more-nav-btn" :class="{ active: isMoreOpen }" aria-controls="settings-mobile-more" :aria-expanded="isMoreOpen" @click="toggleMoreMenu">
      <MoreHorizontal /><span>Plus</span>
    </button>
  </nav>

  <Transition name="slide-up">
    <div v-if="isMoreOpen" class="mobile-more-overlay" @click.self="closeMoreMenu">
      <div id="settings-mobile-more" ref="mobileMoreRef" class="mobile-more-sheet" role="dialog" aria-modal="true" aria-labelledby="settings-menu-title" tabindex="-1">
        <div class="sheet-header">
          <h2 id="settings-menu-title">Paramètres</h2>
          <button type="button" class="close-sheet-btn" aria-label="Fermer le menu" @click="closeMoreMenu"><X /></button>
        </div>
        <div class="sheet-content">
          <div class="menu-section">
            <details v-for="group in settingsGroups" :key="group.label" :open="group.label === activeGroupLabel">
              <summary>{{ group.label }}</summary>
              <RouterLink v-for="item in group.items" :key="item.key" :to="item.to || { path: '/settings', query: { tab: item.key } }" @click="closeMoreMenu">{{ item.label }}</RouterLink>
            </details>
          </div>
          <div class="menu-section">
            <span class="menu-label">Compte</span>
            <RouterLink to="/profile" @click="closeMoreMenu"><UserRound />Profil</RouterLink>
            <RouterLink to="/users" @click="closeMoreMenu"><Users />Administration</RouterLink>
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
import { ChevronUp, CircleUserRound, LogOut, MoreHorizontal, PanelLeftClose, PanelLeftOpen, ServerCog, Settings, UserRound, Users, X } from '@lucide/vue';
import { clearCache } from '@/cache';
import { useModalA11y } from '@/composables/useModalA11y';
import { settingsSections } from '@/settingsSections';

defineProps({ collapsed: { type: Boolean, default: false } });
defineEmits(['toggle']);

const route = useRoute();
const isMoreOpen = ref(false);
const mobileMoreRef = ref(null);
const moreButtonRef = ref(null);

// Regroupe les sections (hors "Vue d'ensemble", affichee a part) par leur
// champ `group`, en preservant l'ordre de settingsSections.js.
const settingsGroups = computed(() => {
  const groups = [];
  for (const item of settingsSections) {
    if (!item.group) continue;
    let group = groups.find(g => g.label === item.group);
    if (!group) { group = { label: item.group, items: [] }; groups.push(group); }
    group.items.push(item);
  }
  return groups;
});
const activeGroupLabel = computed(() => {
  const active = settingsSections.find(item => (item.to ? route.path === item.to : route.path === '/settings' && route.query.tab === item.key));
  return active?.group || '';
});

function toggleMoreMenu() { isMoreOpen.value = !isMoreOpen.value; }
function closeMoreMenu() { isMoreOpen.value = false; }

watch(() => route.fullPath, closeMoreMenu);
watch(isMoreOpen, open => document.body.classList.toggle('modal-open', open));
useModalA11y(mobileMoreRef, isMoreOpen, closeMoreMenu);
onUnmounted(() => document.body.classList.remove('modal-open'));
</script>

<style scoped>
.settings-sidebar { background: linear-gradient(180deg, color-mix(in srgb, var(--surface) 88%, #17110a), var(--surface)); }
.settings-brand { align-items: center; }
.settings-brand .sidebar-toggle { margin-left: auto; }
.settings-brand > span:last-child { display: grid; line-height: 1.05; }
.settings-brand strong { font-size: var(--fs-md); }
.brand-mark { display: grid; flex: none; place-items: center; width: 34px; height: 34px; border-radius: 10px; color: #111; background: var(--accent); box-shadow: 0 8px 24px rgba(229,160,13,.18); }
.brand-mark svg { width: 19px; }
.settings-primary-nav { margin-top: var(--space-2); }
.settings-primary-nav details { display: grid; gap: var(--space-1); margin-top: var(--space-1); }
.settings-primary-nav summary { min-height: 34px; padding: 6px 12px; color: color-mix(in srgb, var(--muted) 75%, white); font-size: var(--fs-xs); font-weight: 700; text-transform: uppercase; letter-spacing: .04em; cursor: pointer; list-style: none; }
.settings-primary-nav summary::-webkit-details-marker { display: none; }
.settings-primary-nav details a { margin-left: 10px; }
.settings-account { position: relative; margin-top: auto; }
.settings-account summary { display: flex; align-items: center; gap: var(--space-3); min-height: 42px; padding: 0 12px; border-radius: var(--radius-sm); color: var(--muted); font-size: var(--fs-sm); cursor: pointer; list-style: none; }
.settings-account summary::-webkit-details-marker { display: none; }
.settings-account summary:hover, .settings-account[open] summary { color: #fff; background: rgba(255,255,255,.04); }
.settings-account summary svg:last-child { width: 14px; margin-left: auto; transition: transform .2s ease; }
.settings-account[open] summary svg:last-child { transform: rotate(180deg); }
.settings-account-popover { position: absolute; right: 0; bottom: calc(100% + 8px); left: 0; display: grid; gap: 3px; padding: 7px; border: 1px solid var(--border); border-radius: var(--radius-md); background: #17171c; box-shadow: 0 16px 38px rgba(0,0,0,.42); }
.settings-account-popover a { min-height: 38px; }
.settings-sidebar.collapsed .settings-brand > span:not(.brand-mark),
.settings-sidebar.collapsed .settings-account span,
.settings-sidebar.collapsed .settings-account summary svg:last-child,
.settings-sidebar.collapsed .settings-primary-nav .menu-label,
.settings-sidebar.collapsed .settings-primary-nav details { display: none; }
.settings-sidebar.collapsed .settings-brand { justify-content: center; padding-inline: 0; }
.settings-sidebar.collapsed .brand-mark { display: none; }
.settings-sidebar.collapsed .settings-account summary { justify-content: center; padding: 0; }
.settings-sidebar.collapsed .settings-account-popover { position: fixed; bottom: 24px; left: 76px; width: 240px; }
.settings-sidebar.collapsed .settings-account-popover a { justify-content: flex-start; gap: var(--space-3); padding: 0 12px; font-size: var(--fs-sm); }
@media (min-width: 641px) and (max-width: 1024px) {
  .settings-sidebar .brand-mark { margin: auto; }
  .settings-sidebar .settings-brand > span:last-child, .settings-sidebar .menu-label, .settings-sidebar .settings-account span, .settings-sidebar .settings-account summary svg:last-child { display: none; }
  .settings-sidebar .settings-account summary { justify-content: center; padding: 0; }
  .settings-account-popover { position: fixed; bottom: 24px; left: 76px; width: 240px; }
  .settings-account-popover a { justify-content: flex-start; gap: var(--space-3); padding: 0 12px; font-size: var(--fs-sm); }
}
</style>
