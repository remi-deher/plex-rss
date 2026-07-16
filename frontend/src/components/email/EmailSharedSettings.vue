<template>
  <div>
    <details open class="template-settings">
      <summary>En-tete commun</summary>
      <div class="settings-grid two form-section">
        <label>Marque<input v-model="shared.email_header_brand"></label>
        <label>Sous-titre<input v-model="shared.email_header_subtitle"></label>
        <label>Couleur de marque<input v-model="shared.email_brand_color" type="color"></label>
        <label class="check"><input v-model="shared.email_show_header_subtitle" type="checkbox"> Afficher le sous-titre</label>
      </div>
    </details>

    <details class="template-settings">
      <summary>Bloc media et apparence</summary>
      <div class="settings-grid two form-section">
        <label>Disposition<select v-model="shared.email_media_layout"><option value="left">Affiche a gauche</option><option value="right">Affiche a droite</option><option value="stacked">Affiche au-dessus</option></select></label>
        <label>Police<select v-model="shared.email_font_family"><option value="arial">Arial</option><option value="georgia">Georgia</option><option value="verdana">Verdana</option><option value="trebuchet">Trebuchet MS</option></select></label>
        <label>Largeur de carte <span>{{ shared.email_card_width }} px</span><input v-model.number="shared.email_card_width" type="range" min="480" max="700" step="10"></label>
        <label>Largeur affiche <span>{{ shared.email_poster_width }} px</span><input v-model.number="shared.email_poster_width" type="range" min="60" max="180" step="10"></label>
        <label>Arrondi de carte <span>{{ shared.email_card_border_radius }} px</span><input v-model.number="shared.email_card_border_radius" type="range" min="0" max="24" step="2"></label>
        <label>Taille du synopsis<select v-model="shared.email_synopsis_font_size"><option value="small">Petite</option><option value="normal">Normale</option><option value="large">Grande</option><option value="xlarge">Tres grande</option></select></label>
        <label>Fond de page<input v-model="shared.email_bg_color" type="color"></label>
        <label>Fond de carte<input v-model="shared.email_card_bg_color" type="color"></label>
        <label class="check"><input v-model="shared.email_show_poster" type="checkbox"> Afficher l'affiche</label>
        <label class="check"><input v-model="shared.email_show_genres" type="checkbox"> Afficher les genres</label>
        <label class="check"><input v-model="shared.email_show_requester" type="checkbox"> Afficher le demandeur</label>
        <label>Libelle du demandeur<input v-model="shared.email_requester_label"></label>
        <label class="check"><input v-model="shared.email_show_tmdb_link" type="checkbox"> Afficher le lien TMDB</label>
        <label class="check"><input v-model="shared.email_show_plex_button" type="checkbox"> Afficher le bouton Plex</label>
      </div>
    </details>

    <details class="template-settings">
      <summary>Pied de page commun</summary>
      <div class="form-section">
        <label>Pied de page HTML / Markdown</label>
        <MarkdownTextarea v-model="shared.email_footer_template" :rows="5" :variables="variables" />
      </div>
    </details>
  </div>
</template>

<script setup>
import MarkdownTextarea from './MarkdownTextarea.vue';

defineProps({
  shared: { type: Object, required: true },
  variables: { type: Array, default: () => [] },
});
</script>
