<template>
  <div class="settings-grid">
    <div class="settings-cards span-two">
      <SettingsCard title="Email" subtitle="Envoi des notifications par email (demandes, disponibilite, echecs) via un serveur SMTP." :icon="Mail" :status="form.email_enabled ? 'active' : 'inactive'" :collapsible="false">
        <template #actions>
          <button class="secondary" :disabled="!form.email_enabled" @click.stop="testSmtp"><PlugZap/>Tester</button>
        </template>
        <label class="check"><input v-model="form.email_enabled" type="checkbox"> Activer les emails</label>
        <label>Expediteur<input v-model="form.smtp_from" type="email"><small>Adresse "De :" utilisee pour tous les emails envoyes par Plexarr.</small></label>
        <label>Email administrateur<input v-model="form.admin_notification_email"><small>Destinataire des alertes techniques (imports bloques, echecs) — distinct des notifications envoyees aux utilisateurs.</small></label>
        <label class="check"><input v-model="form.notify_import_blocked" type="checkbox"> Alerter l'administrateur en cas d'import Sonarr bloqué</label>
        <small class="check-hint">Distinct d'un échec de transmission — se déclenche souvent avec les épisodes « TBA », désactivez si trop fréquent</small>
        <label>URL publique de l'application<input v-model="form.public_base_url" type="url" placeholder="https://plexarr.mondomaine.fr"><small>Utilisee pour le lien vers la politique de confidentialite dans le pied de page des emails ; laisser vide pour ne pas l'afficher</small></label>
      </SettingsCard>

      <EmailProvidersCard/>

      <SettingsCard
        v-for="channel in channels"
        :key="channel.key"
        :title="channel.label"
        :subtitle="channel.subtitle"
        :icon="channel.icon"
        :status="form[`${channel.key}_enabled`] ? 'active' : 'inactive'"
        :collapsible="false"
      >
        <template #actions>
          <button class="secondary" :disabled="!form[`${channel.key}_enabled`]" @click.stop="testSaved(`/api/test/${channel.key}`)"><PlugZap/>Tester</button>
        </template>
        <label class="check"><input v-model="form[`${channel.key}_enabled`]" type="checkbox"> Activer</label>
        <template v-if="channel.key==='discord'">
          <label>Webhook<input v-model="form.discord_webhook_url" type="password" placeholder="Laisser vide pour conserver"><small>Sur le serveur Discord : Parametres du salon -&gt; Integrations -&gt; Webhooks -&gt; Nouveau webhook -&gt; Copier l'URL.</small></label>
        </template>
        <template v-else-if="channel.key==='telegram'">
          <label>Token bot<input v-model="form.telegram_bot_token" type="password"><small>Cree un bot via @BotFather sur Telegram, qui te donne ce token.</small></label>
          <label>Chat ID<input v-model="form.telegram_chat_id"><small>Identifiant numerique du salon/canal a notifier — envoie un message au bot puis recupere-le via @userinfobot ou l'API Telegram.</small></label>
        </template>
        <template v-else-if="channel.key==='ntfy'">
          <label>URL<input v-model="form.ntfy_url"><small>Serveur ntfy, ex. https://ntfy.sh (public) ou l'adresse de ton instance auto-hebergee.</small></label>
          <label>Topic<input v-model="form.ntfy_topic"><small>Nom du canal ntfy auquel s'abonner dans l'application pour recevoir ces notifications.</small></label>
          <label>Token<input v-model="form.ntfy_token" type="password"><small>Uniquement si le topic est protege par un token d'acces ntfy.</small></label>
        </template>
        <template v-else>
          <label>URL<input v-model="form.gotify_url"><small>Adresse de ton serveur Gotify.</small></label>
          <label>Token<input v-model="form.gotify_token" type="password"><small>Token d'application, cree dans Gotify sous Apps -&gt; Create Application.</small></label>
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
import EmailProvidersCard from './EmailProvidersCard.vue';

const channels = [
  { key: 'discord', label: 'Discord', icon: MessageSquare, subtitle: 'Notifications envoyees dans un salon Discord via un webhook.' },
  { key: 'telegram', label: 'Telegram', icon: Send, subtitle: 'Notifications envoyees par un bot Telegram vers un salon ou canal.' },
  { key: 'ntfy', label: 'ntfy', icon: Bell, subtitle: 'Notifications push via ntfy.sh ou une instance ntfy auto-hebergee.' },
  { key: 'gotify', label: 'Gotify', icon: Megaphone, subtitle: 'Notifications push via un serveur Gotify auto-heberge.' },
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
