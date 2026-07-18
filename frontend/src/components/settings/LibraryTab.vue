<template>
  <div class="settings-grid">
    <div class="settings-cards span-two">
      <SettingsCard title="Watchlist" :icon="Rss" status="active" :collapsible="false">
        <label>Intervalle en secondes<input v-model.number="form.poll_interval_seconds" type="number" min="15"></label>
        <label>Priorite<select v-model="form.watchlist_source_priority"><option value="api">API Plex</option><option value="rss">RSS</option></select></label>
        <label class="check"><input v-model="form.watchlist_fallback_enabled" type="checkbox"> Source de repli</label>
        <label class="check"><input v-model="form.require_approval" type="checkbox"> Approbation admin requise</label>
      </SettingsCard>

      <SettingsCard title="Analyse VF" :icon="Languages" :status="form.vff_enabled ? 'active' : 'inactive'" :collapsible="false">
        <template #actions>
          <button class="icon-button" title="Actualiser" @click.stop="loadVffStatus"><RefreshCw/></button>
        </template>
        <label class="check"><input v-model="form.vff_enabled" type="checkbox"> Analyse active</label>
        <label>Nouvelle analyse<IntervalPresetInput v-model="form.vff_recheck_interval_minutes" :presets="MINUTES_PRESETS"/></label>
        <label class="check"><input v-model="form.vff_auto_search" type="checkbox"> Recherche automatique</label>
        <label>Heure de synchronisation Plex (complete)<TimeOfDayInput v-model:hour="form.plex_sync_hour" v-model:minute="form.plex_sync_minute"/><small>Heure locale a laquelle la bibliotheque Plex est resynchronisee en entier (1 fois par jour) ; un scan incremental (medias recemment ajoutes) tourne en continu toutes les 5 minutes</small></label>
        <div>
          <strong style="display:block;margin-bottom:8px;font-size:13px">Bibliotheques analysees</strong>
          <div v-if="plexSectionsLoading" class="notice">Chargement des bibliotheques Plex...</div>
          <div v-else-if="!plexSections.length" class="notice warning-text">Aucune bibliotheque Plex trouvee. Verifiez la connexion Plex dans l'onglet Connexions.</div>
          <div v-else class="vff-library-picker">
            <div v-for="section in plexSections" :key="section.name" class="vff-library-row">
              <label class="check vff-lib-check">
                <input type="checkbox" :checked="isLibrarySelected(section.name)" @change="toggleLibrary(section.name, section.type, $event.target.checked)">
                <span class="vff-lib-name">{{ section.name }}</span>
                <span class="badge">{{ section.type==='show'?'Serie':'Film' }}</span>
              </label>
              <div v-if="isLibrarySelected(section.name)" class="vff-lib-kind">
                <div class="segmented small">
                  <button :class="{active: getLibraryKind(section.name)==='series'}" @click="setLibraryKind(section.name, 'series')">Serie</button>
                  <button :class="{active: getLibraryKind(section.name)==='movie'}" @click="setLibraryKind(section.name, 'movie')">Film</button>
                  <button :class="{active: getLibraryKind(section.name)==='anime'}" @click="setLibraryKind(section.name, 'anime')">Anime</button>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="status-stack">
          <span>Scan VF : {{ scanStatus.status||scanStatus.state||'inconnu' }}</span>
          <span>Synchronisation Plex : {{ syncStatus.status||syncStatus.state||'inconnue' }}</span>
        </div>
        <div class="actions">
          <button class="secondary" @click="vff('/api/vff/scan?force=true')"><ScanSearch/>Scanner maintenant</button>
          <button class="secondary" @click="vff('/api/vff/sync-plex')"><RefreshCw/>Synchroniser Plex</button>
        </div>
      </SettingsCard>
    </div>
  </div>
</template>
<script setup>
import { computed, onMounted, ref } from 'vue';
import { Languages, RefreshCw, Rss, ScanSearch } from '@lucide/vue';
import { api } from '@/api';
import { form } from '@/settingsForm';
import SettingsCard from './SettingsCard.vue';
import IntervalPresetInput from './IntervalPresetInput.vue';
import TimeOfDayInput from './TimeOfDayInput.vue';

const MINUTES_PRESETS = [
  { label: '10 minutes', value: 10 },
  { label: '15 minutes', value: 15 },
  { label: '30 minutes', value: 30 },
  { label: '1 heure', value: 60 },
  { label: '3 heures', value: 180 },
  { label: '6 heures', value: 360 },
  { label: '12 heures', value: 720 },
  { label: '24 heures', value: 1440 },
];

const plexSections = ref([]);
const plexSectionsLoading = ref(false);
async function loadPlexSections() {
  plexSectionsLoading.value = true;
  try { plexSections.value = await api('/api/plex/sections'); }
  catch (e) { plexSections.value = []; }
  finally { plexSectionsLoading.value = false; }
}

const vffLibraryList = computed({
  get() { try { const raw = form.vff_libraries; if (!raw) return []; const parsed = JSON.parse(raw); return Array.isArray(parsed) ? parsed : []; } catch { return []; } },
  set(arr) { form.vff_libraries = JSON.stringify(arr); },
});
function isLibrarySelected(name) { return vffLibraryList.value.some(x => x.name === name); }
function getLibraryKind(name) { return vffLibraryList.value.find(x => x.name === name)?.kind || 'series'; }
function toggleLibrary(name, plexType, checked) {
  const list = [...vffLibraryList.value];
  if (checked) { const defaultKind = plexType === 'show' ? 'series' : 'movie'; list.push({ name, kind: defaultKind }); }
  else { const idx = list.findIndex(x => x.name === name); if (idx >= 0) list.splice(idx, 1); }
  vffLibraryList.value = list;
}
function setLibraryKind(name, kind) { const list = [...vffLibraryList.value]; const entry = list.find(x => x.name === name); if (entry) entry.kind = kind; vffLibraryList.value = list; }

const scanStatus = ref({});
const syncStatus = ref({});
async function loadVffStatus() {
  [scanStatus.value, syncStatus.value] = await Promise.all([
    api('/api/vff/scan-status').catch(() => ({})),
    api('/api/vff/sync-status').catch(() => ({})),
  ]);
}
async function vff(path) {
  await api(path, { method: 'POST' });
  setTimeout(loadVffStatus, 1000);
}

onMounted(() => { loadPlexSections(); loadVffStatus(); });
</script>
