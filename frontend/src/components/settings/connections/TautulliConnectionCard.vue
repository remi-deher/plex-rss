<template>
  <SettingsCard title="Tautulli" subtitle="Historique Plex et suivi des lectures" :icon="History" :status="form.tautulli_enabled ? 'active' : 'inactive'" :collapsible="false">
    <template #actions>
      <ToggleSwitch v-model="form.tautulli_enabled" :label="form.tautulli_enabled ? 'Activé' : 'Désactivé'"/>
    </template>
    <div class="form-grid">
      <label class="span-two">URL Tautulli<input v-model.trim="form.tautulli_url" type="url" placeholder="http://tautulli:8181"></label>
      <label class="span-two">Clé API<input v-model="form.tautulli_api_key" type="password" :placeholder="secretsPresent.tautulli_api_key?'Clé configurée':'Clé API Tautulli'"></label>
      <label>Historique à conserver (jours)<input v-model.number="form.activity_retention_days" type="number" min="0" placeholder="365"></label>
      <label class="check-field"><input v-model="form.activity_anonymize_ips" type="checkbox"><span><strong>Anonymiser les adresses IP</strong><small>Masque les adresses avant leur stockage.</small></span></label>
      <label class="collection-toggle span-two" :class="{ active: form.live_activity_enabled }">
        <input v-model="form.live_activity_enabled" type="checkbox" role="switch" :aria-checked="String(form.live_activity_enabled)">
        <span class="collection-toggle-copy">
          <strong>Activité Plex en direct</strong>
          <small v-if="form.live_activity_enabled">Activée — les lectures en cours apparaissent sur le tableau de bord et dans Activité Plex.</small>
          <small v-else>Désactivée — aucune lecture en cours ne sera collectée ni affichée.</small>
        </span>
        <span class="collection-state">{{ form.live_activity_enabled ? 'Activée' : 'Désactivée' }}</span>
      </label>
    </div>
    <div class="card-actions">
      <button class="secondary" :disabled="busy" @click="testConnection"><PlugZap/>Tester</button>
      <select v-model.number="importLength"><option :value="500">500 sessions</option><option :value="2000">2 000 sessions</option><option :value="10000">Tout (10 000 max.)</option></select>
      <button class="secondary" :disabled="busy" @click="runImport"><History/>Importer</button>
      <button class="secondary" :disabled="busy" @click="normalizeHistory"><RefreshCw/>Normaliser l'historique</button>
      <button class="secondary" :disabled="busy" @click="recalculateLocations"><MapPinned/>Recalculer les lieux</button>
    </div>
    <p v-if="status" class="connection-result">{{ status }}</p>
    <ConfirmModal v-bind="confirmDialog" @cancel="resolveConfirm(false)" @confirm="resolveConfirm(true)"/>
  </SettingsCard>
</template>

<script setup>
import { ref } from 'vue';
import { History, MapPinned, PlugZap, RefreshCw } from '@lucide/vue';
import { api } from '@/api';
import { form, save, secretsPresent } from '@/settingsForm';
import ConfirmModal from '@/components/ConfirmModal.vue';
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue';
import { useConfirm } from '@/composables/useConfirm';
import SettingsCard from '../SettingsCard.vue';

const busy=ref(false),status=ref(''),importLength=ref(2000);
const {dialog:confirmDialog,askConfirm,resolveConfirm}=useConfirm();
async function testConnection(){
  busy.value=true;status.value='';
  try{await save();const result=await api('/api/playback/tautulli/test',{method:'POST'});status.value=result.message}
  catch(error){status.value=error.message}
  finally{busy.value=false}
}
async function runImport(){
  busy.value=true;status.value='';
  try{await save();const result=await api('/api/playback/tautulli/import',{method:'POST',body:JSON.stringify({length:importLength.value})});status.value=`${result.imported} session(s) importée(s) sur ${result.received}.`}
  catch(error){status.value=error.message}
  finally{busy.value=false}
}
async function normalizeHistory(){
  if(!await askConfirm({
    title:"Normaliser l'historique Tautulli ?",
    message:"Les décisions de lecture, la progression et le temps regardé des anciennes sessions seront recalculés depuis Tautulli.",
    confirmLabel:"Normaliser",
  }))return;
  busy.value=true;status.value='';
  try{
    await save();
    const result=await api('/api/playback/tautulli/normalize',{method:'POST',body:JSON.stringify({length:10000})});
    status.value=`${result.normalized} session(s) corrigée(s) sur ${result.matched} retrouvée(s).`;
  }catch(error){status.value=error.message}
  finally{busy.value=false}
}
async function recalculateLocations(){
  if(!await askConfirm({
    title:"Recalculer les localisations ?",
    message:"Les sessions sans lieu seront complétées à partir de leur IP. Les localisations déjà enregistrées seront conservées.",
    confirmLabel:"Recalculer",
  }))return;
  busy.value=true;status.value='';
  try{
    await save();
    const result=await api('/api/playback/locations/recalculate',{method:'POST'});
    status.value=`${result.updated} session(s) complétée(s), ${result.preserved} localisation(s) conservée(s), pour ${result.addresses} IP distincte(s).`;
  }catch(error){status.value=error.message}
  finally{busy.value=false}
}
</script>

<style scoped>
.card-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:4px}.card-actions select{width:auto}.connection-result{margin:0;color:var(--muted);font-size:13px;line-height:1.5}.check-field{display:flex;align-items:flex-start;gap:10px;padding:13px;border:1px solid var(--border);border-radius:11px;background:var(--surface-2)}.check-field input{width:auto;margin-top:2px}.check-field>span{display:grid;gap:3px}.check-field small{color:var(--muted);font-weight:400}.collection-toggle{display:grid!important;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:13px;padding:15px;border:1px solid rgba(239,68,68,.35);border-radius:12px;background:rgba(239,68,68,.06);cursor:pointer}.collection-toggle.active{border-color:rgba(34,197,94,.35);background:rgba(34,197,94,.07)}.collection-toggle>input{width:20px;height:20px;margin:0;accent-color:var(--accent)}.collection-toggle-copy{display:grid;gap:4px}.collection-toggle-copy strong{font-size:14px}.collection-toggle-copy small{color:color-mix(in srgb,var(--text) 72%,transparent);font-size:12px;line-height:1.45}.collection-state{padding:5px 9px;border-radius:999px;background:rgba(239,68,68,.13);color:#f87171;font-size:11px;font-weight:750}.collection-toggle.active .collection-state{background:rgba(34,197,94,.13);color:var(--success)}@media(max-width:640px){.card-actions{display:grid;grid-template-columns:1fr 1fr}.card-actions>*{width:100%!important;min-height:44px}.collection-toggle{grid-template-columns:auto minmax(0,1fr)}.collection-state{grid-column:2;justify-self:start}}@media(max-width:420px){.card-actions{grid-template-columns:1fr}}
</style>
