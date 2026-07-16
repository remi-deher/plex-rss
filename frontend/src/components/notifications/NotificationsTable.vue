<template>
  <section class="panel table-wrap">
    <table>
      <thead>
        <tr>
          <th><input v-if="tab==='pending'" type="checkbox" :checked="allSelected" @change="toggleAll"></th>
          <th>Date</th>
          <th>Evenement</th>
          <th>Media</th>
          <th>Destinataires</th>
          <th>Etat</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.id">
          <td><input v-if="tab==='pending'" v-model="selected" type="checkbox" :value="row.id"></td>
          <td>{{ formatDate(row.sent_at||row.created_at) }}</td>
          <td>
            <strong>{{ row.event_label||row.event }}</strong>
            <small class="table-detail">{{ context(row) }}</small>
          </td>
          <td>{{ row.media_title||'-' }}</td>
          <td>{{ row.recipient||(row.recipients||[]).join(', ')||'-' }}</td>
          <td>
            <span class="badge" :class="row.success===false||row.valid===false?'failed':tab==='pending'?'pending':'available'">
              {{ row.success===false?'Erreur':row.valid===false?'Invalide':tab==='pending'?'En attente':'Envoyee' }}
            </span>
            <small v-if="row.error_msg" class="table-detail error-text">{{ row.error_msg }}</small>
          </td>
          <td>
            <button v-if="tab==='history'&&!row.success" class="icon-button" title="Renvoyer" @click="$emit('resend',row)"><Send/></button>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="!loading&&!rows.length" class="empty">Aucune notification.</p>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue';
import { Send } from '@lucide/vue';

const props = defineProps({
  rows: { type: Array, default: () => [] },
  tab: { type: String, default: 'history' },
  loading: { type: Boolean, default: false },
});
defineEmits(['resend']);

const selected = ref([]);
const allSelected = computed(() => props.rows.length && props.rows.every(x => selected.value.includes(x.id)));

function formatDate(v) {
  return v ? new Intl.DateTimeFormat('fr-FR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(v)) : '-';
}
function context(row) {
  const c = row.context || {};
  return [c.scope, c.language, c.is_upgrade ? 'amelioration' : ''].filter(Boolean).join(' - ') || row.event_description || '';
}
function toggleAll(e) {
  selected.value = e.target.checked ? props.rows.map(x => x.id) : [];
}

defineExpose({ selected });
</script>
