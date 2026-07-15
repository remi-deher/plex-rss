<template>
  <div class="settings-grid">
    <div class="settings-cards span-two">
      <SettingsCard title="Plex" :icon="Server" :status="plexStatus" default-open>
        <template #actions>
          <button class="secondary" @click.stop="testSaved('/api/test/plex-api')"><PlugZap/>Tester</button>
        </template>
        <label>URL<input v-model="form.plex_url" type="url" placeholder="http://plex:32400"></label>
        <label>Token<input v-model="form.plex_token" type="password" placeholder="Laisser vide pour conserver"></label>
        <label>URL RSS<input v-model="form.plex_rss_url" type="url"></label>
        <label class="check"><input v-model="form.plex_verify_ssl" type="checkbox"> Verifier le certificat TLS</label>
        <div class="actions">
          <button class="secondary" @click="testSaved('/api/test/plex-rss')"><Rss/>Tester le RSS</button>
          <button class="secondary" @click="startPlexSso"><LogIn/>Connexion Plex SSO</button>
        </div>
      </SettingsCard>

      <SettingsCard title="Seer" subtitle="Overseerr / Jellyseerr" :icon="Radar" :status="form.seer_enabled ? 'active' : 'inactive'">
        <template #actions>
          <button class="secondary" :disabled="!form.seer_enabled" @click.stop="testSeer"><PlugZap/>Tester</button>
        </template>
        <label class="check"><input v-model="form.seer_enabled" type="checkbox"> Activer Seer</label>
        <label>URL Seer<input v-model="form.seer_url" type="url" placeholder="http://seer:5055"></label>
        <label>Cle API Seer<input v-model="form.seer_api_key" type="password" placeholder="Laisser vide pour conserver"></label>
        <template v-if="form.seer_enabled">
          <label>Mode
            <select v-model="form.seer_mode">
              <option value="observer">Observateur — Seer n'est qu'une source d'information</option>
              <option value="actor">Acteur — Seer traite aussi les demandes</option>
            </select>
          </label>
          <p class="hint" v-if="form.seer_mode !== 'actor'">
            Les demandes sont toujours traitées par Sonarr/Radarr/Prowlarr ; Seer n'est consulté qu'en lecture
            (synchronisation, statut affiché). Une panne de Seer n'a aucun impact.
          </p>
          <template v-if="form.seer_mode === 'actor'">
            <label class="check"><input v-model="form.seer_fallback_arr" type="checkbox"> Repli direct Sonarr/Radarr</label>
            <label class="check"><input v-model="form.seer_suppress_notifications" type="checkbox"> Laisser Plex-RSS gerer les emails de demande pour les utilisateurs Seer</label>
          </template>
        </template>
      </SettingsCard>

      <SettingsCard title="TMDB" subtitle="Metadonnees et posters" :icon="Clapperboard" :status="form.tmdb_enabled ? 'active' : 'inactive'">
        <template #actions>
          <button class="secondary" :disabled="!form.tmdb_enabled" @click.stop="testTmdb"><PlugZap/>Tester</button>
        </template>
        <label class="check"><input v-model="form.tmdb_enabled" type="checkbox"> Activer TMDB</label>
        <label>Cle TMDB<input v-model="form.tmdb_api_key" type="password" placeholder="Laisser vide pour conserver"></label>
      </SettingsCard>

      <SettingsCard
        title="Instances Sonarr, Radarr et Prowlarr"
        :subtitle="`${arrInstances.length} instance(s) configuree(s)`"
        :icon="ServerCog"
        :status="arrInstances.some(i => i.enabled) ? 'active' : 'inactive'"
      >
        <template #actions>
          <button class="secondary" @click.stop="openArrModal()"><Plus/>Ajouter</button>
        </template>
        <div v-if="arrInstances.length" class="table-wrap">
          <table>
            <thead>
              <tr><th>Nom</th><th>Type</th><th>Adresse</th><th>Statut</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="instance in arrInstances" :key="instance.id">
                <td><strong>{{ instance.name }}</strong><small v-if="instance.is_default">Par defaut</small></td>
                <td><span class="badge">{{ instance.arr_type }}</span></td>
                <td class="url-cell">{{ instance.url }}</td>
                <td><span class="badge" :class="instance.enabled?'available':'failed'">{{ instance.enabled?'Actif':'Inactif' }}</span></td>
                <td class="actions">
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

      <SettingsCard
        title="Clients de telechargement direct"
        :subtitle="`${clients.length} client(s) configure(s)`"
        :icon="Download"
        :status="clients.some(c => c.enabled) ? 'active' : 'inactive'"
      >
        <template #actions>
          <button class="secondary" @click.stop="openClientModal()"><Plus/>Ajouter</button>
        </template>
        <div v-if="clients.length" class="table-wrap">
          <table>
            <thead>
              <tr><th>Nom</th><th>Type</th><th>Adresse</th><th>Statut</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="client in clients" :key="client.id">
                <td><strong>{{ client.name }}</strong><small v-if="client.is_default">Par defaut</small></td>
                <td><span class="badge">{{ client.client_type }}</span></td>
                <td class="url-cell">{{ client.url }}</td>
                <td><span class="badge" :class="client.enabled?'available':'failed'">{{ client.enabled?'Actif':'Inactif' }}</span></td>
                <td class="actions">
                  <button class="icon-button" title="Tester" @click="testClient(client)"><PlugZap/></button>
                  <button class="icon-button" title="Modifier" @click="openClientModal(client)"><Pencil/></button>
                  <button class="icon-button" :title="client.enabled?'Desactiver':'Activer'" @click="toggleClient(client)"><Power/></button>
                  <button class="icon-button danger" title="Supprimer" @click="removeClient(client)"><Trash2/></button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="empty">Aucun client configure.</p>
      </SettingsCard>
    </div>

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

    <div v-if="showClientModal" class="drawer-backdrop" @click.self="closeClientModal">
      <aside class="modal-panel arr-instance-modal">
        <div class="panel-head">
          <h2>{{ editingClientId?'Modifier le client':'Ajouter un client' }}</h2>
          <button class="icon-button" title="Fermer" @click="closeClientModal"><X/></button>
        </div>
        <div class="compact-form">
          <label>Nom<input v-model="clientForm.name"></label>
          <label>Type<select v-model="clientForm.client_type"><option value="qbittorrent">qBittorrent</option><option value="transmission">Transmission</option><option value="deluge">Deluge</option></select></label>
          <label>URL<input v-model="clientForm.url" type="url"></label>
          <label>Utilisateur<input v-model="clientForm.username"></label>
          <label>Mot de passe<input v-model="clientForm.password" type="password"></label>
          <label>Categorie<input v-model="clientForm.category"></label>
          <label>Tags<input v-model="clientForm.tags"></label>
          <label class="check"><input v-model="clientForm.is_default" type="checkbox"> Client par defaut</label>
        </div>
        <div class="actions">
          <button class="primary" :disabled="!clientForm.name||!clientForm.url" @click="saveClient"><Save/>{{ editingClientId?'Mettre a jour':'Ajouter' }}</button>
          <button class="secondary" @click="closeClientModal">Annuler</button>
        </div>
      </aside>
    </div>
  </div>
</template>
<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { Clapperboard, Download, ListRestart, LogIn, Pencil, Plus, PlugZap, Power, Radar, Rss, Save, Server, ServerCog, Trash2, X } from '@lucide/vue';
import { api } from '@/api';
import { form, load, secretsPresent, success, fail, testSaved } from '@/settingsForm';
import SettingsCard from './SettingsCard.vue';

const busy = ref(false);
// secretsPresent.plex_token reflete la config reelle (persistee), contrairement a
// form.plex_token qui est toujours vide juste apres le chargement (voir settingsForm.js).
const plexStatus = computed(() => (form.plex_url && secretsPresent.plex_token ? 'active' : 'inactive'));

async function testSeer() {
  try {
    const data = await api('/api/test/seer', { method: 'POST', body: JSON.stringify({ seer_url: form.seer_url, seer_api_key: form.seer_api_key }) });
    success(data.message || 'Connexion valide.');
  } catch (e) { fail(e); }
}
async function testTmdb() {
  try {
    const data = await api('/api/test/tmdb', { method: 'POST', body: JSON.stringify({ tmdb_api_key: form.tmdb_api_key }) });
    success(data.message || 'Connexion valide.');
  } catch (e) { fail(e); }
}
async function startPlexSso() {
  try {
    const data = await api('/api/plex/sso/pin', { method: 'POST' });
    window.open(data.auth_url || data.url, '_blank', 'noopener');
    const timer = setInterval(async () => {
      const state = await api(`/api/plex/sso/check/${data.id}`).catch(() => null);
      if (state?.authenticated || state?.token) {
        clearInterval(timer);
        success('Connexion Plex terminee.');
        await load();
      }
    }, 2000);
    setTimeout(() => clearInterval(timer), 180000);
  } catch (e) { fail(e); }
}

// Instances Sonarr/Radarr/Prowlarr
const arrInstances = ref([]), arrProfiles = ref([]), arrFolders = ref([]), editingArrId = ref(null);
const showArrModal = ref(false);
const arrDefaults = { name: '', arr_type: 'sonarr', url: '', api_key: '', quality_profile_id: null, root_folder: '', minimum_availability: 'released', is_default: false, enabled: true, indexer_ids: null };
const arrForm = reactive({ ...arrDefaults });
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
async function removeArr(instance) { if (!confirm(`Supprimer ${instance.name} ?`)) return; await api(`/api/arr-instances/${instance.id}`, { method: 'DELETE' }); await loadArr(); }

// Clients de telechargement
const clients = ref([]), editingClientId = ref(null);
const showClientModal = ref(false);
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
async function removeClient(client) { if (!confirm(`Supprimer ${client.name} ?`)) return; await api(`/api/download-clients/${client.id}`, { method: 'DELETE' }); await loadClients(); }

onMounted(() => { loadArr(); loadClients(); });
</script>
