<template>
  <SubnavBar :items="items" :active="modelValue" aria-label="Sections de l’activité Plex" />
</template>

<script setup>
import { BarChart3, CircleUserRound, Gauge, History, Radio, SlidersHorizontal } from '@lucide/vue';
import { computed } from 'vue';
import SubnavBar from '@/components/ui/SubnavBar.vue';

const props = defineProps({
  modelValue: { type: String, default: 'overview' },
  liveCount: { type: Number, default: 0 },
});

const items = computed(() => [
  { key: 'overview', label: 'Vue d’ensemble', icon: Gauge, to: { path: '/activity', query: {} } },
  { key: 'live', label: 'En direct', icon: Radio, count: props.liveCount, to: { path: '/activity', query: { view: 'live' } } },
  { key: 'history', label: 'Historique', icon: History, to: { path: '/activity', query: { view: 'history' } } },
  { key: 'stats', label: 'Statistiques', icon: BarChart3, to: { path: '/activity', query: { view: 'stats' } } },
  { key: 'quality', label: 'Qualité', icon: SlidersHorizontal, to: { path: '/activity', query: { view: 'quality' } } },
  { key: 'users', label: 'Utilisateurs', icon: CircleUserRound, to: { path: '/activity', query: { view: 'users' } } },
]);
</script>
