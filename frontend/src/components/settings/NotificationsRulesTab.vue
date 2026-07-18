<template>
  <div class="settings-grid">
    <div class="settings-cards span-two">
      <SettingsCard title="Retention et digest" :icon="Archive" status="active" :collapsible="false">
        <label>Journaux de notifications (jours)<input v-model.number="form.notification_log_retention_days" type="number" min="0" placeholder="0 ou vide = indefini"><small>0 ou vide = conserver indefiniment</small></label>
        <label class="check"><input v-model="form.digest_enabled" type="checkbox"> Digest actif</label>
        <label>Heure du digest<HourInput v-model="form.digest_hour"/></label>
      </SettingsCard>
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
import { Archive, Bell, Megaphone, MessageSquare, Send } from '@lucide/vue';
import { form } from '@/settingsForm';
import SettingsCard from './SettingsCard.vue';
import HourInput from './HourInput.vue';

const channels = [
  { key: 'discord', label: 'Discord', icon: MessageSquare },
  { key: 'telegram', label: 'Telegram', icon: Send },
  { key: 'ntfy', label: 'ntfy', icon: Bell },
  { key: 'gotify', label: 'Gotify', icon: Megaphone },
];
const notificationEvents = [{ key: 'request', label: 'Nouvelle demande' }, { key: 'available', label: 'Disponibilite' }, { key: 'failure', label: 'Echec' }];
</script>
