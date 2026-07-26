<template>
  <nav class="activity-subnav" aria-label="Sections de l’activité Plex">
    <RouterLink
      v-for="item in items"
      :key="item.key"
      :to="{ path: '/activity', query: item.key === 'overview' ? {} : { view: item.key } }"
      :class="{ active: modelValue === item.key }"
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
.activity-subnav{display:flex;gap:5px;margin:0 0 16px;padding:5px;overflow-x:auto;border:1px solid var(--border);border-radius:12px;background:var(--surface);scrollbar-width:none}.activity-subnav::-webkit-scrollbar{display:none}.activity-subnav a{display:flex;align-items:center;gap:7px;min-height:38px;padding:7px 11px;border-radius:8px;color:var(--muted);font-size:12px;font-weight:650;text-decoration:none;white-space:nowrap}.activity-subnav a:hover{color:var(--text);background:rgba(255,255,255,.04)}.activity-subnav a.active{color:var(--text);background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--border)}.activity-subnav svg{width:15px}.activity-subnav a.active svg{color:var(--accent)}.activity-subnav small{display:grid;place-items:center;min-width:19px;height:19px;padding:0 5px;border-radius:99px;background:rgba(229,160,13,.15);color:var(--accent);font-size:9px}@media(max-width:640px){.activity-subnav{margin-inline:-2px}.activity-subnav a{padding-inline:10px}.activity-subnav svg{display:none}}
</style>
