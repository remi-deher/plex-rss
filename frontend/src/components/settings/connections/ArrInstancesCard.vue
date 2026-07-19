<template>
  <SettingsCard
    title="Instances Sonarr, Radarr et Prowlarr"
    :subtitle="`${arrInstances.length} instance(s) configuree(s)`"
    :icon="ServerCog"
    :status="arrInstances.some(i => i.enabled) ? 'active' : 'inactive'"
    :collapsible="false"
  >
    <template #actions>
      <button class="secondary" @click.stop="openArrModal()"><Plus/>Ajouter</button>
    </template>
    <div v-if="arrInstances.length" class="table-wrap table-cards rich">
      <table>
        <thead>
          <tr><th>Nom</th><th>Type</th><th>Adresse</th><th>Statut</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="instance in arrInstances" :key="instance.id">
            <td class="card-title"><strong>{{ instance.name }}</strong><small v-if="instance.is_default">Par defaut</small></td>
            <td data-label="Type"><span class="badge">{{ instance.arr_type }}</span></td>
            <td class="url-cell" data-label="Adresse">{{ instance.url }}</td>
            <td data-label="Statut"><span class="badge" :class="instance.enabled?'available':'failed'">{{ instance.enabled?'Actif':'Inactif' }}</span></td>
            <td class="actions card-actions">
              <button class="icon-button" title="Tester" @click="testArr(instance)"><PlugZap/></button>
              <button class="icon-button" title="Modifier" @click="openArrModal(instance)"><Pencil/></button>
              <button class="icon-button" :title="instance.enabled?'Desactiver':'Activer'" @click="toggleArr(instance)"><Power/></button>
              <button class="icon-button danger" title="Supprimer" @click="removeArr(instance)"><Trash2/></button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="empty">Aucune instance configuree.</p>
  </SettingsCard>

  <div v-if="showArrModal" class="drawer-backdrop" @click.self="closeArrModal">
    <aside class="modal-panel arr-instance-modal">
      <div class="panel-head">
        <h2>{{ editingArrId?'Modifier l\'instance':'Ajouter une instance' }}</h2>
        <button class="icon-button" title="Fermer" @click="closeArrModal"><X/></button>
      </div>
      <div class="compact-form">
        <label>Nom<input v-model="arrForm.name"></label>
        <label>Type<select v-model="arrForm.arr_type"><option value="sonarr">Sonarr</option><option value="radarr">Radarr</option><option value="prowlarr">Prowlarr</option></select></label>
        <label>URL<input v-model="arrForm.url" type="url"></label>
        <label>Cle API<input v-model="arrForm.api_key" type="password"></label>
        <label>Profil<select v-model.number="arrForm.quality_profile_id"><option :value="null">Par defaut</option><option v-for="profile in arrProfiles" :key="profile.id" :value="profile.id">{{ profile.name }}</option></select></label>
        <label>Dossier racine<select v-model="arrForm.root_folder"><option value="">Par defaut</option><option v-for="folder in arrFolders" :key="folder.path||folder" :value="folder.path||folder">{{ folder.path||folder }}</option></select></label>
        <label class="check"><input v-model="arrForm.is_default" type="checkbox"> Instance par defaut</label>
      </div>
      <div class="actions">
        <button class="secondary" @click="loadArrOptions"><ListRestart/>Charger profils et dossiers</button>
        <button class="primary" :disabled="busy||!arrForm.name||!arrForm.url||!arrForm.api_key" @click="saveArr"><Save/>{{ editingArrId?'Mettre a jour':'Ajouter' }}</button>
        <button class="secondary" @click="closeArrModal">Annuler</button>
      </div>
    </aside>
  </div>
  <ConfirmModal v-bind="confirmDialog" @cancel="resolveConfirm(false)" @confirm="resolveConfirm(true)" />
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { ListRestart, Pencil, Plus, PlugZap, Power, Save, ServerCog, Trash2, X } from '@lucide/vue';
import { api } from '@/api';
import { success, fail } from '@/settingsForm';
import SettingsCard from '../SettingsCard.vue';
import ConfirmModal from '../../ConfirmModal.vue';
import { useConfirm } from '@/composables/useConfirm';

const busy = ref(false);
const arrInstances = ref([]), arrProfiles = ref([]), arrFolders = ref([]), editingArrId = ref(null);
const showArrModal = ref(false);
const arrDefaults = { name: '', arr_type: 'sonarr', url: '', api_key: '', quality_profile_id: null, root_folder: '', minimum_availability: 'released', is_default: false, enabled: true, indexer_ids: null };
const arrForm = reactive({ ...arrDefaults });
const { dialog: confirmDialog, askConfirm, resolveConfirm } = useConfirm();

async function loadArr() { arrInstances.value = await api('/api/arr-instances'); }
function resetArr() { editingArrId.value = null; Object.assign(arrForm, arrDefaults); arrProfiles.value = []; arrFolders.value = []; }
function openArrModal(instance) {
  resetArr();
  if (instance) { editingArrId.value = instance.id; Object.assign(arrForm, arrDefaults, instance); loadArrOptions(); }
  showArrModal.value = true;
}
function closeArrModal() { showArrModal.value = false; resetArr(); }
async function loadArrOptions() {
  if (arrForm.arr_type === 'prowlarr') { arrProfiles.value = []; arrFolders.value = []; return; }
  const q = editingArrId.value ? `?instance_id=${editingArrId.value}` : `?url=${encodeURIComponent(arrForm.url)}&api_key=${encodeURIComponent(arrForm.api_key)}`;
  [arrProfiles.value, arrFolders.value] = await Promise.all([
    api(`/api/${arrForm.arr_type}/profiles${q}`).catch(() => []),
    api(`/api/${arrForm.arr_type}/folders${q}`).catch(() => []),
  ]);
}
async function saveArr() {
  busy.value = true;
  try {
    await api(editingArrId.value ? `/api/arr-instances/${editingArrId.value}` : '/api/arr-instances', { method: editingArrId.value ? 'PUT' : 'POST', body: JSON.stringify(arrForm) });
    success(editingArrId.value ? 'Instance mise a jour.' : 'Instance ajoutee.');
    showArrModal.value = false;
    resetArr();
    await loadArr();
  } catch (e) { fail(e); } finally { busy.value = false; }
}
async function testArr(instance = arrForm) {
  try {
    const data = await api('/api/test/arr-instance', { method: 'POST', body: JSON.stringify({ url: instance.url, api_key: instance.api_key, arr_type: instance.arr_type }) });
    success(data.message || 'Instance joignable.');
  } catch (e) { fail(e); }
}
async function toggleArr(instance) { await api(`/api/arr-instances/${instance.id}/toggle`, { method: 'PATCH' }); await loadArr(); }
async function removeArr(instance) { if (!await askConfirm({ title: 'Supprimer cette instance ?', message: `${instance.name} sera supprimée définitivement.`, confirmLabel: 'Supprimer', danger: true })) return; await api(`/api/arr-instances/${instance.id}`, { method: 'DELETE' }); await loadArr(); }

onMounted(loadArr);
</script>
