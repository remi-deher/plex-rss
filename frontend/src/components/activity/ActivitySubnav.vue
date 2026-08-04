<template>
  <nav class="activity-subnav" aria-label="Sections de l’activité Plex">
    <RouterLink
      v-for="item in items"
      :key="item.key"
      :to="{ path: '/activity', query: item.key === 'overview' ? {} : { view: item.key } }"
      :class="{ active: modelValue === item.key }"
      :aria-current="modelValue === item.key ? 'page' : undefined"
    >
      <component :is="item.icon" />
      <span>{{ item.label }}</span>
      <small v-if="item.count != null">{{ item.count }}</small>
    </RouterLink>
  </nav>
</template>

<script setup>
import { BarChart3, CircleUserRound, Gauge, History, Radio, SlidersHorizontal } from '@lucide/vue';
import { computed } from 'vue';

const props=defineProps({
  modelValue: { type: String, default: 'overview' },
  liveCount: { type: Number, default: 0 },
});

const items = computed(()=>[
  { key: 'overview', label: 'Vue d’ensemble', icon: Gauge },
  { key: 'live', label: 'En direct', icon: Radio, count: props.liveCount },
  { key: 'history', label: 'Historique', icon: History },
  { key: 'stats', label: 'Statistiques', icon: BarChart3 },
  { key: 'quality', label: 'Qualité', icon: SlidersHorizontal },
  { key: 'users', label: 'Utilisateurs', icon: CircleUserRound },
]);
</script>

<style scoped>
.activity-subnav{display:flex;gap: var(--space-1);margin:0 0 16px;padding:5px;overflow-x:auto;border:1px solid var(--border);border-radius:var(--radius-md);background:var(--surface);scrollbar-width:none;scroll-snap-type:x proximity;overscroll-behavior-x:contain}.activity-subnav::-webkit-scrollbar{display:none}.activity-subnav a{display:flex;align-items:center;gap: var(--space-2);min-height:44px;padding:7px 11px;border-radius:var(--radius-sm);color:var(--muted);font-size:var(--fs-sm);font-weight:650;text-decoration:none;white-space:nowrap;scroll-snap-align:start}.activity-subnav a:hover{color:var(--text);background:rgba(255,255,255,.04)}.activity-subnav a.active{color:var(--text);background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--border)}.activity-subnav svg{width:15px}.activity-subnav a.active svg{color:var(--accent)}.activity-subnav small{display:grid;place-items:center;min-width:19px;height:19px;padding:0 5px;border-radius:var(--radius-pill);background:rgba(229,160,13,.15);color:var(--accent);font-size:var(--fs-xs)}@media(max-width:640px){.activity-subnav{margin-inline:-2px}.activity-subnav a{padding-inline:10px}.activity-subnav svg{display:none}}
</style>
