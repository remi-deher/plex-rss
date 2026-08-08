<template>
  <SettingsCard title="Tautulli" subtitle="Historique Plex et suivi des lectures" :icon="History" :status="form.tautulli_enabled ? 'active' : 'inactive'" :default-open="form.tautulli_enabled">
    <template #actions>
      <ToggleSwitch v-model="form.tautulli_enabled" :label="form.tautulli_enabled ? 'Activé' : 'Désactivé'"/>
    </template>
    <div class="settings-grid two">
      <label class="span-two">URL Tautulli<input v-model.trim="form.tautulli_url" type="url" placeholder="http://tautulli:8181"><small>Adresse de ton instance Tautulli, ex. http://tautulli:8181 en Docker.</small></label>
      <label class="span-two">Clé API<input v-model="form.tautulli_api_key" type="password" :placeholder="secretsPresent.tautulli_api_key?'Clé configurée':'Clé API Tautulli'"><small>Disponible dans Tautulli sous Réglages -&gt; Web Interface -&gt; API.</small></label>
      <label>Historique à conserver (jours)<RetentionDaysInput v-model="form.activity_retention_days" :default-days="365" placeholder="365"/><small>Sessions plus anciennes supprimées automatiquement.</small></label>
      <label class="collection-toggle span-two" :class="{ active: form.activity_anonymize_ips }">
        <input v-model="form.activity_anonymize_ips" type="checkbox" role="switch" :aria-checked="String(form.activity_anonymize_ips)">
        <span class="collection-toggle-copy">
          <strong>Anonymiser les adresses IP</strong>
          <small v-if="form.activity_anonymize_ips">Activée — le dernier segment de l'IP est remplacé par 0 avant stockage (ex. 192.168.1.42 devient 192.168.1.0) ; la géolocalisation reste approximative, l'adresse exacte n'est jamais enregistrée.</small>
          <small v-else>Désactivée — l'adresse IP complète de chaque lecture est conservée telle quelle dans l'historique.</small>
        </span>
        <span class="collection-state">{{ form.activity_anonymize_ips ? 'Activée' : 'Désactivée' }}</span>
      </label>
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
    <p class="connection-result">
      <strong>Importer</strong> récupère les sessions passées depuis Tautulli (jusqu'à la limite choisie).
      <strong>Normaliser l'historique</strong> recalcule la décision de lecture, la progression et le temps regardé des sessions déjà importées.
      <strong>Recalculer les lieux</strong> complète la localisation des sessions qui n'en ont pas, à partir de leur IP.
    </p>
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
import RetentionDaysInput from '../RetentionDaysInput.vue';

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
.card-actions{display:flex;flex-wrap:wrap;gap: var(--space-2);align-items:center;margin-top:4px}.card-actions select{width:auto}.connection-result{margin:0;color:var(--muted);font-size:var(--fs-sm);line-height:1.5}.collection-toggle{display:grid!important;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap: var(--space-3);padding:15px;border:1px solid rgba(239,68,68,.35);border-radius:var(--radius-md);background:rgba(239,68,68,.06);cursor:pointer}.collection-toggle.active{border-color:rgba(34,197,94,.35);background:rgba(34,197,94,.07)}.collection-toggle>input{width:20px;height:20px;margin:0;accent-color:var(--accent)}.collection-toggle-copy{display:grid;gap: var(--space-1)}.collection-toggle-copy strong{font-size:var(--fs-md)}.collection-toggle-copy small{color:color-mix(in srgb,var(--text) 72%,transparent);font-size:var(--fs-sm);line-height:1.45}.collection-state{padding:5px 9px;border-radius:var(--radius-pill);background:rgba(239,68,68,.13);color:#f87171;font-size:var(--fs-xs);font-weight:750}.collection-toggle.active .collection-state{background:rgba(34,197,94,.13);color:var(--success)}@media(max-width:640px){.card-actions{display:grid;grid-template-columns:1fr 1fr}.card-actions>*{width:100%!important;min-height:44px}.collection-toggle{grid-template-columns:auto minmax(0,1fr)}.collection-state{grid-column:2;justify-self:start}}@media(max-width:420px){.card-actions{grid-template-columns:1fr}}
</style>
