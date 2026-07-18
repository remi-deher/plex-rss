<template>
  <section class="panel">
    <div class="panel-head">
      <h2>Demandes a valider</h2>
      <RouterLink to="/library?status=pending_approval" class="panel-link">Tout voir</RouterLink>
    </div>
    <article v-for="row in pending" :key="row.id" class="detail-row">
      <div>
        <strong>{{ row.title }}</strong>
        <span>{{ row.requested_by || row.plex_user || row.plex_user_id }}</span>
      </div>
      <div class="actions">
        <button class="icon-button success" title="Approuver" @click="$emit('action', row, 'approve')">
          <Check />
        </button>
        <button class="icon-button danger" title="Refuser" @click="$emit('action', row, 'reject')">
          <X />
        </button>
      </div>
    </article>
    <p v-if="!pending.length" class="empty">Aucune demande a valider.</p>
  </section>
</template>

<script setup>
import { Check, X } from '@lucide/vue';

defineProps({ pending: { type: Array, default: () => [] } });
defineEmits(['action']);
</script>
