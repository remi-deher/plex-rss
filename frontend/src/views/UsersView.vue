<template>
  <div class="page">
    <header class="page-head"><div><h1>Utilisateurs</h1><p>Comptes Plex, Seer, roles et preferences de notification.</p></div><div class="actions"><button class="secondary" :disabled="busy" @click="syncSeer"><RefreshCw/>Synchroniser Seer</button><button class="primary" @click="openCreate"><UserPlus/>Ajouter</button></div></header>
    <div class="toolbar wrap"><input v-model="query" class="search" type="search" placeholder="Rechercher un utilisateur"><select v-model="status"><option value="">Tous les statuts</option><option value="enabled">Actifs</option><option value="disabled">Desactives</option></select><select v-model="source"><option value="">Toutes les sources</option><option v-for="value in sources" :key="value">{{ value }}</option></select><select v-model="sort"><option value="name">Nom</option><option value="requests">Demandes</option></select></div>
    <p v-if="error" class="notice error-text">{{ error }}</p><p v-if="message" class="notice success-text">{{ message }}</p>

    <UsersTable ref="tableRef" :rows="filtered" :loading="loading" @open="openUser" @toggle="toggle" @bulk-status="bulkStatus" @bulk-notify="bulkNotify" @bulk-delete="bulkDelete"/>

    <UserEditorDrawer
      v-if="editing"
      ref="drawerRef"
      :editing="editing"
      :creating="creating"
      :form="form"
      :users="users"
      :busy="busy"
      :editor-error="editorError"
      @close="closeEditor"
      @save="saveUser"
      @delete="deleteUser"
      @test-email="testEmail"
      @user-action="userAction"
      @unlink-seer="unlinkSeer"
      @merge="mergeUser"
    />
    <ConfirmModal v-bind="confirmDialog" @cancel="resolveConfirm(false)" @confirm="resolveConfirm(true)" />
  </div>
</template>
<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { RefreshCw, UserPlus } from '@lucide/vue';
import { useRoute, useRouter } from 'vue-router';
import { api } from '@/api';
import UsersTable from '@/components/users/UsersTable.vue';
import UserEditorDrawer from '@/components/users/UserEditorDrawer.vue';
import ConfirmModal from '@/components/ConfirmModal.vue';
import { useConfirm } from '@/composables/useConfirm';

const route = useRoute(), router = useRouter();
const users = ref([]), editing = ref(null), creating = ref(false), query = ref(''), status = ref(''), source = ref(''), sort = ref('name');
const loading = ref(false), busy = ref(false), error = ref(''), editorError = ref(''), message = ref('');
const tableRef = ref(null), drawerRef = ref(null);
const { dialog: confirmDialog, askConfirm, resolveConfirm } = useConfirm();

const defaults = { plex_user_id: '', display_name: '', custom_name: '', plex_email: '', notification_email: '', enabled: true, notify_admin: true, notify_on_request: true, notify_on_available: true, notify_digest: false, notify_vf_movie: true, notify_vf_series: true, notify_vf_anime: false, discord_webhook_url: '', telegram_chat_id: '', seer_active: null, role: 'user', can_login: true, auto_approve: false, sonarr_instance_id: null, radarr_instance_id: null, movie_notify_language: null, series_notify_language: null, series_notify_granularity: 'jalons' };
const form = reactive({ ...defaults });

const sources = computed(() => [...new Set(users.value.map(x => x.source).filter(Boolean))]);
const filtered = computed(() => users.value.filter(user =>
  (!query.value || `${displayName(user)} ${user.plex_user_id} ${user.plex_email || ''}`.toLowerCase().includes(query.value.toLowerCase())) &&
  (!status.value || (status.value === 'enabled') === Boolean(user.enabled)) &&
  (!source.value || user.source === source.value)
).sort((a, b) => sort.value === 'requests' ? (b.stats?.total || 0) - (a.stats?.total || 0) : displayName(a).localeCompare(displayName(b), 'fr')));

function displayName(user) { return user?.custom_name || user?.display_name || user?.plex_user_id || ''; }
function fillForm(user) { Object.assign(form, defaults, Object.fromEntries(Object.keys(defaults).map(key => [key, user?.[key] ?? defaults[key]]))); }

async function load() { loading.value = true; error.value = ''; try { users.value = await api('/api/users'); } catch (e) { error.value = e.message; } finally { loading.value = false; } }
async function openUser(id) {
  creating.value = false; editorError.value = '';
  try { editing.value = await api(`/api/users/${id}`); fillForm(editing.value); drawerRef.value?.resetTab(); router.replace(`/users/${id}`); }
  catch (e) { error.value = e.message; }
}
function openCreate() { creating.value = true; editing.value = {}; fillForm(null); drawerRef.value?.resetTab(); }
function closeEditor() { editing.value = null; creating.value = false; if (route.params.userId) router.replace('/users'); }
async function saveUser() {
  busy.value = true; editorError.value = '';
  try {
    const path = creating.value ? '/api/users' : `/api/users/${editing.value.id}`;
    const saved = await api(path, { method: creating.value ? 'POST' : 'PUT', body: JSON.stringify(form) });
    await load(); message.value = 'Utilisateur enregistre.';
    if (creating.value) await openUser(saved.id); else await openUser(editing.value.id);
  } catch (e) { editorError.value = e.message; } finally { busy.value = false; }
}
async function toggle(user) { try { await api(`/api/users/${user.id}/enabled`, { method: 'PUT', body: JSON.stringify({ enabled: !user.enabled }) }); await load(); } catch (e) { error.value = e.message; } }
async function deleteUser() { if (!await askConfirm({ title: 'Supprimer cet utilisateur ?', message: `${displayName(editing.value)} sera supprimé définitivement.`, confirmLabel: 'Supprimer', danger: true })) return; await api(`/api/users/${editing.value.id}`, { method: 'DELETE' }); closeEditor(); await load(); }
async function syncSeer() { busy.value = true; try { await api('/api/seer/sync', { method: 'POST' }); message.value = 'Synchronisation Seer terminee.'; await load(); } catch (e) { error.value = e.message; } finally { busy.value = false; } }
async function userAction(action) { busy.value = true; try { await api(`/api/users/${editing.value.id}/${action}`, { method: 'POST' }); await openUser(editing.value.id); } catch (e) { editorError.value = e.message; } finally { busy.value = false; } }
async function unlinkSeer() { await api(`/api/users/${editing.value.id}/seer-link`, { method: 'DELETE' }); await openUser(editing.value.id); }
async function testEmail() { const data = await api(`/api/users/${editing.value.id}/test-email`, { method: 'POST' }); message.value = `Email envoye a ${data.recipient}`; }
async function mergeUser(targetId) { if (!await askConfirm({ title: 'Fusionner les utilisateurs ?', message: 'Cette fusion est irréversible. Les demandes et préférences seront rattachées à l’utilisateur cible.', confirmLabel: 'Fusionner', danger: true })) return; await api(`/api/users/${editing.value.id}/merge-into/${targetId}`, { method: 'POST' }); closeEditor(); await load(); }

async function bulkStatus(enabled) { const ids = tableRef.value.selectedIds; await api('/api/users/bulk/status', { method: 'PUT', body: JSON.stringify({ user_ids: ids, enabled }) }); tableRef.value.selectedIds = []; await load(); }
async function bulkDelete() { const ids = tableRef.value.selectedIds; if (!await askConfirm({ title: 'Supprimer les utilisateurs sélectionnés ?', message: `${ids.length} utilisateur(s) seront supprimé(s) définitivement.`, confirmLabel: 'Supprimer', danger: true })) return; await api('/api/users/bulk/delete', { method: 'POST', body: JSON.stringify({ user_ids: ids }) }); tableRef.value.selectedIds = []; await load(); }
async function bulkNotify(field, value) {
  const ids = tableRef.value.selectedIds;
  try { await api('/api/users/bulk/notifications', { method: 'PUT', body: JSON.stringify({ user_ids: ids, [field]: value }) }); message.value = 'Notifications mises a jour.'; tableRef.value.selectedIds = []; await load(); }
  catch (e) { error.value = e.message; }
}

onMounted(async () => { await load(); if (route.params.userId) await openUser(route.params.userId); });
</script>
