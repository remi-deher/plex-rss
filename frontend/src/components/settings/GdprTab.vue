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
    </div>
  </div>
</template>
<script setup>
import { ShieldCheck } from '@lucide/vue';
import { form } from '@/settingsForm';
import SettingsCard from './SettingsCard.vue';
</script>
