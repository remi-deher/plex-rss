<template>
  <div class="settings-grid">
    <div class="settings-cards span-two">
      <SettingsCard title="Export et sauvegarde" :icon="HardDriveDownload" status="neutral" :collapsible="false">
        <label class="check"><input v-model="includeSecrets" type="checkbox"> Inclure les identifiants</label>
        <div class="actions">
          <a class="secondary" :href="includeSecrets?'/api/export?include_secrets=true':'/api/export'"><Download/>Exporter en JSON</a>
          <a class="secondary" href="/api/backup/db"><HardDriveDownload/>Backup complet</a>
        </div>
        <p class="warning-text">Ces fichiers peuvent contenir des secrets.</p>
      </SettingsCard>

      <SettingsCard title="Importer un export JSON" :icon="Upload" status="neutral" :collapsible="false">
        <input ref="jsonInput" type="file" accept=".json">
        <div class="actions">
          <button class="secondary" :disabled="busy" @click="importJson"><Upload/>Fusionner les donnees</button>
        </div>
      </SettingsCard>

      <SettingsCard title="Ancienne base SQLite" :icon="DatabaseZap" status="neutral" :collapsible="false">
        <input ref="sqliteInput" type="file" accept=".db,.sqlite,.sqlite3" @change="resetInspection">
        <div class="actions">
          <button class="secondary" :disabled="busy" @click="inspectSqlite"><Search/>Inspecter</button>
        </div>
        <div v-if="inspection" class="migration-summary">
          <strong>{{ inspection.total_rows.toLocaleString() }} lignes</strong>
          <span>{{ inspection.populated_tables }} tables · integrite {{ inspection.integrity }}</span>
          <div class="table-badges">
            <span v-for="(count,name) in populatedTables" :key="name" class="badge">{{ name }} : {{ count.toLocaleString() }}</span>
          </div>
        </div>
        <template v-if="inspection">
          <p class="warning-text">Une sauvegarde PostgreSQL sera creee avant le remplacement.</p>
          <label>Confirmation<input v-model="confirmation" class="mono" placeholder="REMPLACER"></label>
          <button class="primary danger-button" :disabled="busy||confirmation!=='REMPLACER'" @click="migrateSqlite"><DatabaseZap/>Remplacer</button>
        </template>
      </SettingsCard>

      <SettingsCard title="Medias supprimes" :icon="Trash2" status="neutral" :collapsible="false">
        <p>
          Ces medias ont ete deliberement supprimes par un admin. Toute nouvelle demande
          pour l'un d'eux (watchlist, requete manuelle) sera forcee en attente
          d'approbation, meme si l'auto-approbation est activee.
        </p>
        <p v-if="!deletedLog.length">Aucun media dans ce journal.</p>
        <div v-for="entry in deletedLog" :key="entry.id" class="detail-row">
          <div>
            <strong>{{ entry.title }}</strong><br>
            <small>{{ entry.media_type==='show'?'Serie':'Film' }} · supprime le {{ formatDate(entry.deleted_at) }}{{ entry.deleted_by ? ` par ${entry.deleted_by}` : '' }}</small>
          </div>
          <button class="secondary" :disabled="busy" @click="forgetEntry(entry.id)">Oublier</button>
        </div>
      </SettingsCard>
    </div>
  </div>
</template>
<script setup>
import { computed, onMounted, ref } from 'vue';
import { DatabaseZap, Download, HardDriveDownload, Search, Trash2, Upload } from '@lucide/vue';
import { api } from '@/api';
import { load, success, fail } from '@/settingsForm';
import SettingsCard from './SettingsCard.vue';

const busy = ref(false), includeSecrets = ref(false);
const jsonInput = ref(null), sqliteInput = ref(null), inspection = ref(null), confirmation = ref('');
const populatedTables = computed(() => Object.fromEntries(Object.entries(inspection.value?.tables || {}).filter(([, count]) => count > 0)));

const deletedLog = ref([]);
function formatDate(value) {
  return value ? new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium' }).format(new Date(value)) : '-';
}
async function loadDeletedLog() {
  deletedLog.value = await api('/api/requests/deleted-log').catch(() => []);
}
async function forgetEntry(id) {
  busy.value = true;
  try {
    await api(`/api/requests/deleted-log/${id}`, { method: 'DELETE' });
    await loadDeletedLog();
  } catch (e) { fail(e); } finally { busy.value = false; }
}
onMounted(loadDeletedLog);

async function upload(path, file, extra = {}) {
  const body = new FormData();
  body.append('file', file);
  for (const [key, value] of Object.entries(extra)) body.append(key, value);
  const response = await fetch(path, { method: 'POST', credentials: 'same-origin', body });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}
async function importJson() {
  const file = jsonInput.value?.files?.[0];
  if (!file) return;
  busy.value = true;
  try {
    const data = await upload('/api/import', file);
    success(`Import termine : ${data.stats.users_upserted} utilisateurs.`);
    await load();
  } catch (e) { fail(e); } finally { busy.value = false; }
}
function resetInspection() { inspection.value = null; confirmation.value = ''; }
async function inspectSqlite() {
  const file = sqliteInput.value?.files?.[0];
  if (!file) return;
  busy.value = true;
  try {
    inspection.value = await upload('/api/migration/sqlite/inspect', file);
    success('Base SQLite valide.');
  } catch (e) { fail(e); } finally { busy.value = false; }
}
async function migrateSqlite() {
  const file = sqliteInput.value?.files?.[0];
  if (!file || confirmation.value !== 'REMPLACER') return;
  busy.value = true;
  try {
    const data = await upload('/api/migration/sqlite', file, { confirm: confirmation.value });
    success(`Migration terminee : ${data.report.copied_rows.toLocaleString()} lignes.`);
    setTimeout(() => location.assign('/dashboard'), 1500);
  } catch (e) { fail(e); } finally { busy.value = false; }
}
</script>
