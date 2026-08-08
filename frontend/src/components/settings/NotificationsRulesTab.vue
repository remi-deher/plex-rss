<template>
  <div class="settings-grid">
    <div class="settings-cards span-two">
      <SettingsCard title="Retention et digest" subtitle="Duree de conservation des journaux de notifications, et recapitulatif quotidien par email." :icon="Archive" status="active" :collapsible="false">
        <label>Journaux de notifications (jours)<RetentionDaysInput v-model="form.notification_log_retention_days" :default-days="30"/></label>
        <label class="check"><input v-model="form.digest_enabled" type="checkbox"> Digest actif</label>
        <small class="check-hint">Envoie un recapitulatif quotidien par email, a l'heure choisie ci-dessous, aux utilisateurs ayant active le digest dans leurs preferences — au lieu de recevoir chaque notification individuellement.</small>
        <label>Heure du digest<TimeOfDayInput v-model:hour="form.digest_hour" v-model:minute="form.digest_minute"/></label>
      </SettingsCard>
    </div>

    <section class="panel form-section span-two">
      <h2>Evenements et canaux</h2>
      <p class="hint">Choisis, pour chaque type d'evenement, quels canaux doivent envoyer une notification. Un canal doit d'abord etre active dans l'onglet Canaux pour que sa case ici ait un effet.</p>
      <div class="event-matrix">
        <div></div><strong>Email</strong><strong>Discord</strong><strong>Telegram</strong><strong>ntfy</strong><strong>Gotify</strong>
        <template v-for="event in notificationEvents" :key="event.key">
          <strong>{{ event.label }}</strong>
          <label class="check"><input v-model="form[`email_on_${event.key}`]" type="checkbox"></label>
          <label v-for="channel in channels" :key="channel.key" class="check"><input v-model="form[`${channel.key}_send_${event.key}`]" type="checkbox"></label>
        </template>
      </div>
      <label class="check"><input v-model="form.email_on_vf_available" type="checkbox"> Email lors d'une amelioration VO vers VF</label>
      <small class="check-hint">Notifie separement quand un media deja disponible en VO recoit sa VF, en plus de la notification de disponibilite initiale.</small>
      <div class="settings-grid two">
        <label class="check"><input v-model="form.movie_notify_language" type="checkbox"> Distinguer VO/VF pour les films</label>
        <label class="check"><input v-model="form.series_notify_language" type="checkbox"> Distinguer VO/VF pour les series</label>
        <label>Granularite series
          <select v-model="form.series_notify_granularity">
            <option value="minimal">Serie complete</option>
            <option value="jalons">Debut et fin de saison</option>
            <option value="tout">Chaque episode</option>
          </select>
          <small>A quel rythme une serie en cours declenche une notification : une seule fois a la fin, a chaque debut/fin de saison, ou a chaque episode disponible.</small>
        </label>
      </div>
    </section>
  </div>
</template>
<script setup>
import { Archive, Bell, Megaphone, MessageSquare, Send } from '@lucide/vue';
import { form } from '@/settingsForm';
import SettingsCard from './SettingsCard.vue';
import TimeOfDayInput from './TimeOfDayInput.vue';
import RetentionDaysInput from './RetentionDaysInput.vue';

const channels = [
  { key: 'discord', label: 'Discord', icon: MessageSquare },
  { key: 'telegram', label: 'Telegram', icon: Send },
  { key: 'ntfy', label: 'ntfy', icon: Bell },
  { key: 'gotify', label: 'Gotify', icon: Megaphone },
];
const notificationEvents = [{ key: 'request', label: 'Nouvelle demande' }, { key: 'available', label: 'Disponibilite' }, { key: 'failure', label: 'Echec' }];
</script>
