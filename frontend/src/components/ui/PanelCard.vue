<template>
  <section class="panel" :class="panelClass">
    <div v-if="title || eyebrow || $slots.head || $slots.action" class="panel-head">
      <div>
        <span v-if="eyebrow" class="eyebrow">{{ eyebrow }}</span>
        <h2 v-if="title">{{ title }}</h2>
        <p v-if="description">{{ description }}</p>
        <slot name="head" />
      </div>
      <slot name="action" />
    </div>
    <slot />
    <p v-if="empty" class="empty">{{ empty }}</p>
  </section>
</template>

<script setup>
// Coquille des panneaux : `<section class="panel">` + `panel-head` + surtitre/titre +
// zone d'action à droite + état vide. Ce markup était recopié dans 33 fichiers.
//
// `empty` est une chaîne, pas un booléen : le parent passe le message quand il n'a rien à
// afficher (`:empty="items.length ? '' : 'Aucune donnée.'"`), ce qui évite d'avoir à
// répéter `<p v-if="!items.length" class="empty">` à chaque appel.
defineProps({
  title: { type: String, default: '' },
  eyebrow: { type: String, default: '' },
  description: { type: String, default: '' },
  /** Message d'état vide ; chaîne vide = rien à afficher. */
  empty: { type: String, default: '' },
  panelClass: { type: String, default: '' },
});
</script>
