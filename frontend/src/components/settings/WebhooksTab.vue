<template>
  <div class="settings-grid">
    <div class="settings-cards span-two">
      <SettingsCard
        title="Configuration des Webhooks"
        subtitle="Les webhooks permettent aux applications tierces de notifier Plex-RSS en temps reel."
        :icon="Link"
        :status="form.webhook_secret ? 'active' : 'inactive'"
        :collapsible="false"
      >
        <div v-if="!form.webhook_secret" class="notice warning">
          <p>Le secret webhook n'est pas configuré. L'authentification des webhooks entrants est désactivée.</p>
          <button class="primary" @click="generateWebhookSecret">Générer un secret</button>
        </div>

        <div v-else class="webhook-list">
          <div v-for="svc in ['plex', 'radarr', 'sonarr']" :key="svc" class="webhook-item">
            <div class="webhook-title">
              <strong>{{ svc.charAt(0).toUpperCase() + svc.slice(1) }}</strong>
            </div>
            <div class="webhook-url">
              <input type="text" readonly :aria-label="`URL webhook ${svc}`" :value="`${baseUrl}/webhook/${svc}?secret=${form.webhook_secret}`">
              <button class="icon-button" @click="copyWebhook(svc)" title="Copier" aria-label="Copier"><Copy/></button>
              <button v-if="svc === 'sonarr' || svc === 'radarr'" class="secondary" @click="configureWebhook(svc)" :disabled="configuringWebhook === svc">
                <RefreshCw v-if="configuringWebhook === svc" class="spin" />
                <span v-else>Configurer automatiquement</span>
              </button>
              <button class="secondary" @click="testWebhook(svc)" :disabled="testingWebhook === svc">
                <RefreshCw v-if="testingWebhook === svc" class="spin" />
                <span v-else>Tester</span>
              </button>
            </div>
            <div v-if="configureStatus[svc]" class="webhook-status" :class="{ 'status-ok': configureStatus[svc].success, 'status-error': !configureStatus[svc].success }">
              <span v-if="configureStatus[svc].success"><Check /> {{ configureStatus[svc].message }}</span>
              <span v-else>Erreur : {{ configureStatus[svc].message }}</span>
            </div>
            <div v-if="webhookStatus[svc]" class="webhook-status" :class="{ 'status-ok': webhookStatus[svc].success, 'status-error': !webhookStatus[svc].success }">
              <span v-if="webhookStatus[svc].success"><Check /> {{ webhookStatus[svc].message || 'Succès' }}</span>
              <span v-else>Erreur : {{ webhookStatus[svc].message }}</span>
            </div>
          </div>

          <div class="actions" style="margin-top: 2rem;">
            <button class="secondary" @click="generateWebhookSecret">Regénérer le secret</button>
          </div>
        </div>
      </SettingsCard>

      <SettingsCard title="Token API" subtitle="Jeton pour les appels programmatiques a l'API Plexarr" :icon="KeyRound" status="neutral" :collapsible="false">
        <template #actions>
          <button class="icon-button" title="Actualiser" aria-label="Actualiser" @click.stop="loadToken"><RefreshCw/></button>
        </template>
        <code class="secret-box">{{ apiToken || (tokenActive ? 'Actif (valeur masquee)' : 'Aucun token genere') }}</code>
        <p class="hint">Ce token donne un acces complet a l'API Plexarr (creation de demandes, lecture des utilisateurs, etc.) — a passer en en-tete <code>Authorization: Bearer …</code>. Il n'est affiche qu'une seule fois a la generation ; regenerez-le si vous le perdez.</p>
        <div class="actions">
          <button class="secondary" @click="generateToken"><KeyRound/>Generer</button>
          <button class="secondary danger" @click="deleteToken"><Trash2/>Revoquer</button>
        </div>
      </SettingsCard>
    </div>
  </div>
  <ConfirmModal v-bind="confirmDialog" @cancel="resolveConfirm(false)" @confirm="resolveConfirm(true)" />
</template>
<script setup>
import { onMounted, reactive, ref } from 'vue';
import { Check, Copy, KeyRound, Link, RefreshCw, Trash2 } from '@lucide/vue';
import { api } from '@/api';
import { form, success, fail } from '@/settingsForm';
import SettingsCard from './SettingsCard.vue';
import ConfirmModal from '../ConfirmModal.vue';
import { useConfirm } from '@/composables/useConfirm';

const baseUrl = window.location.origin;
const webhookStatus = reactive({ plex: null, radarr: null, sonarr: null });
const configureStatus = reactive({ plex: null, radarr: null, sonarr: null });
const testingWebhook = ref(null);
const configuringWebhook = ref(null);
const { dialog: confirmDialog, askConfirm, resolveConfirm } = useConfirm();

const apiToken = ref('');
const tokenActive = ref(false);
async function loadToken() {
  const token = await api('/api/settings/token').catch(() => ({}));
  tokenActive.value = Boolean(token.active);
}
async function generateToken() {
  const data = await api('/api/settings/token', { method: 'POST', body: JSON.stringify({ scopes: ['*'] }) });
  apiToken.value = data.api_token;
  tokenActive.value = true;
}
async function deleteToken() {
  await api('/api/settings/token', { method: 'DELETE' });
  apiToken.value = '';
  tokenActive.value = false;
}
onMounted(loadToken);

async function generateWebhookSecret() {
  if (form.webhook_secret && !await askConfirm({ title: 'Régénérer le secret webhook ?', message: "L’ancien secret sera invalidé et les webhooks actuellement configurés ne fonctionneront plus.", confirmLabel: 'Régénérer', danger: true })) return;
  try {
    const res = await api('/api/settings/webhook-secret', { method: 'POST' });
    form.webhook_secret = res.webhook_secret;
    success('Secret genere avec succes.');
  } catch (e) { fail(e); }
}
async function copyWebhook(svc) {
  const url = `${baseUrl}/webhook/${svc}?secret=${form.webhook_secret}`;
  await navigator.clipboard.writeText(url);
  success('URL copiee dans le presse-papier.');
}
async function configureWebhook(svc) {
  configuringWebhook.value = svc;
  configureStatus[svc] = null;
  try {
    const url = `${baseUrl}/webhook/${svc}?secret=${form.webhook_secret}`;
    const res = await api(`/webhook/configure/${svc}`, { method: 'POST', body: JSON.stringify({ webhook_url: url }) });
    const result = res.results && res.results[0];
    if (result && result.success) {
      configureStatus[svc] = { success: true, message: `Webhook ${svc.charAt(0).toUpperCase() + svc.slice(1)} correctement configuré : ${result.message}` };
      success(`Webhook ${svc} correctement configuré.`);
    } else {
      configureStatus[svc] = { success: false, message: result ? result.message : 'Aucun résultat.' };
    }
  } catch (e) {
    configureStatus[svc] = { success: false, message: e.message };
  } finally {
    configuringWebhook.value = null;
  }
}
async function testWebhook(svc) {
  testingWebhook.value = svc;
  try {
    const res = await api(`/webhook/check-live/${svc}`, { method: 'POST' });
    const result = res.results && res.results[0];
    webhookStatus[svc] = result ? { success: result.success, message: result.message } : { success: true, message: 'Test effectue (pas de resultat precis)' };
  } catch (e) {
    webhookStatus[svc] = { success: false, message: e.message };
  } finally {
    testingWebhook.value = null;
  }
}
</script>
