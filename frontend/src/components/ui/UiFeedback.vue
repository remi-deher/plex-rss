<template>
  <div v-if="message" class="ui-feedback" :class="`is-${type}`" :role="type === 'error' ? 'alert' : 'status'" aria-live="polite">
    <component :is="icon" aria-hidden="true" />
    <div><strong v-if="title">{{ title }}</strong><span>{{ message }}</span></div>
    <button v-if="retry" class="secondary" type="button" @click="$emit('retry')">Réessayer</button>
    <button v-if="dismissible" class="ui-feedback-close" type="button" aria-label="Fermer" @click="$emit('dismiss')"><X /></button>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import { AlertTriangle, CheckCircle2, Info, LoaderCircle, X } from '@lucide/vue';
const props = defineProps({ type: { type: String, default: 'info' }, title: { type: String, default: '' }, message: { type: String, default: '' }, retry: Boolean, dismissible: Boolean });
defineEmits(['retry', 'dismiss']);
const icon = computed(() => ({ success: CheckCircle2, error: AlertTriangle, warning: AlertTriangle, loading: LoaderCircle }[props.type] || Info));
</script>
