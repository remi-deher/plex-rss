<template>
  <div class="form-section">
    <label>Sujet<input v-model="model.subject"></label>
    <label>Modele HTML / Markdown</label>
    <MarkdownTextarea v-model="model.template" :rows="13" :variables="variables" />

    <div v-if="appearanceEditable" class="settings-grid two">
      <label>Couleur d'accent<input v-model="model.accent_color" type="color"></label>
      <label>Badge<input v-model="model.badge_text"></label>
      <label>Titre principal<input v-model="model.headline_text"></label>
      <label class="check"><input v-model="model.show_synopsis" type="checkbox"> Afficher le synopsis</label>
    </div>
    <p v-else class="notice">L'apparence herite actuellement du modele « Film disponible ». Elle sera reorganisee avec le futur menu Emails.</p>
  </div>
</template>

<script setup>
import MarkdownTextarea from './MarkdownTextarea.vue';

defineProps({
  model: { type: Object, required: true },
  variables: { type: Array, default: () => [] },
  appearanceEditable: { type: Boolean, default: true },
});
</script>
