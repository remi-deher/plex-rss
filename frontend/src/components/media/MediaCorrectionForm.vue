<template>
  <div class="panel form-section" style="margin-top: 1rem; border: 1px solid var(--accent-color);">
    <div class="panel-head">
      <h3 style="margin: 0;">Envoyer une correction {{ scopeLabel }}</h3>
    </div>
    
    <label>Destinataires (demandeurs pre-selectionnes)
      <div class="season-grid" style="grid-template-columns: 1fr 1fr; margin-top: 0.5rem;">
        <label v-for="u in users" :key="u.id" class="check">
          <input type="checkbox" v-model="localForm.recipient_user_ids" :value="u.id"> {{ u.custom_name || u.display_name || u.plex_user_id }}
        </label>
      </div>
    </label>
    
    <label>Corrections a annoncer
      <div class="season-grid" style="grid-template-columns: 1fr; margin-top: 0.5rem;">
        <label v-for="opt in correctionOptions" :key="opt" class="check">
          <input type="checkbox" :checked="localForm.corrections.includes(opt)" @change="e => { if (e.target.checked) localForm.corrections.push(opt); else localForm.corrections = localForm.corrections.filter(x => x !== opt); }" :value="opt"> {{ opt }}
        </label>
      </div>
    </label>
    
    <label>Message complementaire
      <textarea v-model="localForm.note" class="search" rows="3" placeholder="Optionnel"></textarea>
    </label>
    
    <div class="inline-row compact" style="margin-top: 1rem;">
      <button class="primary" :disabled="busy || !localForm.corrections.length || !localForm.recipient_user_ids.length" @click="$emit('submit', localForm)">Envoyer la correction</button>
      <button class="secondary" @click="$emit('cancel')">Annuler</button>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, watch } from 'vue';

const props = defineProps({
  initialForm: { type: Object, required: true },
  users: { type: Array, required: true },
  correctionOptions: { type: Array, required: true },
  busy: { type: Boolean, default: false }
});

const emit = defineEmits(['submit', 'cancel']);

const localForm = reactive({ ...props.initialForm });

// Sync if props change
watch(() => props.initialForm, (newVal) => {
  Object.assign(localForm, newVal);
}, { deep: true });

const scopeLabel = computed(() => {
  if (localForm.scope === 'season') return `(Saison ${localForm.season_number})`;
  if (localForm.scope === 'episode') return `(Saison ${localForm.season_number} Ep ${localForm.episode_number})`;
  return '(Media complet)';
});
</script>
