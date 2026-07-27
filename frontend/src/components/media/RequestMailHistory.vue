<template>
  <details class="mail-history-details">
    <summary>Historique</summary>
    <small>{{ row.origin_kind === 'arr' ? 'Detectee le' : 'Demandee le' }} {{ formatDate(row.requested_at) }}</small>
    <small v-if="row.arr_processed_at" class="mail-history">
      Validee par *arr le {{ formatDateTime(row.arr_processed_at) }}
    </small>
    <small v-if="row.last_request_mail" class="mail-history">
      Mail demande {{ formatDateTime(row.last_request_mail.sent_at) }} ({{ triggerLabel(row.last_request_mail) }})
      <span v-if="row.last_request_mail.success === false" class="badge failed tiny">Echec</span>
    </small>
    <small v-if="row.available_at" class="mail-history">
      Disponible le {{ formatDateTime(row.available_at) }}
    </small>
    <small v-if="row.last_available_mail" class="mail-history">
      Mail dispo {{ formatDateTime(row.last_available_mail.sent_at) }} ({{ triggerLabel(row.last_available_mail) }})
      <span v-if="row.last_available_mail.success === false" class="badge failed tiny">Echec</span>
    </small>
    <small v-if="row.vf_tracking_disabled" class="mail-history">Suivi VF arrete</small>
  </details>
</template>

<script setup>
// Chronologie d'une demande : détection/création, validation *arr, emails envoyés.
import { formatDate, formatDateTime } from '@/utils/format';

defineProps({ row: { type: Object, required: true } });

const triggerLabel = mail => (mail.triggered_by === 'manual' ? 'manuel' : 'auto');
</script>
