<template>
  <SettingsCard title="Plex" subtitle="Connexion au serveur Plex local — requise pour la bibliotheque, les demandes et la synchronisation VF." :icon="Server" :status="plexStatus" :default-open="true">
    <template #actions>
      <button class="secondary" @click.stop="testSaved('/api/test/plex-api')"><PlugZap/>Tester</button>
    </template>
    <label>URL<input v-model="form.plex_url" type="url" placeholder="http://plex:32400"><small>Adresse locale de ton serveur Plex (pas app.plex.tv), ex. http://192.168.1.10:32400 ou http://plex:32400 en Docker.</small></label>
    <label>Token<input v-model="form.plex_token" type="password" placeholder="Laisser vide pour conserver"><small>Jeton d'authentification Plex (X-Plex-Token). Le plus simple est d'utiliser "Connexion Plex SSO" ci-dessous, qui le recupere automatiquement.</small></label>
    <label>URL Universal Watchlist<input v-model="form.plex_rss_url" type="url" placeholder="https://rss.plex.tv/..."><small>Agrege la watchlist de tous tes amis Plex sans qu'ils aient besoin de se connecter a Plexarr. Necessite un abonnement Plex Pass — genere depuis plex.tv, Reglages du compte -&gt; Watchlist -&gt; Activer le flux RSS.</small></label>
    <label class="check"><input v-model="form.plex_verify_ssl" type="checkbox"> Verifier le certificat TLS</label>
    <div class="actions">
      <button class="secondary" @click="testSaved('/api/test/plex-rss')"><Rss/>Tester l'Universal Watchlist</button>
      <button class="secondary" @click="startPlexSso"><LogIn/>Connexion Plex SSO</button>
    </div>
  </SettingsCard>
</template>

<script setup>
import { computed } from 'vue';
import { LogIn, PlugZap, Rss, Server } from '@lucide/vue';
import { api } from '@/api';
import { form, load, secretsPresent, success, fail, testSaved } from '@/settingsForm';
import SettingsCard from '../SettingsCard.vue';

// secretsPresent.plex_token reflete la config reelle (persistee), contrairement a
// form.plex_token qui est toujours vide juste apres le chargement (voir settingsForm.js).
const plexStatus = computed(() => (form.plex_url && secretsPresent.plex_token ? 'active' : 'inactive'));

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
</script>
