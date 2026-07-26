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
import { formatDate } from '@/utils/format';
import { CalendarDays } from '@lucide/vue';

defineProps({ events: { type: Array, default: () => [] } });

</script>
