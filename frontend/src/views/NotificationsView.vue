<template>
<div class="page">
  <header class="page-head">
    <div>
      <h1>Notifications</h1>
      <p>Historique des envois et file de distribution.</p>
    </div>
    <div class="actions">
      <div class="notification-control" :class="{paused: holdEnabled}">
        <div class="notification-control-icon"><PauseCircle v-if="holdEnabled"/><PlayCircle v-else/></div>
        <div class="notification-control-copy">
          <strong>{{ holdEnabled ? 'Envoi suspendu' : 'Envoi actif' }}</strong>
          <span>{{ holdEnabled ? 'Les nouvelles notifications restent dans la file.' : 'Les notifications sont envoyées automatiquement.' }}</span>
        </div>
        <div class="notification-control-action">
          <span class="notification-control-count" v-if="pendingTotal">{{ pendingTotal }} en attente</span>
          <label class="hold-switch" :title="holdEnabled ? 'Réactiver les notifications automatiques' : 'Mettre les notifications en attente'">
            <input
              type="checkbox"
              role="switch"
              :checked="holdEnabled"
              :disabled="holdSaving"
              :aria-checked="holdEnabled"
              @change="toggleHold($event.target.checked)"
            >
            <span class="hold-switch-track"><span class="hold-switch-thumb"></span></span>
          </label>
        </div>
      </div>
    <button class="icon-button" :disabled="loading" title="Actualiser" @click="load">
      <RefreshCw :class="{spin:loading}"/>
    </button>
    </div>
  </header>

  <Transition name="notification-feedback">
    <p v-if="feedback.text" class="notification-feedback" :class="feedback.type">
      <CheckCheck v-if="feedback.type === 'success'"/><span>{{ feedback.text }}</span>
    </p>
  </Transition>

  <ConfirmModal v-bind="confirmDialog" @cancel="resolveConfirm(false)" @confirm="resolveConfirm(true)" />

  <nav class="detail-tabs">
    <button :class="{active:tab==='history'}" @click="tab='history';offset=0;load()">Historique</button>
    <button :class="{active:tab==='pending'}" @click="tab='pending';offset=0;load()">En attente <span v-if="pendingTotal" class="badge">{{ pendingTotal }}</span></button>
  </nav>

  <div class="toolbar wrap">
    <input v-model="search" class="search" type="search" placeholder="Media, destinataire ou evenement">

    <!-- Actions "En attente" -->
    <div v-if="tab==='pending'&&rows.length" class="actions">
      <button class="secondary" :disabled="!selectedIds.length" @click="sendSelected"><Send/>Envoyer la sélection</button>
      <button class="secondary danger" :disabled="!selectedIds.length" @click="deleteSelected"><Trash2/>Supprimer la sélection</button>
      <button class="secondary" @click="purge(true)"><CheckCheck/>Purger et marquer traitees</button>
      <button class="secondary danger" @click="purge(false)"><Trash2/>Purger</button>
    </div>
  </div>

  <NotificationsFiltersBar
    v-if="tab==='history'"
    v-model:state="state"
    v-model:selected-types="selectedTypes"
    v-model:selected-users="selectedUsers"
    :users="users"
    :type-options="typeOptions"
  />

  <p v-if="error" class="notice error-text">{{ error }}</p>

  <NotificationsTable ref="tableRef" :rows="rows" :tab="tab" :loading="loading" @resend="resend"/>

  <div v-if="tab==='history'&&total>limit" class="pagination">
    <button class="secondary" :disabled="offset===0" @click="page(-1)"><ChevronLeft/>Precedent</button>
    <span>{{ offset+1 }}-{{ Math.min(offset+limit,total) }} sur {{ total }}</span>
    <button class="secondary" :disabled="offset+limit>=total" @click="page(1)">Suivant<ChevronRight/></button>
  </div>
</div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { CheckCheck, ChevronLeft, ChevronRight, PauseCircle, PlayCircle, RefreshCw, Send, Trash2 } from '@lucide/vue';
import { api } from '@/api';
import { useRealtime } from '@/events';
import NotificationsFiltersBar from '@/components/notifications/NotificationsFiltersBar.vue';
import NotificationsTable from '@/components/notifications/NotificationsTable.vue';
import ConfirmModal from '@/components/ConfirmModal.vue';
import { useConfirm } from '@/composables/useConfirm';

const rows = ref([]);
const users = ref([]);
const tab = ref('history');
const loading = ref(false);
const error = ref('');
const search = ref('');
const state = ref('');
const selectedTypes = ref([]);
const selectedUsers = ref([]);
const tableRef = ref(null);

const typeOptions = [
  { value: 'request', label: 'Demandes' },
  { value: 'available', label: 'Disponibilites' },
  { value: 'upgrade', label: 'Améliorations (VF)' },
  { value: 'correction', label: 'Corrections' },
  { value: 'failed', label: 'Erreurs systeme' }
];

const total = ref(0);
const pendingTotal = ref(0);
const offset = ref(0);
const limit = 50;
const holdEnabled = ref(false);
const holdSaving = ref(false);
const feedback = ref({ type: '', text: '' });
let feedbackTimeout;
const { dialog: confirmDialog, askConfirm, resolveConfirm } = useConfirm();

const selectedIds = computed(() => tableRef.value?.selected || []);

async function loadUsers() {
  try {
    const data = await api('/api/users');
    users.value = data || [];
  } catch(e) {
    console.error("Erreur chargement utilisateurs", e);
  }
}

async function loadHold() {
  try {
    const data = await api('/api/notifications/hold');
    holdEnabled.value = data.enabled;
    pendingTotal.value = data.pending_count ?? pendingTotal.value;
  } catch(e) { error.value = e.message; }
}

function showFeedback(type, text) {
  clearTimeout(feedbackTimeout);
  feedback.value = { type, text };
  feedbackTimeout = setTimeout(() => { feedback.value = { type: '', text: '' }; }, 6000);
}

async function toggleHold(enabled) {
  const previous = holdEnabled.value;
  holdSaving.value = true;
  holdEnabled.value = enabled;
  try {
    const data = await api('/api/notifications/hold', { method: 'PUT', body: JSON.stringify({ enabled }) });
    holdEnabled.value = data.enabled;
    pendingTotal.value = data.pending_count ?? pendingTotal.value;
    showFeedback('success', data.message || (enabled ? 'Notifications mises en attente.' : 'Notifications automatiques réactivées.'));
  } catch(e) {
    holdEnabled.value = previous;
    showFeedback('error', `Le changement n'a pas été enregistré : ${e.message}`);
  } finally {
    holdSaving.value = false;
  }
}

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const q = new URLSearchParams({ limit, offset: offset.value });
    if (state.value) q.append('state', state.value);
    if (selectedTypes.value.length) q.append('types', selectedTypes.value.join(','));
    if (selectedUsers.value.length) q.append('users', selectedUsers.value.join(','));
    if (search.value) q.append('search', search.value);

    const data = tab.value === 'history'
      ? await api(`/api/notifications/log?${q.toString()}`)
      : await api('/api/notifications/pending');

    rows.value = data.items || [];
    total.value = data.total || 0;

    if (tab.value === 'pending') {
      pendingTotal.value = data.total || 0;
    } else {
      api('/api/notifications/pending').then(x => pendingTotal.value = x.total).catch(() => {});
    }
  } catch(e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}

async function resend(row) {
  await api(`/api/notifications/${row.id}/resend`, { method: 'POST' });
  await load();
}

async function purge(markHandled) {
  const ids = tableRef.value?.selected || [];
  if (!await askConfirm({
    title: markHandled ? 'Marquer les notifications comme traitées ?' : 'Supprimer les notifications ?',
    message: `${ids.length ? ids.length : 'Toute la file'} notification(s) seront ${markHandled ? 'marquée(s) comme traitée(s)' : 'supprimée(s) définitivement'}.`,
    confirmLabel: markHandled ? 'Marquer comme traitées' : 'Supprimer',
    danger: !markHandled,
  })) return;
  await api('/api/notifications/pending/purge', { method: 'POST', body: JSON.stringify({ ids, mark_handled: markHandled }) });
  if (tableRef.value) tableRef.value.selected = [];
  await load();
}

async function sendSelected() {
  const ids = [...selectedIds.value];
  if (!ids.length) return;
  await api('/api/notifications/pending/process', { method: 'POST', body: JSON.stringify({ ids }) });
  if (tableRef.value) tableRef.value.selected = [];
  await load();
}

async function deleteSelected() {
  const ids = [...selectedIds.value];
  if (!ids.length) return;
  if (!await askConfirm({
    title: 'Supprimer la sélection ?',
    message: `${ids.length} notification(s) seront supprimée(s) définitivement.`,
    confirmLabel: 'Supprimer',
    danger: true,
  })) return;
  await api('/api/notifications/pending/purge', { method: 'POST', body: JSON.stringify({ ids, mark_handled: false }) });
  if (tableRef.value) tableRef.value.selected = [];
  await load();
}

function page(delta) {
  offset.value = Math.max(0, offset.value + delta * limit);
  load();
}

// Relance auto sur modif des filtres (avec reset de l'offset)
watch([state, selectedTypes, selectedUsers], () => {
  offset.value = 0;
  load();
}, { deep: true });

let searchTimeout;
watch(search, () => {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(() => {
    offset.value = 0;
    load();
  }, 300);
});

useRealtime(['notification.updated'], () => { loadHold(); load(); });

onMounted(() => {
  loadUsers();
  loadHold();
  load();
});
</script>

<style scoped>
.notification-control {
  display: flex;
  align-items: center;
  gap: .7rem;
  min-width: min(540px, 55vw);
  padding: .55rem .7rem;
  border: 1px solid var(--border, #d9dee7);
  border-radius: 14px;
  background: var(--surface, #fff);
  box-shadow: 0 3px 12px rgba(20, 34, 55, .06);
}
.notification-control.paused { border-color: #e9c46a; background: #fffaf0; }
.notification-control-icon { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 10px; color: #2471a3; background: #eaf4fb; }
.notification-control.paused .notification-control-icon { color: #a66a00; background: #fff0c9; }
.notification-control-copy { display: grid; gap: .12rem; min-width: 0; flex: 1; }
.notification-control-copy strong { font-size: .86rem; }
.notification-control-copy span { overflow: hidden; color: var(--muted, #667085); font-size: .72rem; text-overflow: ellipsis; white-space: nowrap; }
.notification-control-action { display: flex; align-items: center; gap: .6rem; }
.notification-control-count { color: #9a6500; font-size: .72rem; font-weight: 700; white-space: nowrap; }
.hold-switch { position: relative; display: inline-flex; cursor: pointer; }
.hold-switch input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.hold-switch-track { display: flex; align-items: center; width: 42px; height: 24px; padding: 3px; border-radius: 999px; background: #b8c0cc; transition: background .2s ease; }
.hold-switch-thumb { width: 18px; height: 18px; border-radius: 50%; background: #fff; box-shadow: 0 1px 3px rgba(0, 0, 0, .25); transition: transform .2s ease; }
.hold-switch input:checked + .hold-switch-track { background: #d89a16; }
.hold-switch input:checked + .hold-switch-track .hold-switch-thumb { transform: translateX(18px); }
.hold-switch input:focus-visible + .hold-switch-track { outline: 3px solid rgba(36, 113, 163, .28); outline-offset: 2px; }
.hold-switch input:disabled + .hold-switch-track { cursor: wait; opacity: .6; }
.notification-feedback { display: flex; align-items: center; gap: .45rem; margin: .9rem 0 0; padding: .7rem .85rem; border-radius: 10px; font-size: .84rem; }
.notification-feedback.success { color: #176b42; background: #eaf8f0; }
.notification-feedback.error { color: #a33a2b; background: #fff0ee; }
.notification-feedback-enter-active, .notification-feedback-leave-active { transition: opacity .2s ease, transform .2s ease; }
.notification-feedback-enter-from, .notification-feedback-leave-to { opacity: 0; transform: translateY(-4px); }
@media (max-width: 900px) {
  .notification-control { min-width: 0; max-width: calc(100vw - 3rem); }
  .notification-control-copy span { display: none; }
}
</style>
