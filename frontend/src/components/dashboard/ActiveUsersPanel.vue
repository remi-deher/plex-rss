<template>
  <section class="panel">
    <div class="panel-head">
      <h2>Utilisateurs actifs</h2>
      <RouterLink to="/users" class="panel-link">Gerer</RouterLink>
    </div>
    <article v-for="user in users.slice(0, 6)" :key="user.plex_user_id" class="detail-row">
      <strong>{{ user.display_name }}</strong>
      <span class="badge">{{ user.total }} demande(s)</span>
    </article>
    <p v-if="!users.length" class="empty">Aucune activite.</p>
  </section>
</template>

<script setup>
defineProps({ users: { type: Array, default: () => [] } });
</script>
