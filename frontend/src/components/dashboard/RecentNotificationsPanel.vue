<template>
  <PanelCard title="Notifications recentes">
    <template #action><RouterLink to="/notifications" class="panel-link">Tout voir</RouterLink></template>
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
  </PanelCard>
</template>

<script setup>
import PanelCard from '@/components/ui/PanelCard.vue';
defineProps({ notifications: { type: Array, default: () => [] } });
</script>
