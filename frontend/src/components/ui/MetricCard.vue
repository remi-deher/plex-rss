<template>
  <component
    :is="to ? 'RouterLink' : 'article'"
    :to="to || undefined"
    class="metric-card"
    :class="[cardClass, { 'metric-card-link': to }]"
  >
    <template v-if="icon">
      <component :is="icon" class="metric-icon" />
      <div>
        <span>{{ label }}</span>
        <strong>{{ value }}</strong>
        <small v-if="detail">{{ detail }}</small>
      </div>
    </template>
    <template v-else>
      <span>{{ label }}</span>
      <strong>{{ value }}</strong>
      <small v-if="detail">{{ detail }}</small>
    </template>
  </component>
</template>

<script setup>
// Tuile de métrique, en deux formes selon la présence d'une icône :
//   sans icône -> span/strong/small à plat (Bibliothèque, Téléchargements, Insights)
//   avec icône -> icône + div enveloppant le texte (Tableau de bord, Activité Plex)
// Ce sont les deux markups qui existaient déjà, recopiés dans six fichiers. La mise en
// page vient de la grille parente (`.compact-metrics`, `.dashboard-metrics`,
// `.activity-metrics`) : le composant ne fait que produire la structure attendue.
defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: '—' },
  detail: { type: String, default: '' },
  icon: { type: [Object, Function], default: null },
  /** Rend la tuile cliquable (RouterLink) au lieu d'un simple article. */
  to: { type: [String, Object], default: null },
  /** Variante de style, ex. `activity-metric-card`. */
  cardClass: { type: String, default: '' },
});
</script>

<style scoped>
.metric-card {
  padding: 18px;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.metric-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
}
.metric-card strong {
  display: block;
  margin-top: 8px;
  color: var(--text);
  font-size: var(--fs-3xl);
  text-shadow: 0 2px 12px rgba(229, 160, 13, 0.3);
}
/* Une tuile-lien ne doit pas ressembler à un lien : le fond et la bordure de
   `.metric-card` portent déjà l'affordance. */
.metric-card-link { color: inherit; text-decoration: none; }
</style>
