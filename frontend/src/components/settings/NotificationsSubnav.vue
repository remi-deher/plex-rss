<template>
  <SubnavBar :items="items" :active="active" aria-label="Sections des notifications" />
</template>

<script setup>
import { computed } from 'vue';
import SubnavBar from '@/components/ui/SubnavBar.vue';
import { notificationSections } from '@/notificationSections';

const props = defineProps({
  active: { type: String, default: 'history' },
  pendingCount: { type: Number, default: null },
});

const items = computed(() => notificationSections.map(section => (
  section.key === 'pending' && props.pendingCount
    ? { ...section, count: props.pendingCount }
    : section
)));
</script>
