<template>
  <section class="drawer-section timeline">
    <article v-for="event in events || []" :key="`${event.date}:${event.title}:${event.subtitle}`" class="timeline-row">
      <CalendarDays />
      <div><strong>{{ event.title }}</strong><span>{{ event.subtitle }} · {{ formatDate(event.date) }}</span></div>
    </article>
    <p v-if="!events?.length" class="empty">Aucun evenement planifie.</p>
  </section>
</template>

<script setup>
import { CalendarDays } from '@lucide/vue';

defineProps({ events: { type: Array, default: () => [] } });

function formatDate(value) { return value ? new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium' }).format(new Date(value)) : '-'; }
</script>
