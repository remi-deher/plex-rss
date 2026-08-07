<template>
  <div class="settings-merged">
    <ScheduledTasksTab/>
    <h2 class="settings-merged-heading">Maintenance</h2>
    <MaintenanceTab/>
  </div>
</template>
<script setup>
import ScheduledTasksTab from './ScheduledTasksTab.vue';
import MaintenanceTab from './MaintenanceTab.vue';
</script>
<style scoped>
.settings-merged-heading { margin: var(--space-2) 0 0; font-size: var(--fs-lg); }
</style>
