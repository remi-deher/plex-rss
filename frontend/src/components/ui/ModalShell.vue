<template>
  <div v-if="open" class="drawer-backdrop" @click.self="requestClose">
    <aside
      ref="panelRef"
      tabindex="-1"
      class="modal-panel"
      :class="panelClass"
      role="dialog"
      aria-modal="true"
      :aria-label="ariaLabel || title"
    >
      <div class="panel-head">
        <div>
          <h2>{{ title }}</h2>
          <p v-if="subtitle">{{ subtitle }}</p>
        </div>
        <button class="icon-button" title="Fermer" aria-label="Fermer" :disabled="busy" @click="requestClose">
          <X />
        </button>
      </div>
      <p v-if="error" class="notice error-text">{{ error }}</p>
      <slot />
      <div v-if="$slots.actions" class="actions"><slot name="actions" /></div>
    </aside>
  </div>
</template>

<script setup>
// Coquille des modales centrées : backdrop, fermeture au clic extérieur, piège de focus
// et restitution du focus à la fermeture (via useModalA11y), en-tête et zone d'actions.
// Pendant de DrawerShell, qui fait la même chose pour les panneaux latéraux.
//
// Cinq modales recopiaient ce markup et rebranchaient useModalA11y à la main. La classe
// `.modal-panel` et le `.panel-head` sont conservés à l'identique : le rendu ne change pas.
import { ref, toRef } from 'vue';
import { X } from '@lucide/vue';

import { useModalA11y } from '@/composables/useModalA11y';

const props = defineProps({
  /** Monté/démonté par le parent (`v-if`) ? Laisser `true`. Sinon, piloter par cette prop. */
  open: { type: Boolean, default: true },
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  /** Libellé accessible quand il doit différer du titre visible. */
  ariaLabel: { type: String, default: '' },
  /** Classe additionnelle sur le panneau, pour sa largeur ou ses styles propres. */
  panelClass: { type: String, default: '' },
  error: { type: String, default: '' },
  /** Opération en cours : neutralise la fermeture pour éviter un abandon à mi-course. */
  busy: { type: Boolean, default: false },
});
const emit = defineEmits(['close']);

function requestClose() {
  if (!props.busy) emit('close');
}

const panelRef = ref(null);
useModalA11y(panelRef, toRef(props, 'open'), requestClose);
</script>
