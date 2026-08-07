<template>
  <aside class="sidebar settings-sidebar desktop-only" :class="{ collapsed }" aria-label="Navigation Paramètres" :aria-expanded="!collapsed">
    <div class="brand settings-brand">
      <span class="brand-mark"><Settings /></span>
      <span><strong>Plexarr</strong></span>
      <button class="sidebar-toggle" type="button" :aria-label="collapsed ? 'Afficher le menu' : 'Réduire le menu'" :title="collapsed ? 'Afficher le menu' : 'Réduire le menu'" @click="$emit('toggle')">
        <PanelLeftOpen v-if="collapsed"/><PanelLeftClose v-else/>
      </button>
    </div>

    <!-- Home Link -->
    <div class="menu-section settings-home-nav">
      <RouterLink to="/dashboard" title="Accueil"><House /><span>Accueil</span></RouterLink>
    </div>

    <!-- Mode A: Main Overview & Categories List (when at /settings root) -->
    <template v-if="isGlobalOverview">
      <div class="menu-section settings-global-nav">
        <span class="menu-label">Paramètres</span>
        <RouterLink
          :to="{ path: '/settings', query: { tab: 'overview' } }"
          class="router-link-active"
          title="Vue d’ensemble"
        >
          <ServerCog />
          <span>Vue d’ensemble</span>
        </RouterLink>
      </div>

      <div class="menu-section settings-categories-nav">
        <span class="menu-label">Catégories</span>
        <RouterLink
          v-for="group in settingsGroups"
          :key="group.label"
          :to="getItemRoute(group.items[0])"
          :title="group.label"
        >
          <component :is="group.items[0].icon" />
          <span>{{ group.label }}</span>
        </RouterLink>
      </div>
    </template>

    <!-- Mode B: Inside a Group Context -->
    <template v-else>
      <!-- Return Button to main /settings -->
      <div class="menu-section settings-back-nav">
        <RouterLink
          :to="{ path: '/settings', query: { tab: 'overview' } }"
          class="back-settings-link"
          title="Retour aux paramètres"
        >
          <ArrowLeft />
          <span>Paramètres</span>
        </RouterLink>
      </div>

      <!-- Group Sub-entries ONLY -->
      <div class="menu-section settings-primary-nav">
        <span class="menu-label">{{ activeGroupLabel }}</span>
        <RouterLink
          v-for="item in activeGroupItems"
          :key="item.key"
          :to="getItemRoute(item)"
          :class="{ 'router-link-active': isItemActive(item) }"
          :title="item.label"
        >
          <component :is="item.icon" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </div>
    </template>

    <details class="settings-account desktop-only">
      <summary><CircleUserRound /><span>Plus</span><ChevronUp /></summary>
      <div class="settings-account-popover">
        <RouterLink to="/profile"><UserRound />Profil</RouterLink>
        <RouterLink to="/users"><Users />Administration</RouterLink>
        <a href="/logout" @click="clearCache"><LogOut />Déconnexion</a>
      </div>
    </details>
  </aside>

  <!-- Mobile Navigation Bar -->
  <nav class="mobile-nav-bar mobile-only settings-mobile-nav" aria-label="Navigation Paramètres">
    <!-- Mode A: Global Overview (at root /settings) -->
    <template v-if="isGlobalOverview">
      <RouterLink
        :to="{ path: '/settings', query: { tab: 'overview' } }"
        class="router-link-active"
        @click="closeMoreMenu"
      >
        <ServerCog />
        <span>Aperçu</span>
      </RouterLink>
      <RouterLink
        v-for="group in settingsGroups"
        :key="group.label"
        :to="getItemRoute(group.items[0])"
        @click="closeMoreMenu"
      >
        <component :is="group.items[0].icon" />
        <span>{{ group.label === 'Bibliothèque & acquisition' ? 'Bibliothèque' : group.label }}</span>
      </RouterLink>
    </template>

    <!-- Mode B: Inside a Group Context -->
    <template v-else>
      <RouterLink
        :to="{ path: '/settings', query: { tab: 'overview' } }"
        @click="closeMoreMenu"
      >
        <ArrowLeft />
        <span>Retour</span>
      </RouterLink>
      <RouterLink
        v-for="item in activeGroupItems"
        :key="item.key"
        :to="getItemRoute(item)"
        :class="{ 'router-link-active': isItemActive(item) }"
        @click="closeMoreMenu"
      >
        <component :is="item.icon" />
        <span>{{ item.mobileLabel || item.label }}</span>
      </RouterLink>
    </template>

    <button ref="moreButtonRef" type="button" class="more-nav-btn" :class="{ active: isMoreOpen }" aria-controls="settings-mobile-more" :aria-expanded="isMoreOpen" @click="toggleMoreMenu">
      <MoreHorizontal /><span>Plus</span>
    </button>
  </nav>

  <Transition name="slide-up">
    <div v-if="isMoreOpen" class="mobile-more-overlay" @click.self="closeMoreMenu">
      <div id="settings-mobile-more" ref="mobileMoreRef" class="mobile-more-sheet" role="dialog" aria-modal="true" aria-labelledby="settings-menu-title" tabindex="-1">
        <div class="sheet-header">
          <h2 id="settings-menu-title">Menu</h2>
          <button type="button" class="close-sheet-btn" aria-label="Fermer le menu" @click="closeMoreMenu"><X /></button>
        </div>
        <div class="sheet-content">
          <div class="menu-section">
            <RouterLink to="/dashboard" @click="closeMoreMenu"><House /><span>Accueil</span></RouterLink>
          </div>
          <div class="menu-section">
            <span class="menu-label">Compte</span>
            <RouterLink to="/profile" @click="closeMoreMenu"><UserRound /><span>Profil</span></RouterLink>
            <RouterLink to="/users" @click="closeMoreMenu"><Users /><span>Administration</span></RouterLink>
            <a href="/logout" @click="clearCache"><LogOut /><span>Déconnexion</span></a>
          </div>
        </div>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { ArrowLeft, ChevronUp, CircleUserRound, House, LogOut, MoreHorizontal, PanelLeftClose, PanelLeftOpen, ServerCog, Settings, UserRound, Users, X } from '@lucide/vue';
import { clearCache } from '@/cache';
import { useModalA11y } from '@/composables/useModalA11y';
import { settingsSections } from '@/settingsSections';

defineProps({ collapsed: { type: Boolean, default: false } });
defineEmits(['toggle']);

const route = useRoute();
const isMoreOpen = ref(false);
const mobileMoreRef = ref(null);
const moreButtonRef = ref(null);

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

const isGlobalOverview = computed(() => {
  return route.path === '/settings' && (!route.query.tab || route.query.tab === 'overview');
});

const activeItem = computed(() => {
  return settingsSections.find(item => {
    if (item.to) {
      if (typeof item.to === 'string') return route.path === item.to || route.path.startsWith(item.to);
      if (item.to.path) return route.path === item.to.path && (item.to.query?.tab ? route.query.tab === item.to.query.tab : true);
    }
    const currentTab = route.query.tab || 'overview';
    return route.path === '/settings' && currentTab === item.key;
  }) || settingsSections[0];
});

const activeGroupLabel = computed(() => {
  if (isGlobalOverview.value) return '';
  return activeItem.value?.group || 'Services';
});

const activeGroupItems = computed(() => {
  if (!activeGroupLabel.value) return [];
  return settingsSections.filter(item => item.group === activeGroupLabel.value);
});

function getItemRoute(item) {
  if (item.to) return item.to;
  return { path: '/settings', query: { tab: item.key } };
}

function isItemActive(item) {
  if (item.to) {
    if (typeof item.to === 'string') return route.path === item.to;
    if (item.to.path) return route.path === item.to.path && route.query.tab === item.to.query?.tab;
  }
  const currentTab = route.query.tab || 'overview';
  return route.path === '/settings' && currentTab === item.key;
}

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

.settings-home-nav { margin-top: var(--space-2); }
.settings-global-nav { margin-top: var(--space-2); }
.settings-categories-nav { margin-top: var(--space-3); }
.settings-back-nav { margin-top: var(--space-2); }
.settings-primary-nav { margin-top: var(--space-2); }

.back-settings-link {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  color: var(--muted);
  font-size: var(--fs-sm);
  font-weight: 600;
  transition: color 0.15s ease, background 0.15s ease;
}
.back-settings-link:hover {
  color: var(--text);
  background: rgba(255, 255, 255, 0.04);
}

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
.settings-sidebar.collapsed .menu-label,
.settings-sidebar.collapsed .settings-home-nav a span,
.settings-sidebar.collapsed .settings-global-nav a span,
.settings-sidebar.collapsed .settings-categories-nav a span,
.settings-sidebar.collapsed .settings-back-nav a span,
.settings-sidebar.collapsed .settings-primary-nav a span { display: none; }
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
