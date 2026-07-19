<template>
  <section class="settings-card" :class="[status, { collapsed: collapsible && !open }]">
    <header class="settings-card-head">
      <div class="settings-card-title">
        <span class="settings-card-icon" v-if="icon"><component :is="icon"/></span>
        <div class="settings-card-heading">
          <div class="settings-card-name-row">
            <h3>{{ title }}</h3>
            <span class="settings-card-status" :class="status">{{ statusLabel }}</span>
          </div>
          <p v-if="subtitle" class="settings-card-subtitle">{{ subtitle }}</p>
        </div>
      </div>
      <div class="settings-card-head-actions">
        <slot name="actions"/>
        <button v-if="collapsible" class="chevron" :class="{ open }" type="button" :aria-expanded="open" @click="toggle">
          <span class="chevron-label">{{ open ? 'Replier' : 'Deplier' }}</span>
          <ChevronDown/>
        </button>
      </div>
    </header>

    <div v-if="feedback" class="settings-card-feedback" :class="feedback.success === false ? 'error' : 'ok'">
      <component :is="feedback.success === false ? XCircle : CheckCircle2"/>
      <span>{{ feedback.message }}</span>
    </div>

    <div v-show="!collapsible || open" class="settings-card-body">
      <slot/>
    </div>
  </section>
</template>
<script setup>
import { computed, ref } from 'vue';
import { CheckCircle2, ChevronDown, XCircle } from '@lucide/vue';

const props = defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  icon: { type: [Object, Function], default: null },
  status: { type: String, default: 'neutral' }, // active | inactive | error | neutral
  statusText: { type: String, default: '' },
  collapsible: { type: Boolean, default: true },
  defaultOpen: { type: Boolean, default: false },
  feedback: { type: Object, default: null }, // { success: boolean, message: string }
});

const open = ref(props.defaultOpen);
function toggle() { open.value = !open.value; }

const defaultLabels = { active: 'Actif', inactive: 'Inactif', error: 'Erreur', neutral: '' };
const statusLabel = computed(() => props.statusText || defaultLabels[props.status] || '');

defineExpose({ toggle, open });
</script>
