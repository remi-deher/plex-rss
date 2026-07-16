<template>
  <SettingsCard title="Plex" :icon="Server" :status="plexStatus" default-open>
    <template #actions>
      <button class="secondary" @click.stop="testSaved('/api/test/plex-api')"><PlugZap/>Tester</button>
    </template>
    <label>URL<input v-model="form.plex_url" type="url" placeholder="http://plex:32400"></label>
    <label>Token<input v-model="form.plex_token" type="password" placeholder="Laisser vide pour conserver"></label>
    <label>URL RSS<input v-model="form.plex_rss_url" type="url"></label>
    <label class="check"><input v-model="form.plex_verify_ssl" type="checkbox"> Verifier le certificat TLS</label>
    <div class="actions">
      <button class="secondary" @click="testSaved('/api/test/plex-rss')"><Rss/>Tester le RSS</button>
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
