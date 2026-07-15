<template>
  <div class="settings-grid">
    <div class="accordion-list span-two">
      <!-- Email -->
      <div class="accordion-item" :class="{ expanded: expandedSections.email }">
        <div class="accordion-header" @click="toggleSection('email')">
          <div class="accordion-title">
            <span class="status-indicator" :class="{ active: form.email_enabled }"></span>
            <h3>Email</h3>
          </div>
          <div class="accordion-actions" @click.stop>
            <button class="secondary" :disabled="!form.email_enabled" @click="testSmtp"><PlugZap/>Tester</button>
            <span class="chevron"><ChevronDown /></span>
          </div>
        </div>
        <div class="accordion-content">
          <div class="accordion-content-inner">
            <label class="check"><input v-model="form.email_enabled" type="checkbox"> Activer les emails</label>
            <label>Serveur SMTP<input v-model="form.smtp_host"></label>
            <label>Port<input v-model.number="form.smtp_port" type="number"></label>
            <label>Utilisateur<input v-model="form.smtp_user"></label>
            <label>Mot de passe<input v-model="form.smtp_password" type="password" placeholder="Laisser vide pour conserver"></label>
            <label>Expediteur<input v-model="form.smtp_from" type="email"></label>
            <label>Email administrateur<input v-model="form.admin_notification_email"></label>
            <label class="check"><input v-model="form.smtp_tls" type="checkbox"> TLS</label>
          </div>
        </div>
      </div>

      <!-- Discord, Telegram, ntfy, Gotify -->
      <div v-for="channel in channels" :key="channel.key" class="accordion-item" :class="{ expanded: expandedSections[channel.key] }">
        <div class="accordion-header" @click="toggleSection(channel.key)">
          <div class="accordion-title">
            <span class="status-indicator" :class="{ active: form[`${channel.key}_enabled`] }"></span>
            <h3>{{ channel.label }}</h3>
          </div>
          <div class="accordion-actions" @click.stop>
            <button class="secondary" :disabled="!form[`${channel.key}_enabled`]" @click="testSaved(`/api/test/${channel.key}`)"><PlugZap/>Tester</button>
            <span class="chevron"><ChevronDown /></span>
          </div>
        </div>
        <div class="accordion-content">
          <div class="accordion-content-inner">
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
          </div>
        </div>
      </div>
    </div>

    <section class="panel form-section span-two">
      <h2>Evenements et canaux</h2>
      <div class="event-matrix">
        <div></div><strong>Email</strong><strong>Discord</strong><strong>Telegram</strong><strong>ntfy</strong><strong>Gotify</strong>
        <template v-for="event in notificationEvents" :key="event.key">
          <strong>{{ event.label }}</strong>
          <label class="check"><input v-model="form[`email_on_${event.key}`]" type="checkbox"></label>
          <label v-for="channel in channels" :key="channel.key" class="check"><input v-model="form[`${channel.key}_send_${event.key}`]" type="checkbox"></label>
        </template>
      </div>
      <label class="check"><input v-model="form.email_on_vf_available" type="checkbox"> Email lors d'une amelioration VO vers VF</label>
      <div class="settings-grid two">
        <label class="check"><input v-model="form.movie_notify_language" type="checkbox"> Distinguer VO/VF pour les films</label>
        <label class="check"><input v-model="form.series_notify_language" type="checkbox"> Distinguer VO/VF pour les series</label>
        <label>Granularite series
          <select v-model="form.series_notify_granularity">
            <option value="minimal">Serie complete</option>
            <option value="jalons">Debut et fin de saison</option>
            <option value="tout">Chaque episode</option>
          </select>
        </label>
      </div>
    </section>
  </div>
</template>
<script setup>
import { reactive } from 'vue';
import { ChevronDown, PlugZap } from '@lucide/vue';
import { api } from '@/api';
import { form, success, fail, testSaved, save } from '@/settingsForm';

const channels = [{ key: 'discord', label: 'Discord' }, { key: 'telegram', label: 'Telegram' }, { key: 'ntfy', label: 'ntfy' }, { key: 'gotify', label: 'Gotify' }];
const notificationEvents = [{ key: 'request', label: 'Nouvelle demande' }, { key: 'available', label: 'Disponibilite' }, { key: 'failure', label: 'Echec' }];

const expandedSections = reactive({ email: false, discord: false, telegram: false, ntfy: false, gotify: false });
function toggleSection(sec) { expandedSections[sec] = !expandedSections[sec]; }

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
