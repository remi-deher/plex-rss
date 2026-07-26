<template>
  <PanelCard title="Utilisateurs actifs" :empty="users.length ? '' : 'Aucune activite.'">
    <template #action><RouterLink to="/users" class="panel-link">Gerer</RouterLink></template>
    <article v-for="user in users.slice(0, 6)" :key="user.plex_user_id" class="detail-row">
      <strong>{{ user.display_name }}</strong>
      <span class="badge">{{ user.total }} demande(s)</span>
    </article>
  </PanelCard>
</template>

<script setup>
import PanelCard from '@/components/ui/PanelCard.vue';
defineProps({ users: { type: Array, default: () => [] } });
</script>
