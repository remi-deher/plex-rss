<template>
  <div v-if="hasMore" class="load-more">
    <button class="secondary" :disabled="loading" @click="$emit('load')">
      <LoaderCircle v-if="loading" class="spin" aria-hidden="true" />
      {{ loading ? loadingLabel : label }}
    </button>
  </div>
</template>

<script setup>
// Bouton « charger plus », présent en quatre exemplaires avec des libellés et des états
// de chargement légèrement différents.
import { LoaderCircle } from '@lucide/vue';

defineProps({
  hasMore: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  label: { type: String, default: 'Charger plus' },
  loadingLabel: { type: String, default: 'Chargement…' },
});
defineEmits(['load']);
</script>
