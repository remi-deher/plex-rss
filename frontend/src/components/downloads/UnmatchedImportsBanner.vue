<template>
  <section v-if="items.length" class="panel unmatched-alert">
    <div class="unmatched-header">
      <div class="unmatched-icon"><AlertTriangle /></div>
      <div>
        <strong>{{ items.length }} import{{ items.length > 1 ? 's' : '' }} non associé{{ items.length > 1 ? 's' : '' }}</strong>
        <span>Ces téléchargements ne sont pas liés à une demande ou à un élément de la bibliothèque. Cliquez sur <Link style="width:14px;height:14px;display:inline;vertical-align:middle"/> pour les associer.</span>
      </div>
      <button class="panel-link" @click="$emit('view-all')">Voir les imports</button>
    </div>
    <div class="unmatched-list">
      <div v-for="row in items.slice(0, 4)" :key="rowKey(row)" class="unmatched-item">
        <span class="unmatched-title">{{ row.title }}</span>
        <span class="badge">{{ row.instance || '-' }}</span>
        <button class="icon-button" title="Associer manuellement" aria-label="Associer manuellement" @click="$emit('associate', row)"><Link /></button>
      </div>
      <div v-if="items.length > 4" class="unmatched-more">
        + {{ items.length - 4 }} autre(s)
      </div>
    </div>
  </section>
</template>

<script setup>
import { AlertTriangle, Link } from '@lucide/vue';

defineProps({
  items: { type: Array, default: () => [] },
  rowKey: { type: Function, required: true },
});
defineEmits(['view-all', 'associate']);
</script>
