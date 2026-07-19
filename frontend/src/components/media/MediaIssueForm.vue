<template>
  <div class="panel form-section" style="margin-top: 1rem; border: 1px solid var(--border-color);">
    <label>Description du probleme
      <textarea v-model="localMessage" placeholder="Decrivez le probleme rencontre" rows="3" class="search"></textarea>
    </label>
    <div class="inline-row compact">
      <button class="primary" :disabled="busy || !localMessage.trim()" @click="$emit('submit', localMessage)">Envoyer</button>
      <button class="secondary" @click="$emit('cancel')">Annuler</button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';

defineProps({
  busy: { type: Boolean, default: false }
});

const emit = defineEmits(['submit', 'cancel']);

const localMessage = ref('');
</script>
