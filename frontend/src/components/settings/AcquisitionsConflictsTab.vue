<template>
  <div class="settings-merged">
    <AcquisitionsTab/>
    <h2 class="settings-merged-heading">Conflits</h2>
    <ConflictsTab/>
  </div>
</template>
<script setup>
import AcquisitionsTab from './AcquisitionsTab.vue';
import ConflictsTab from './ConflictsTab.vue';
</script>
<style scoped>
.settings-merged-heading { margin: var(--space-2) 0 0; font-size: var(--fs-lg); }
</style>
