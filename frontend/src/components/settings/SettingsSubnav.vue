<template>
  <SubnavBar :items="items" :active="active" aria-label="Sections des paramètres" />
</template>

<script setup>
import { computed } from 'vue';
import SubnavBar from '@/components/ui/SubnavBar.vue';
import { settingsSections } from '@/settingsSections';

defineProps({ active: { type: String, default: 'overview' } });

const items = computed(() => settingsSections.map(section => ({
  ...section,
  to: section.to || { path: '/settings', query: { tab: section.key } },
})));
</script>
