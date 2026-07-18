<template>
  <SettingsCard title="TMDB" subtitle="Metadonnees et posters" :icon="Clapperboard" :status="form.tmdb_enabled ? 'active' : 'inactive'" :collapsible="false">
    <template #actions>
      <button class="secondary" :disabled="!form.tmdb_enabled" @click.stop="testTmdb"><PlugZap/>Tester</button>
    </template>
    <label class="check"><input v-model="form.tmdb_enabled" type="checkbox"> Activer TMDB</label>
    <label>Cle TMDB<input v-model="form.tmdb_api_key" type="password" placeholder="Laisser vide pour conserver"></label>
  </SettingsCard>
</template>

<script setup>
import { Clapperboard, PlugZap } from '@lucide/vue';
import { api } from '@/api';
import { form, success, fail } from '@/settingsForm';
import SettingsCard from '../SettingsCard.vue';

async function testTmdb() {
  try {
    const data = await api('/api/test/tmdb', { method: 'POST', body: JSON.stringify({ tmdb_api_key: form.tmdb_api_key }) });
    success(data.message || 'Connexion valide.');
  } catch (e) { fail(e); }
}
</script>
