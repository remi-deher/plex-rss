<template>
  <section class="drawer-section">
    <div v-if="admin" class="add-requester-row">
      <span class="add-requester-label">Co-demandeur</span>
      <div class="inline-row compact">
        <select :value="newRequesterId" :disabled="!addableUsers.length" @change="$emit('update:newRequesterId', $event.target.value)">
          <option value="">{{ addableUsers.length ? 'Sélectionnez un utilisateur' : 'Tous les utilisateurs sont déjà demandeurs' }}</option>
          <option v-for="u in addableUsers" :key="u.plex_user_id" :value="u.plex_user_id">{{ u.custom_name || u.display_name || u.plex_user_id }}</option>
        </select>
        <button class="primary" :disabled="busy || !newRequesterId" @click="$emit('add-requester')"><PlusCircle/> Ajouter</button>
      </div>
    </div>
    <article v-for="row in requests || []" :key="row.id" class="detail-row request-detail-row">
      <div>
        <div class="request-detail-top">
          <strong>{{ row.requested_by || row.plex_user || row.plex_user_id }}</strong>
          <span class="badge status-tag" :class="row.status">{{ requestStatusLabel(row.status) }}</span>
        </div>

        <div class="origin-line">
          <span class="badge tiny">{{ row.origin_label || 'Demande utilisateur' }}</span>
          <small>{{ row.operational_status_label }}</small>
        </div>
        <p v-if="row.waiting_reason" class="waiting-reason">{{ row.waiting_reason }}</p>

        <div v-if="!['failed','rejected'].includes(row.status)" class="status-stepper">
          <span v-for="step in statusSteps(row)" :key="step.key" :class="['step', stepState(row, step.key)]">{{ step.label }}</span>
        </div>

        <details v-if="row.media_type === 'show' && row.seasons?.length" class="mail-history-details">
          <summary>Detail par saison ({{ seasonsSummary(row.seasons) }})</summary>
          <div v-for="season in row.seasons" :key="season.season_number" class="inline-row compact" style="justify-content: space-between; margin-bottom: 4px;">
            <span>Saison {{ season.season_number }}</span>
            <span class="badge" :class="season.status">{{ season.episodes_available_count }}/{{ season.episodes_total_count }}</span>
          </div>
        </details>

        <details class="mail-history-details">
          <summary>Historique</summary>
          <small>{{ row.origin_kind === 'arr' ? 'Detectee le' : 'Demandee le' }} {{ formatDate(row.requested_at) }}</small>
          <small v-if="row.arr_processed_at" class="mail-history">
            Validee par *arr le {{ formatDateTime(row.arr_processed_at) }}
          </small>
          <small v-if="row.last_request_mail" class="mail-history">
            Mail demande {{ formatDateTime(row.last_request_mail.sent_at) }} ({{ row.last_request_mail.triggered_by === 'manual' ? 'manuel' : 'auto' }})
            <span v-if="row.last_request_mail.success === false" class="badge failed tiny">Echec</span>
          </small>
          <small v-if="row.available_at" class="mail-history">
            Disponible le {{ formatDateTime(row.available_at) }}
          </small>
          <small v-if="row.last_available_mail" class="mail-history">
            Mail dispo {{ formatDateTime(row.last_available_mail.sent_at) }} ({{ row.last_available_mail.triggered_by === 'manual' ? 'manuel' : 'auto' }})
            <span v-if="row.last_available_mail.success === false" class="badge failed tiny">Echec</span>
          </small>
          <small v-if="row.vf_tracking_disabled" class="mail-history">Suivi VF arrete</small>
        </details>

        <div v-if="(row.requester_ids || []).length > 1" class="requester-breakdown">
          <div v-for="(uid, idx) in row.requester_ids" :key="`${uid}-${idx}`" class="requester-line">
            <span class="requester-name">
              {{ row.requesters?.[idx] || uid }}
              <span v-if="idx === 0" class="badge tiny">Principal</span>
              <span
                v-if="notifiedStatus(row, uid) !== null"
                :class="['notif-dot', notifiedStatus(row, uid) ? 'ok' : 'pending']"
                :title="notifiedStatus(row, uid) ? 'Deja notifie' : 'Pas encore notifie'"
              ></span>
            </span>
            <div v-if="admin" class="requester-menu-wrap">
              <button class="icon-button" title="Actions" @click.stop="toggleRequesterMenu(row.id, uid)"><MoreVertical /></button>
              <div v-if="openRequesterMenu === `${row.id}:${uid}`" class="requester-menu" @click.stop>
                <button :disabled="busy" @click="$emit('notify-user', row.id, uid, ['request']); closeRequesterMenu()"><Mail /> Renvoyer mail demande</button>
                <button v-if="row.status === 'available'" :disabled="busy" @click="$emit('notify-user', row.id, uid, ['available']); closeRequesterMenu()"><MailCheck /> Renvoyer mail dispo</button>
                <button v-if="idx !== 0" :disabled="busy" @click="$emit('promote-requester', row, uid); closeRequesterMenu()"><Crown /> Promouvoir principal</button>
                <button class="danger" :disabled="busy" @click="$emit('remove-requester', row, uid); closeRequesterMenu()"><UserMinus /> Retirer</button>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="actions">
        <button v-if="row.status === 'pending_approval' && admin" class="icon-button success" title="Approuver" :disabled="busy" @click="$emit('approve', row.id)"><Check /></button>
        <button v-if="row.status === 'pending_approval' && admin" class="icon-button danger" title="Refuser" :disabled="busy" @click="$emit('reject', row)"><Ban /></button>
        <button v-if="row.arr_id" class="icon-button" title="Rechercher une release" @click="$emit('open-release', row.id)"><Search /></button>
        <button v-if="row.status === 'failed'" class="icon-button" title="Relancer" @click="$emit('retry', row.id)"><RotateCcw /></button>
        <button v-if="admin && hasUnnotified(row)" class="icon-button" title="Rattraper tout le monde (notifier les demandeurs pas encore prevenus)" :disabled="busy" @click="$emit('catch-up-all', row)"><Users /></button>
        <button class="icon-button" :title="(row.requester_ids || []).length > 1 ? 'Renvoyer le mail de demande a tous' : 'Renvoyer email de demande'" :disabled="busy" @click="$emit('resend-mail', row.id, 'request')"><Mail /></button>
        <button v-if="row.status === 'available'" class="icon-button" :title="(row.requester_ids || []).length > 1 ? 'Renvoyer le mail de disponibilite a tous' : 'Renvoyer email de disponibilite'" :disabled="busy" @click="$emit('resend-mail', row.id, 'available')"><MailCheck /></button>
        <button v-if="canClose(row)" class="icon-button" title="Cloturer la demande" :disabled="busy" @click="$emit('close-request', row)"><CheckCheck /></button>
        <button class="icon-button danger" title="Supprimer" @click="$emit('delete-request', row.id)"><Trash2 /></button>
      </div>
    </article>
    <article v-if="!requests?.length && detail?.in_library" class="detail-row plex-origin-card">
      <div>
        <strong>Disponible directement dans Plex</strong>
        <p>Ce media ne possede aucune demande utilisateur liee. Son point d'entree operationnel est Plex.</p>
        <div class="status-stepper">
          <span class="step done">Detecte dans Plex</span>
          <span class="step current">Disponible</span>
        </div>
      </div>
    </article>
    <p v-else-if="!requests?.length" class="empty">Aucune demande liee.</p>
  </section>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue';
import { Ban, Check, CheckCheck, Crown, Mail, MailCheck, MoreVertical, PlusCircle, RotateCcw, Search, Trash2, UserMinus, Users } from '@lucide/vue';

defineProps({
  requests: { type: Array, default: () => [] },
  detail: { type: Object, default: () => ({}) },
  admin: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
  addableUsers: { type: Array, default: () => [] },
  newRequesterId: { type: String, default: '' },
});
defineEmits([
  'update:newRequesterId', 'add-requester', 'open-release', 'retry', 'catch-up-all',
  'resend-mail', 'close-request', 'delete-request', 'notify-user', 'promote-requester', 'remove-requester',
  'approve', 'reject',
]);

const openRequesterMenu = ref(null);
const requestSteps = [
  { key: 'requested', label: 'Demandee' }, { key: 'submitted', label: 'Transmise a *ARR' },
  { key: 'queued', label: 'En file' }, { key: 'downloading', label: 'Telechargement' },
  { key: 'importing', label: 'Import *ARR' }, { key: 'awaiting_plex', label: 'Attente Plex' },
  { key: 'completed', label: 'Disponible' },
];
const arrSteps = [
  { key: 'submitted', label: 'Detectee dans *ARR' }, { key: 'queued', label: 'En file' },
  { key: 'downloading', label: 'Telechargement' }, { key: 'importing', label: 'Import *ARR' },
  { key: 'awaiting_plex', label: 'Attente Plex' }, { key: 'completed', label: 'Disponible' },
];

function formatDate(value) { return value ? new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium' }).format(new Date(value)) : '-'; }
function formatDateTime(value) { return value ? new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '-'; }
function requestStatusLabel(value) {
  return ({
    pending_approval: 'A approuver',
    pending: 'En attente',
    sent_to_arr: 'Transmise',
    partially_available: 'Partiellement disponible',
    available: 'Disponible',
    failed: 'Erreur',
    rejected: 'Refusee',
  })[value] || value;
}
function seasonsSummary(seasons) {
  const available = seasons.filter(s => s.status === 'available').length;
  return `${available}/${seasons.length} completes`;
}
function statusSteps(row) { return row.origin_kind === 'arr' ? arrSteps : requestSteps; }
function stepState(row, key) {
  const steps = statusSteps(row);
  const order = steps.map(step => step.key);
  let current = row.operational_status || 'not_submitted';
  if (['not_submitted', 'awaiting_submission'].includes(current)) current = 'requested';
  if (current === 'partially_available') current = 'completed';
  if (row.origin_kind === 'arr' && current === 'requested') current = 'submitted';
  const statusIndex = Math.max(0, order.indexOf(current));
  const keyIndex = order.indexOf(key);
  if (keyIndex < statusIndex) return 'done';
  if (keyIndex === statusIndex) return 'current';
  return 'upcoming';
}
function notifiedStatus(row, uid) {
  const n = row.requester_notifications?.[uid];
  if (!n) return null;
  return row.status === 'available' ? n.available : n.request;
}
function hasUnnotified(row) {
  return (row.requester_ids || []).some((uid) => notifiedStatus(row, uid) === false);
}
function canClose(row) {
  return row.status !== 'available' || (row.has_vf !== true && !row.vf_tracking_disabled);
}
function toggleRequesterMenu(rowId, uid) {
  const key = `${rowId}:${uid}`;
  openRequesterMenu.value = openRequesterMenu.value === key ? null : key;
}
function closeRequesterMenu() { openRequesterMenu.value = null; }
function handleOutsideClick(event) {
  if (!event.target.closest('.requester-menu-wrap')) closeRequesterMenu();
}
onMounted(() => document.addEventListener('click', handleOutsideClick));
onBeforeUnmount(() => document.removeEventListener('click', handleOutsideClick));
</script>

<style scoped>
.add-requester-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}
.add-requester-label {
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
}
.add-requester-row .inline-row {
  flex: 1;
}
.add-requester-row select {
  flex: 1;
  min-width: 0;
}

.request-detail-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.request-detail-row .mail-history {
  display: block;
  color: var(--muted);
}

.status-stepper {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin: 6px 0;
}
.origin-line {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  color: var(--muted);
}
.waiting-reason {
  margin: 6px 0;
  color: var(--muted);
  font-size: 12px;
}
.plex-origin-card p {
  margin: 6px 0;
  color: var(--muted);
}
.status-stepper .step {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--border);
  color: var(--muted);
  background: var(--surface-2);
}
.status-stepper .step.done {
  border-color: rgba(34, 197, 94, .45);
  color: var(--green);
}
.status-stepper .step.current {
  border-color: var(--accent);
  color: var(--accent);
  font-weight: 600;
}

.mail-history-details {
  margin-top: 4px;
}
.mail-history-details summary {
  cursor: pointer;
  font-size: 11px;
  color: var(--muted);
  user-select: none;
}
.mail-history-details small {
  display: block;
}

.requester-breakdown {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--border);
}

.requester-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
}

.requester-name {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.badge.tiny {
  min-height: auto;
  padding: 0 6px;
  font-size: 10px;
}

.notif-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.notif-dot.ok {
  background: var(--green);
}
.notif-dot.pending {
  background: var(--muted);
}

.requester-menu-wrap {
  position: relative;
}
.requester-menu {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  z-index: 30;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 200px;
  padding: 6px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}
.requester-menu button {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: 0;
  background: transparent;
  color: var(--text);
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  text-align: left;
}
.requester-menu button:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.06);
}
.requester-menu button.danger {
  color: var(--red);
}
</style>
