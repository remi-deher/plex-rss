<template>
  <SettingsCard
    title="Clients de telechargement direct"
    :subtitle="`${clients.length} client(s) configure(s) — utilises pour pousser une release choisie manuellement via la recherche Prowlarr, sans passer par Sonarr/Radarr`"
    :icon="Download"
    :status="clients.some(c => c.enabled) ? 'active' : 'inactive'"
    :default-open="clients.some(c => c.enabled)"
  >
    <template #actions>
      <button class="secondary" @click.stop="openClientModal()"><Plus/>Ajouter</button>
    </template>
    <div v-if="clients.length" class="table-wrap table-cards rich">
      <table>
        <thead>
          <tr><th>Nom</th><th>Type</th><th>Adresse</th><th>Statut</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="client in clients" :key="client.id">
            <td class="card-title"><strong>{{ client.name }}</strong><small v-if="client.is_default">Par defaut</small></td>
            <td data-label="Type"><span class="badge">{{ client.client_type }}</span></td>
            <td class="url-cell" data-label="Adresse">{{ client.url }}</td>
            <td data-label="Statut"><span class="badge" :class="client.enabled?'available':'failed'">{{ client.enabled?'Actif':'Inactif' }}</span></td>
            <td class="actions card-actions">
              <button class="icon-button" title="Tester" aria-label="Tester" @click="testClient(client)"><PlugZap/></button>
              <button class="icon-button" title="Modifier" aria-label="Modifier" @click="openClientModal(client)"><Pencil/></button>
              <button class="icon-button" :title="client.enabled?'Desactiver':'Activer'" :aria-label="client.enabled?'Desactiver':'Activer'" @click="toggleClient(client)"><Power/></button>
              <button class="icon-button danger" title="Supprimer" aria-label="Supprimer" @click="removeClient(client)"><Trash2/></button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="empty">Aucun client configure.</p>
  </SettingsCard>

  <ModalShell
    v-if="showClientModal"
    :title="editingClientId?'Modifier le client':'Ajouter un client'"
    panel-class="arr-instance-modal"
    @close="closeClientModal"
  >
    <div class="compact-form">
        <label>Nom<input v-model="clientForm.name"></label>
        <label>Type<select v-model="clientForm.client_type"><option value="qbittorrent">qBittorrent</option><option value="transmission">Transmission</option><option value="deluge">Deluge</option></select></label>
        <label>URL<input v-model="clientForm.url" type="url"></label>
        <label>Utilisateur<input v-model="clientForm.username"></label>
        <label>Mot de passe<input v-model="clientForm.password" type="password"></label>
        <label>Categorie<input v-model="clientForm.category"><small>Categorie appliquee aux torrents envoyes, pour les retrouver facilement dans le client.</small></label>
        <label>Tags<input v-model="clientForm.tags"><small>Tags separes par des virgules, appliques aux torrents envoyes depuis Plexarr.</small></label>
        <label class="check"><input v-model="clientForm.is_default" type="checkbox"> Client par defaut</label>
        <small class="check-hint">Client preselectionne quand plusieurs sont configures et qu'aucun n'est explicitement choisi lors d'un envoi manuel.</small>
    </div>
    <template #actions>
      <button class="primary" :disabled="!clientForm.name||!clientForm.url" @click="saveClient"><Save/>{{ editingClientId?'Mettre a jour':'Ajouter' }}</button>
      <button class="secondary" @click="closeClientModal">Annuler</button>
    </template>
  </ModalShell>
  <ConfirmModal v-bind="confirmDialog" @cancel="resolveConfirm(false)" @confirm="resolveConfirm(true)" />
</template>

<script setup>
import ModalShell from '@/components/ui/ModalShell.vue';
import { onMounted, reactive, ref } from 'vue';
import { Download, Pencil, Plus, PlugZap, Power, Save, Trash2 } from '@lucide/vue';
import { api } from '@/api';
import ConfirmModal from '../../ConfirmModal.vue';
import { useConfirm } from '@/composables/useConfirm';
import { success, fail } from '@/settingsForm';
import SettingsCard from '../SettingsCard.vue';

const clients = ref([]), editingClientId = ref(null);
const showClientModal = ref(false);
const { dialog: confirmDialog, askConfirm, resolveConfirm } = useConfirm();
const clientDefaults = { name: '', client_type: 'qbittorrent', url: '', username: '', password: '', category: '', tags: '', is_default: false, enabled: true };
const clientForm = reactive({ ...clientDefaults });

async function loadClients() { clients.value = await api('/api/download-clients'); }
function resetClient() { editingClientId.value = null; Object.assign(clientForm, clientDefaults); }
function openClientModal(client) {
  resetClient();
  if (client) { editingClientId.value = client.id; Object.assign(clientForm, clientDefaults, client); }
  showClientModal.value = true;
}
function closeClientModal() { showClientModal.value = false; resetClient(); }
async function saveClient() {
  try {
    await api(editingClientId.value ? `/api/download-clients/${editingClientId.value}` : '/api/download-clients', { method: editingClientId.value ? 'PUT' : 'POST', body: JSON.stringify(clientForm) });
    showClientModal.value = false;
    resetClient();
    await loadClients();
    success('Client enregistre.');
  } catch (e) { fail(e); }
}
async function testClient(client = clientForm) {
  try {
    const data = await api('/api/test/download-client', { method: 'POST', body: JSON.stringify(client) });
    success(data.message || 'Client joignable.');
  } catch (e) { fail(e); }
}
async function toggleClient(client) { await api(`/api/download-clients/${client.id}/toggle`, { method: 'PATCH' }); await loadClients(); }
async function removeClient(client) { if (!await askConfirm({ title: 'Supprimer ce client ?', message: `${client.name} sera supprimé définitivement.`, confirmLabel: 'Supprimer', danger: true })) return; await api(`/api/download-clients/${client.id}`, { method: 'DELETE' }); await loadClients(); }

onMounted(loadClients);
</script>
