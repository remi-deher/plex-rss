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
        <label>Tentatives de connexion / adresses IP (jours)<input v-model.number="form.login_attempt_retention_days" type="number" min="0" placeholder="90"><small>Les adresses IP de connexion sont purgées après ce délai. 0 ou vide = conservation indéfinie (déconseillé).</small></label>
        <label>Journaux d'audit et de diagnostic (jours)<input v-model.number="form.audit_log_retention_days" type="number" min="0" placeholder="0 ou vide = indéfini"><small>Actions admin, événements de diagnostic, exécutions de tâches. 0 ou vide = conserver indéfiniment.</small></label>
      </SettingsCard>
    </div>
  </div>
</template>
<script setup>
import { ShieldCheck, Timer } from '@lucide/vue';
import { form } from '@/settingsForm';
import SettingsCard from './SettingsCard.vue';
</script>
