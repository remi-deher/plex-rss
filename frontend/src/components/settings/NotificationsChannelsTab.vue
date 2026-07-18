<template>
  <div class="settings-grid">
    <div class="settings-cards span-two">
      <SettingsCard title="Email" :icon="Mail" :status="form.email_enabled ? 'active' : 'inactive'" :collapsible="false">
        <template #actions>
          <button class="secondary" :disabled="!form.email_enabled" @click.stop="testSmtp"><PlugZap/>Tester</button>
        </template>
        <label class="check"><input v-model="form.email_enabled" type="checkbox"> Activer les emails</label>
        <label>Serveur SMTP<input v-model="form.smtp_host"></label>
        <label>Port<input v-model.number="form.smtp_port" type="number"></label>
        <label>Utilisateur<input v-model="form.smtp_user"></label>
        <label>Mot de passe<input v-model="form.smtp_password" type="password" placeholder="Laisser vide pour conserver"></label>
        <label>Expediteur<input v-model="form.smtp_from" type="email"></label>
        <label>Email administrateur<input v-model="form.admin_notification_email"></label>
        <label class="check"><input v-model="form.smtp_tls" type="checkbox"> TLS</label>
        <label>URL publique de l'application<input v-model="form.public_base_url" type="url" placeholder="https://plexarr.mondomaine.fr"><small>Utilisee pour le lien vers la politique de confidentialite dans le pied de page des emails ; laisser vide pour ne pas l'afficher</small></label>
      </SettingsCard>

      <SettingsCard
        v-for="channel in channels"
        :key="channel.key"
        :title="channel.label"
        :icon="channel.icon"
        :status="form[`${channel.key}_enabled`] ? 'active' : 'inactive'"
        :collapsible="false"
      >
        <template #actions>
          <button class="secondary" :disabled="!form[`${channel.key}_enabled`]" @click.stop="testSaved(`/api/test/${channel.key}`)"><PlugZap/>Tester</button>
        </template>
        <label class="check"><input v-model="form[`${channel.key}_enabled`]" type="checkbox"> Activer</label>
        <template v-if="channel.key==='discord'">
          <label>Webhook<input v-model="form.discord_webhook_url"></label>
        </template>
        <template v-else-if="channel.key==='telegram'">
          <label>Token bot<input v-model="form.telegram_bot_token" type="password"></label>
          <label>Chat ID<input v-model="form.telegram_chat_id"></label>
        </template>
        <template v-else-if="channel.key==='ntfy'">
          <label>URL<input v-model="form.ntfy_url"></label>
          <label>Topic<input v-model="form.ntfy_topic"></label>
          <label>Token<input v-model="form.ntfy_token" type="password"></label>
        </template>
        <template v-else>
          <label>URL<input v-model="form.gotify_url"></label>
          <label>Token<input v-model="form.gotify_token" type="password"></label>
        </template>
      </SettingsCard>
    </div>
  </div>
</template>
<script setup>
import { Bell, Mail, Megaphone, MessageSquare, PlugZap, Send } from '@lucide/vue';
import { api } from '@/api';
import { form, success, fail, testSaved, save } from '@/settingsForm';
import SettingsCard from './SettingsCard.vue';

const channels = [
  { key: 'discord', label: 'Discord', icon: MessageSquare },
  { key: 'telegram', label: 'Telegram', icon: Send },
  { key: 'ntfy', label: 'ntfy', icon: Bell },
  { key: 'gotify', label: 'Gotify', icon: Megaphone },
];

async function testSmtp() {
  await save();
  const recipient = prompt('Adresse de test', form.admin_notification_email || form.smtp_from);
  if (!recipient) return;
  try {
    const data = await api('/api/test/smtp', { method: 'POST', body: JSON.stringify({ recipient }) });
    success(data.message || 'Email envoye.');
  } catch (e) { fail(e); }
}
</script>
