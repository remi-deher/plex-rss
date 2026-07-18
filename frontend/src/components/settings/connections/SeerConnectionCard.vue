<template>
  <SettingsCard title="Seer" subtitle="Overseerr / Jellyseerr" :icon="Radar" :status="form.seer_enabled ? 'active' : 'inactive'" :collapsible="false">
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
</template>

<script setup>
import { PlugZap, Radar } from '@lucide/vue';
import { api } from '@/api';
import { form, success, fail } from '@/settingsForm';
import SettingsCard from '../SettingsCard.vue';

async function testSeer() {
  try {
    const data = await api('/api/test/seer', { method: 'POST', body: JSON.stringify({ seer_url: form.seer_url, seer_api_key: form.seer_api_key }) });
    success(data.message || 'Connexion valide.');
  } catch (e) { fail(e); }
}
</script>
