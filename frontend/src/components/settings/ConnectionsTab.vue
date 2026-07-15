<template>
  <div class="settings-grid">
    <div class="accordion-list span-two">
      <!-- Plex -->
      <div class="accordion-item" :class="{ expanded: expandedSections.plex }">
        <div class="accordion-header" @click="toggleSection('plex')">
          <div class="accordion-title">
            <span class="status-indicator active"></span>
            <h3>Plex</h3>
          </div>
          <div class="accordion-actions" @click.stop>
            <button class="secondary" @click="testSaved('/api/test/plex-api')"><PlugZap/>Tester</button>
            <span class="chevron"><ChevronDown /></span>
          </div>
        </div>
        <div class="accordion-content">
          <div class="accordion-content-inner">
            <label>URL<input v-model="form.plex_url" type="url" placeholder="http://plex:32400"></label>
            <label>Token<input v-model="form.plex_token" type="password" placeholder="Laisser vide pour conserver"></label>
            <label>URL RSS<input v-model="form.plex_rss_url" type="url"></label>
            <label class="check"><input v-model="form.plex_verify_ssl" type="checkbox"> Verifier le certificat TLS</label>
            <div class="actions">
              <button class="secondary" @click="testSaved('/api/test/plex-rss')"><Rss/>Tester le RSS</button>
              <button class="secondary" @click="startPlexSso"><LogIn/>Connexion Plex SSO</button>
            </div>
          </div>
        </div>
      </div>

      <!-- Seer -->
      <div class="accordion-item" :class="{ expanded: expandedSections.seer }">
        <div class="accordion-header" @click="toggleSection('seer')">
          <div class="accordion-title">
            <span class="status-indicator" :class="{ active: form.seer_enabled }"></span>
            <h3>Seer</h3>
          </div>
          <div class="accordion-actions" @click.stop>
            <button class="secondary" :disabled="!form.seer_enabled" @click="testSeer"><PlugZap/>Tester</button>
            <span class="chevron"><ChevronDown /></span>
          </div>
        </div>
        <div class="accordion-content">
          <div class="accordion-content-inner">
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
          </div>
        </div>
      </div>

      <!-- TMDB -->
      <div class="accordion-item" :class="{ expanded: expandedSections.tmdb }">
        <div class="accordion-header" @click="toggleSection('tmdb')">
          <div class="accordion-title">
            <span class="status-indicator" :class="{ active: form.tmdb_enabled }"></span>
            <h3>TMDB</h3>
          </div>
          <div class="accordion-actions" @click.stop>
            <button class="secondary" :disabled="!form.tmdb_enabled" @click="testTmdb"><PlugZap/>Tester</button>
            <span class="chevron"><ChevronDown /></span>
          </div>
        </div>
        <div class="accordion-content">
          <div class="accordion-content-inner">
            <label class="check"><input v-model="form.tmdb_enabled" type="checkbox"> Activer TMDB</label>
            <label>Cle TMDB<input v-model="form.tmdb_api_key" type="password" placeholder="Laisser vide pour conserver"></label>
          </div>
        </div>
      </div>
    </div>

    <section class="panel form-section span-two">
      <div class="panel-head"><h2>Instances Sonarr, Radarr et Prowlarr</h2><button class="icon-button" @click="loadArr"><RefreshCw/></button></div>
      <div class="connection-list">
        <article v-for="instance in arrInstances" :key="instance.id" class="inline-row">
          <div><strong>{{ instance.name }}</strong><span>{{ instance.arr_type }} · {{ instance.url }}</span></div>
          <div class="actions">
            <button class="icon-button" title="Tester" @click="testArr(instance)"><PlugZap/></button>
            <button class="icon-button" title="Modifier" @click="editArr(instance)"><Pencil/></button>
            <button class="icon-button" :title="instance.enabled?'Desactiver':'Activer'" @click="toggleArr(instance)"><Power/></button>
            <button class="icon-button danger" title="Supprimer" @click="removeArr(instance)"><Trash2/></button>
          </div>
        </article>
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
        <button v-if="editingArrId" class="secondary" @click="resetArr">Annuler</button>
      </div>
    </section>

    <section class="panel form-section span-two">
      <div class="panel-head"><h2>Clients de telechargement direct</h2><button class="icon-button" @click="loadClients"><RefreshCw/></button></div>
      <div class="connection-list">
        <article v-for="client in clients" :key="client.id" class="inline-row">
          <div><strong>{{ client.name }}</strong><span>{{ client.client_type }} · {{ client.url }}</span></div>
          <div class="actions">
            <button class="icon-button" @click="testClient(client)"><PlugZap/></button>
            <button class="icon-button" @click="editClient(client)"><Pencil/></button>
            <button class="icon-button" @click="toggleClient(client)"><Power/></button>
            <button class="icon-button danger" @click="removeClient(client)"><Trash2/></button>
          </div>
        </article>
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
        <button class="primary" @click="saveClient"><Save/>{{ editingClientId?'Mettre a jour':'Ajouter' }}</button>
        <button v-if="editingClientId" class="secondary" @click="resetClient">Annuler</button>
      </div>
    </section>
  </div>
</template>
<script setup>
import { onMounted, reactive, ref } from 'vue';
import { ChevronDown, ListRestart, LogIn, Pencil, Plug, PlugZap, Power, RefreshCw, Rss, Save, Trash2 } from '@lucide/vue';
import { api } from '@/api';
import { form, load, success, fail, testSaved } from '@/settingsForm';

const expandedSections = reactive({ plex: false, seer: false, tmdb: false });
function toggleSection(sec) { expandedSections[sec] = !expandedSections[sec]; }

const busy = ref(false);

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
const arrDefaults = { name: '', arr_type: 'sonarr', url: '', api_key: '', quality_profile_id: null, root_folder: '', minimum_availability: 'released', is_default: false, enabled: true, indexer_ids: null };
const arrForm = reactive({ ...arrDefaults });
async function loadArr() { arrInstances.value = await api('/api/arr-instances'); }
function resetArr() { editingArrId.value = null; Object.assign(arrForm, arrDefaults); arrProfiles.value = []; arrFolders.value = []; }
function editArr(instance) { editingArrId.value = instance.id; Object.assign(arrForm, arrDefaults, instance); loadArrOptions(); }
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
const clientDefaults = { name: '', client_type: 'qbittorrent', url: '', username: '', password: '', category: '', tags: '', is_default: false, enabled: true };
const clientForm = reactive({ ...clientDefaults });
async function loadClients() { clients.value = await api('/api/download-clients'); }
function resetClient() { editingClientId.value = null; Object.assign(clientForm, clientDefaults); }
function editClient(client) { editingClientId.value = client.id; Object.assign(clientForm, clientDefaults, client); }
async function saveClient() {
  try {
    await api(editingClientId.value ? `/api/download-clients/${editingClientId.value}` : '/api/download-clients', { method: editingClientId.value ? 'PUT' : 'POST', body: JSON.stringify(clientForm) });
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
