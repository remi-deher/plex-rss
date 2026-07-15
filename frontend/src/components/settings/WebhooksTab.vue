<template>
  <div class="settings-grid">
    <section class="panel form-section span-two">
      <h2>Configuration des Webhooks</h2>
      <p>Les webhooks permettent aux applications tierces de notifier Plex-RSS en temps réel.</p>

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
            <input type="text" readonly :value="`${baseUrl}/webhook/${svc}?secret=${form.webhook_secret}`">
            <button class="icon-button" @click="copyWebhook(svc)" title="Copier"><Copy/></button>
            <button class="secondary" @click="testWebhook(svc)" :disabled="testingWebhook === svc">
              <RefreshCw v-if="testingWebhook === svc" class="spin" />
              <span v-else>Tester</span>
            </button>
          </div>
          <div v-if="webhookStatus[svc]" class="webhook-status" :class="{ 'status-ok': webhookStatus[svc].success, 'status-error': !webhookStatus[svc].success }">
            <span v-if="webhookStatus[svc].success"><Check /> {{ webhookStatus[svc].message || 'Succès' }}</span>
            <span v-else>Erreur : {{ webhookStatus[svc].message }}</span>
          </div>
        </div>

        <div class="actions" style="margin-top: 2rem;">
          <button class="secondary danger" @click="revokeWebhookSecret">Révoquer le secret</button>
          <button class="secondary" @click="generateWebhookSecret">Regénérer le secret</button>
        </div>
      </div>
    </section>
  </div>
</template>
<script setup>
import { reactive, ref } from 'vue';
import { Check, Copy, RefreshCw } from '@lucide/vue';
import { api } from '@/api';
import { form, success, fail } from '@/settingsForm';

const baseUrl = window.location.origin;
const webhookStatus = reactive({ plex: null, radarr: null, sonarr: null });
const testingWebhook = ref(null);

async function generateWebhookSecret() {
  if (form.webhook_secret && !confirm("Generer un nouveau secret annulera l'ancien et cassera les webhooks configures. Continuer ?")) return;
  try {
    const res = await api('/api/settings/webhook-secret', { method: 'POST' });
    form.webhook_secret = res.webhook_secret;
    success('Secret genere avec succes.');
  } catch (e) { fail(e); }
}
async function revokeWebhookSecret() {
  if (!confirm("Voulez-vous vraiment desactiver l'authentification des webhooks entrants ?")) return;
  try {
    await api('/api/settings/webhook-secret', { method: 'DELETE' });
    form.webhook_secret = '';
    success('Secret revoque.');
  } catch (e) { fail(e); }
}
async function copyWebhook(svc) {
  const url = `${baseUrl}/webhook/${svc}?secret=${form.webhook_secret}`;
  await navigator.clipboard.writeText(url);
  success('URL copiee dans le presse-papier.');
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
