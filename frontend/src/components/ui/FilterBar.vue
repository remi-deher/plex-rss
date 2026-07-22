<template>
  <section class="ui-filter-bar" aria-label="Filtres">
    <div v-if="$slots.primary" class="ui-filter-primary"><slot name="primary" /></div>
    <div class="ui-filter-desktop">
      <slot name="filters" />
      <button v-if="activeCount" class="ui-filter-reset" type="button" @click="$emit('reset')">Réinitialiser</button>
    </div>
    <button class="ui-filter-mobile-trigger secondary" type="button" :aria-expanded="open" @click="open=true">
      <SlidersHorizontal/>Filtres<span v-if="activeCount" class="ui-filter-count">{{ activeCount }}</span>
    </button>
  </section>

  <Teleport to="body">
    <Transition name="filter-sheet">
      <div v-if="open" class="ui-filter-overlay" @click.self="close">
        <section ref="panelRef" tabindex="-1" class="ui-filter-sheet" role="dialog" aria-modal="true" aria-labelledby="filter-sheet-title">
          <header><div><span>Affichage</span><h2 id="filter-sheet-title">Filtres</h2></div><button class="icon-button" type="button" aria-label="Fermer" @click="close"><X/></button></header>
          <div class="ui-filter-sheet-content"><slot name="filters" /></div>
          <footer>
            <button class="secondary" type="button" :disabled="!activeCount" @click="$emit('reset')">Réinitialiser</button>
            <button class="primary" type="button" @click="close">{{ resultCount == null ? 'Afficher les résultats' : `Afficher ${resultCount} résultat${resultCount > 1 ? 's' : ''}` }}</button>
          </footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref } from 'vue';
import { SlidersHorizontal, X } from '@lucide/vue';
import { useModalA11y } from '@/composables/useModalA11y';
defineProps({ activeCount: { type: Number, default: 0 }, resultCount: { type: Number, default: null } });
defineEmits(['reset']);
const open=ref(false);
function close(){open.value=false}
const panelRef = ref(null);
useModalA11y(panelRef, open, close);
</script>
