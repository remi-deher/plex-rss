<template>
  <div class="settings-grid">
    <div class="settings-cards span-two">
      <SettingsCard title="Watchlist" :icon="Rss" status="active" default-open>
        <label>Intervalle en secondes<input v-model.number="form.poll_interval_seconds" type="number" min="15"></label>
        <label>Priorite<select v-model="form.watchlist_source_priority"><option value="api">API Plex</option><option value="rss">RSS</option></select></label>
        <label class="check"><input v-model="form.watchlist_fallback_enabled" type="checkbox"> Source de repli</label>
        <label class="check"><input v-model="form.require_approval" type="checkbox"> Approbation admin requise</label>
      </SettingsCard>

      <SettingsCard title="Analyse VF" :icon="Languages" :status="form.vff_enabled ? 'active' : 'inactive'">
        <label class="check"><input v-model="form.vff_enabled" type="checkbox"> Analyse active</label>
        <label>Nouvelle analyse (minutes)<input v-model.number="form.vff_recheck_interval_minutes" type="number"></label>
        <label class="check"><input v-model="form.vff_auto_search" type="checkbox"> Recherche automatique</label>
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
      </SettingsCard>

      <SettingsCard title="Conservation" :icon="Archive" status="active">
        <label>Journaux de notifications (jours)<input v-model.number="form.notification_log_retention_days" type="number" min="0" placeholder="0 ou vide = indefini"><small>0 ou vide = conserver indefiniment</small></label>
        <label>Historique de polling (jours)<input v-model.number="form.poll_history_retention_days" type="number" min="0" placeholder="0 ou vide = indefini"><small>0 ou vide = conserver indefiniment</small></label>
        <label class="check"><input v-model="form.digest_enabled" type="checkbox"> Digest actif</label>
        <label>Heure du digest<input v-model.number="form.digest_hour" type="number" min="0" max="23"></label>
        <label>Heure de synchronisation Plex<input v-model.number="form.plex_sync_hour" type="number" min="0" max="23"><small>Heure locale a laquelle la bibliotheque Plex est resynchronisee en entier (1 fois par jour)</small></label>
      </SettingsCard>

      <SettingsCard title="Regles torrent" :icon="Magnet" status="active">
        <label>Mots requis<input v-model="form.torrent_required_keywords"></label>
        <label>Mots interdits<input v-model="form.torrent_forbidden_keywords"></label>
        <label>Taille minimale (Go)<input v-model.number="form.torrent_min_size_gb" type="number"></label>
        <label>Taille maximale (Go)<input v-model.number="form.torrent_max_size_gb" type="number"></label>
        <label>Ratio limite<input v-model.number="form.torrent_ratio_limit" type="number" step="0.1"></label>
        <label>Duree de seed (h)<input v-model.number="form.torrent_seed_time_limit_hours" type="number"></label>
        <label class="check"><input v-model="form.torrent_auto_delete_files" type="checkbox"> Supprimer les fichiers apres seed</label>
      </SettingsCard>
    </div>
  </div>
</template>
<script setup>
import { computed, onMounted, ref } from 'vue';
import { Archive, Languages, Magnet, Rss } from '@lucide/vue';
import { api } from '@/api';
import { form } from '@/settingsForm';
import SettingsCard from './SettingsCard.vue';

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

onMounted(loadPlexSections);
</script>
