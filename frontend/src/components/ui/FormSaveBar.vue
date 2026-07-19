<template>
  <Transition name="save-bar">
    <aside v-if="dirty" class="form-save-bar" role="status" aria-live="polite">
      <div><span class="unsaved-dot" aria-hidden="true"/><span><strong>Modifications non enregistrées</strong><small>Enregistrez avant de quitter cette page.</small></span></div>
      <button class="primary" type="button" :disabled="saving" @click="$emit('save')"><LoaderCircle v-if="saving" class="spin"/><Save v-else/>{{ saving?'Enregistrement…':'Enregistrer' }}</button>
    </aside>
  </Transition>
</template>
<script setup>
import { LoaderCircle, Save } from '@lucide/vue';
defineProps({dirty:Boolean,saving:Boolean});
defineEmits(['save']);
</script>
