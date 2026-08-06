<template>
  <section class="panel table-wrap table-cards rich">
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
          <td class="card-select"><input v-if="tab==='pending'" v-model="selected" type="checkbox" :value="row.id"></td>
          <td data-label="Date">{{ formatDate(row.sent_at||row.created_at) }}</td>
          <td class="card-title">
            <strong>{{ row.event_label||row.event }}</strong>
            <small class="table-detail">{{ context(row) }}</small>
          </td>
          <td data-label="Media">{{ row.media_title||'-' }}</td>
          <td data-label="Destinataires">{{ row.recipient||(row.recipients||[]).join(', ')||'-' }}</td>
          <td data-label="Etat">
            <span class="badge" :class="row.success===false||row.valid===false?'failed':tab==='pending'?'pending':'available'">
              {{ row.success===false?'Erreur':row.valid===false?'Invalide':tab==='pending'?'En attente':'Envoyee' }}
            </span>
            <small v-if="row.error_msg" class="table-detail error-text">{{ row.error_msg }}</small>
          </td>
          <td class="card-actions">
            <button v-if="tab==='history'" class="icon-button" title="Voir l'email" aria-label="Voir l'email" @click="$emit('preview',row)"><Eye/></button>
            <button v-if="tab==='history'&&!row.success" class="icon-button" title="Renvoyer" aria-label="Renvoyer" @click="$emit('resend',row)"><Send/></button>
            <button v-if="tab==='pending'" class="icon-button" title="Marquer comme traitee (sans envoyer)" aria-label="Marquer comme traitee" @click="$emit('markHandled',row)"><CheckCheck/></button>
            <button v-if="tab==='pending'" class="icon-button danger" title="Supprimer" aria-label="Supprimer" @click="$emit('deleteOne',row)"><Trash2/></button>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="!loading&&!rows.length" class="empty">Aucune notification.</p>
  </section>
</template>

<script setup>
import { formatDateTimeShort as formatDate } from '@/utils/format';
import { computed, ref } from 'vue';
import { CheckCheck, Eye, Send, Trash2 } from '@lucide/vue';

const props = defineProps({
  rows: { type: Array, default: () => [] },
  tab: { type: String, default: 'history' },
  loading: { type: Boolean, default: false },
});
defineEmits(['resend', 'markHandled', 'deleteOne', 'preview']);

const selected = ref([]);
const allSelected = computed(() => props.rows.length && props.rows.every(x => selected.value.includes(x.id)));

const SCOPE_LABELS = {
  episode: 'Épisode',
  season_start: 'Début de saison',
  season_complete: 'Saison complète',
  series_complete: 'Série complète',
  movie: 'Film',
};

function context(row) {
  const scope = row.scope, season = row.season_number, episode = row.episode_number;
  const parts = [];
  if (scope === 'episode' && season && episode) parts.push(`S${season}E${episode}`);
  else if (scope && (season || scope !== 'movie')) parts.push(season ? `${SCOPE_LABELS[scope] || scope} ${season}` : (SCOPE_LABELS[scope] || scope));
  if (row.language) parts.push(row.language.toUpperCase());
  if (row.is_upgrade) parts.push('amélioration');
  if (parts.length) return parts.join(' · ');
  const c = row.context || {};
  return [c.scope, c.language, c.is_upgrade ? 'amelioration' : ''].filter(Boolean).join(' - ') || row.event_description || '';
}
function toggleAll(e) {
  selected.value = e.target.checked ? props.rows.map(x => x.id) : [];
}

defineExpose({ selected });
</script>
