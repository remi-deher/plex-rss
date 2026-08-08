<template>
  <SettingsCard title="TMDB" subtitle="Fournit les fiches, affiches et suggestions de l'onglet Découvrir." :icon="Clapperboard" :status="form.tmdb_enabled ? 'active' : 'inactive'" :default-open="form.tmdb_enabled">
    <template #actions>
      <button class="secondary" :disabled="!form.tmdb_enabled" @click.stop="testTmdb"><PlugZap/>Tester</button>
    </template>
    <label class="check"><input v-model="form.tmdb_enabled" type="checkbox"> Activer TMDB</label>
    <label>Clé TMDB<input v-model="form.tmdb_api_key" type="password" placeholder="Laisser vide pour conserver"><small>Clé API (v3) gratuite, a generer sur themoviedb.org -&gt; Parametres -&gt; API.</small></label>
    <label>Région de découverte
      <input v-model="form.tmdb_region" maxlength="2" placeholder="FR" @input="form.tmdb_region = form.tmdb_region.toUpperCase()">
      <small>Code pays ISO 3166-1 (ex. FR) utilisé pour les dates de sortie, les plateformes de streaming et les tendances régionales affichées dans Découvrir.</small>
    </label>
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
