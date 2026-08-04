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

        <RequestStatusStepper v-if="!['failed','rejected'].includes(row.status)" :row="row" />

        <details v-if="row.media_type === 'show' && row.seasons?.length" class="mail-history-details">
          <summary>Detail par saison ({{ seasonsSummary(row.seasons) }})</summary>
          <div v-for="season in row.seasons" :key="season.season_number" class="inline-row compact" style="justify-content: space-between; margin-bottom: 4px;">
            <span>Saison {{ season.season_number }}</span>
            <span class="badge" :class="season.status">{{ season.episodes_available_count }}/{{ season.episodes_total_count }}</span>
          </div>
        </details>

        <RequestMailHistory :row="row" />
        <RequesterList
          :row="row"
          :admin="admin"
          :busy="busy"
          @notify-user="(...args) => $emit('notify-user', ...args)"
          @promote-requester="(...args) => $emit('promote-requester', ...args)"
          @remove-requester="(...args) => $emit('remove-requester', ...args)"
        />
      </div>
      <details v-if="admin" class="request-admin-actions">
        <summary>Administration</summary>
        <div class="actions">
          <button v-if="row.status === 'pending_approval'" class="icon-button success" title="Approuver" aria-label="Approuver" :disabled="busy" @click="$emit('approve', row.id)"><Check /></button>
          <button v-if="row.status === 'pending_approval'" class="icon-button danger" title="Refuser" aria-label="Refuser" :disabled="busy" @click="$emit('reject', row)"><Ban /></button>
          <button v-if="row.arr_id" class="icon-button" title="Rechercher une release" aria-label="Rechercher une release" @click="$emit('open-release', row.id)"><Search /></button>
          <button v-if="row.status === 'failed'" class="icon-button" title="Relancer" aria-label="Relancer" @click="$emit('retry', row.id)"><RotateCcw /></button>
          <button v-if="hasUnnotified(row)" class="icon-button" title="Rattraper tout le monde (notifier les demandeurs pas encore prevenus)" aria-label="Rattraper tout le monde (notifier les demandeurs pas encore prevenus)" :disabled="busy" @click="$emit('catch-up-all', row)"><Users /></button>
          <button class="icon-button" :title="(row.requester_ids || []).length > 1 ? 'Renvoyer le mail de demande a tous' : 'Renvoyer email de demande'" :aria-label="(row.requester_ids || []).length > 1 ? 'Renvoyer le mail de demande a tous' : 'Renvoyer email de demande'" :disabled="busy" @click="$emit('resend-mail', row.id, 'request')"><Mail /></button>
          <button v-if="row.status === 'available'" class="icon-button" :title="(row.requester_ids || []).length > 1 ? 'Renvoyer le mail de disponibilite a tous' : 'Renvoyer email de disponibilite'" :aria-label="(row.requester_ids || []).length > 1 ? 'Renvoyer le mail de disponibilite a tous' : 'Renvoyer email de disponibilite'" :disabled="busy" @click="$emit('resend-mail', row.id, 'available')"><MailCheck /></button>
          <button v-if="canClose(row)" class="icon-button" title="Cloturer la demande" aria-label="Cloturer la demande" :disabled="busy" @click="$emit('close-request', row)"><CheckCheck /></button>
          <button class="icon-button danger" title="Supprimer" aria-label="Supprimer" @click="$emit('delete-request', row.id)"><Trash2 /></button>
        </div>
      </details>
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
import { requestStatusLabel } from '@/utils/labels';
import { Ban, Check, CheckCheck, Mail, MailCheck, PlusCircle, RotateCcw, Search, Trash2, Users } from '@lucide/vue';
import RequestMailHistory from './RequestMailHistory.vue';
import RequestStatusStepper from './RequestStatusStepper.vue';
import RequesterList from './RequesterList.vue';
import { canClose, hasUnnotified, seasonsSummary } from './requestRules';

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

</script>

<style scoped>
.add-requester-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}
.add-requester-label {
  font-size: var(--fs-sm);
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
  gap: var(--space-2);
}
.request-admin-actions {
  align-self: start;
  min-width: 130px;
}
.request-admin-actions summary {
  cursor: pointer;
  color: var(--muted);
  font-size: var(--fs-sm);
  font-weight: 600;
  text-align: right;
}
.request-admin-actions .actions {
  justify-content: flex-end;
  margin-top: 8px;
}
:deep(.request-detail-row .mail-history) {
  display: block;
  color: var(--muted);
}

:deep(.status-stepper) {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1);
  margin: 6px 0;
}
.origin-line {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: 6px;
  color: var(--muted);
}
.waiting-reason {
  margin: 6px 0;
  color: var(--muted);
  font-size: var(--fs-sm);
}
.plex-origin-card p {
  margin: 6px 0;
  color: var(--muted);
}
:deep(.status-stepper .step) {
  font-size: var(--fs-xs);
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border);
  color: var(--muted);
  background: var(--surface-2);
}
:deep(.status-stepper .step.done) {
  border-color: rgba(34, 197, 94, .45);
  color: var(--green-text);
}
:deep(.status-stepper .step.current) {
  border-color: var(--accent);
  color: var(--accent);
  font-weight: 600;
}

:deep(.mail-history-details) {
  margin-top: 4px;
}
:deep(.mail-history-details summary) {
  cursor: pointer;
  font-size: var(--fs-xs);
  color: var(--muted);
  user-select: none;
}
:deep(.mail-history-details small) {
  display: block;
}

:deep(.requester-breakdown) {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--border);
}

:deep(.requester-line) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  font-size: var(--fs-sm);
}

:deep(.requester-name) {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

:deep(.badge.tiny) {
  min-height: auto;
  padding: 0 6px;
  font-size: var(--fs-xs);
}

:deep(.notif-dot) {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
:deep(.notif-dot.ok) {
  background: var(--green);
}
:deep(.notif-dot.pending) {
  background: var(--muted);
}

:deep(.requester-menu-wrap) {
  position: relative;
}
:deep(.requester-menu) {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  z-index: 30;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 200px;
  padding: 6px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}
:deep(.requester-menu button) {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 6px 8px;
  border: 0;
  background: transparent;
  color: var(--text);
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--fs-sm);
  text-align: left;
}
:deep(.requester-menu button:hover:not(:disabled)) {
  background: rgba(255, 255, 255, 0.06);
}
:deep(.requester-menu button.danger) {
  color: var(--red-text);
}
</style>
