<template>
  <div class="settings-grid">
    <div class="settings-cards span-two">
      <SettingsCard
        title="RGPD / confidentialité"
        subtitle="Identité affichée sur la page publique /privacy comme responsable de traitement."
        :icon="ShieldCheck"
        :status="form.gdpr_contact_email ? 'active' : 'inactive'"
        :collapsible="false"
      >
        <div v-if="!form.gdpr_contact_email" class="notice warning">
          Sans contact renseigné, la page de confidentialité ne peut pas indiquer à qui
          s'adresser pour exercer ses droits (accès, rectification, suppression...).
        </div>
        <label>Nom du responsable de traitement<input v-model="form.gdpr_contact_name" placeholder="Jean Dupont"></label>
        <label>Email de contact<input v-model="form.gdpr_contact_email" type="email" placeholder="contact@exemple.fr"></label>
      </SettingsCard>

      <SettingsCard
        title="Rétention des données personnelles"
        subtitle="Durée de conservation des traces contenant des données personnelles (minimisation, Art. 5-1-e)."
        :icon="Clock"
        status="active"
        :collapsible="false"
      >
        <label>Tentatives de connexion / adresses IP (jours)<RetentionDaysInput v-model="form.login_attempt_retention_days" :default-days="90" placeholder="90"/><small>Les adresses IP de connexion sont purgées après ce délai. Conservation indéfinie déconseillée pour ces données.</small></label>
        <label>Journaux d'audit et de diagnostic (jours)<RetentionDaysInput v-model="form.audit_log_retention_days" :default-days="90"/><small>Actions admin, événements de diagnostic, exécutions de tâches.</small></label>
      </SettingsCard>
    </div>
  </div>
</template>
<script setup>
import { ShieldCheck, Timer } from '@lucide/vue';
import { form } from '@/settingsForm';
import SettingsCard from './SettingsCard.vue';
import RetentionDaysInput from './RetentionDaysInput.vue';
</script>
