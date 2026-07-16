<template>
  <div class="settings-grid">
    <div class="settings-cards span-two">
      <PlexConnectionCard/>
      <SeerConnectionCard/>
      <TmdbConnectionCard/>
      <ArrInstancesCard/>
      <DownloadClientsCard/>
    </div>
  </div>
</template>
<script setup>
import PlexConnectionCard from './connections/PlexConnectionCard.vue';
import SeerConnectionCard from './connections/SeerConnectionCard.vue';
import TmdbConnectionCard from './connections/TmdbConnectionCard.vue';
import ArrInstancesCard from './connections/ArrInstancesCard.vue';
import DownloadClientsCard from './connections/DownloadClientsCard.vue';
</script>
