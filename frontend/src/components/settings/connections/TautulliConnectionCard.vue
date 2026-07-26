<template>
  <section class="settings-card">
    <div class="settings-card-head">
      <div><span class="eyebrow">Historique Plex</span><h2>Tautulli</h2><p>Importer les anciennes lectures dans Plexarr.</p></div>
      <label class="switch"><input v-model="form.tautulli_enabled" type="checkbox"><span></span></label>
    </div>
    <div class="form-grid">
      <label class="span-two">URL Tautulli<input v-model.trim="form.tautulli_url" type="url" placeholder="http://tautulli:8181"></label>
      <label class="span-two">Clé API<input v-model="form.tautulli_api_key" type="password" :placeholder="secretsPresent.tautulli_api_key?'Clé configurée':'Clé API Tautulli'"></label>
      <label>Historique à conserver (jours)<input v-model.number="form.activity_retention_days" type="number" min="0" placeholder="365"></label>
      <label class="check-field"><input v-model="form.activity_anonymize_ips" type="checkbox">Anonymiser les adresses IP</label>
      <label class="check-field span-two"><input v-model="form.live_activity_enabled" type="checkbox">Collecter les lectures Plex en direct</label>
    </div>
    <div class="card-actions">
      <button class="secondary" :disabled="busy" @click="testConnection"><PlugZap/>Tester</button>
      <select v-model.number="importLength"><option :value="500">500 sessions</option><option :value="2000">2 000 sessions</option><option :value="10000">Tout (10 000 max.)</option></select>
      <button class="secondary" :disabled="busy" @click="runImport"><History/>Importer</button>
    </div>
    <p v-if="status" class="connection-result">{{ status }}</p>
  </section>
</template>

<script setup>
import { ref } from 'vue';
import { History, PlugZap } from '@lucide/vue';
import { api } from '@/api';
import { form, save, secretsPresent } from '@/settingsForm';

const busy=ref(false),status=ref(''),importLength=ref(2000);
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
</script>

<style scoped>
.card-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:12px}.card-actions select{width:auto}.connection-result{margin:10px 0 0;color:var(--muted);font-size:12px}.check-field{display:flex;align-items:center;gap:8px;padding-top:22px}.check-field input{width:auto}
</style>
