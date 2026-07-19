<template>
  <section class="panel">
    <div class="panel-head">
      <h2>Notifications recentes</h2>
      <RouterLink to="/notifications" class="panel-link">Tout voir</RouterLink>
    </div>
    <article v-for="notif in notifications" :key="notif.id" class="detail-row">
      <div>
        <strong>{{ notif.media_title || '—' }}</strong>
        <span>{{ notif.event_label }} · {{ notif.recipient }}</span>
      </div>
      <span class="badge" :class="notif.success ? 'available' : 'failed'">
        {{ notif.success ? 'Envoyé' : 'Erreur' }}
      </span>
    </article>
    <p v-if="!notifications.length" class="empty">Aucune notification envoyee.</p>
  </section>
</template>

<script setup>
defineProps({ notifications: { type: Array, default: () => [] } });
</script>
