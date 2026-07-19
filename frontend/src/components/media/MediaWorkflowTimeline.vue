<template>
  <section v-if="steps?.length" class="workflow-card">
    <div class="workflow-heading">
      <h2>Parcours du media</h2>
      <span>{{ progressLabel }}</span>
    </div>
    <ol class="workflow-timeline">
      <li v-for="step in steps" :key="step.key" :class="`is-${step.state}`">
        <span class="workflow-marker">
          <Check v-if="step.state === 'completed'" />
          <TriangleAlert v-else-if="step.state === 'error'" />
          <Circle v-else />
        </span>
        <div>
          <strong>{{ step.label }}</strong>
          <small v-if="step.occurred_at">{{ formatDate(step.occurred_at) }}</small>
          <small v-else-if="step.state === 'current'">Etape actuelle</small>
          <small v-else-if="step.state === 'upcoming'">A venir</small>
        </div>
      </li>
    </ol>
  </section>
</template>

<script setup>
import { computed } from 'vue';
import { Check, Circle, TriangleAlert } from '@lucide/vue';

const props = defineProps({ steps: { type: Array, default: () => [] } });
const progressLabel = computed(() => {
  const current = props.steps.find(step => step.state === 'current' || step.state === 'error');
  return current?.label || props.steps.at(-1)?.label || '';
});

function formatDate(value) {
  return new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}
</script>

<style scoped>
.workflow-card { margin-bottom: 18px; padding: 16px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-2); }
.workflow-heading { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; margin-bottom: 16px; }
.workflow-heading h2 { margin: 0; font-size: 16px; }
.workflow-heading span { color: var(--muted); font-size: 12px; text-align: right; }
.workflow-timeline { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); margin: 0; padding: 0; list-style: none; }
.workflow-timeline li { position: relative; display: flex; gap: 9px; min-width: 0; padding: 0 12px 12px 0; color: var(--muted); }
.workflow-timeline li::after { content: ''; position: absolute; top: 12px; left: 24px; right: 0; height: 2px; background: var(--border); }
.workflow-timeline li:last-child::after { display: none; }
.workflow-marker { z-index: 1; flex: 0 0 24px; width: 24px; height: 24px; display: grid; place-items: center; border-radius: 50%; background: var(--surface-2); border: 2px solid var(--border); }
.workflow-marker :deep(svg) { width: 13px; height: 13px; }
.workflow-timeline strong, .workflow-timeline small { display: block; }
.workflow-timeline strong { color: inherit; font-size: 13px; line-height: 1.25; }
.workflow-timeline small { margin-top: 4px; font-size: 11px; }
.workflow-timeline .is-completed { color: var(--success, #42b883); }
.workflow-timeline .is-completed::after { background: var(--success, #42b883); }
.workflow-timeline .is-current { color: var(--text); }
.workflow-timeline .is-current .workflow-marker { border-color: var(--accent); color: var(--accent); }
.workflow-timeline .is-error { color: var(--danger, #ef5350); }
.workflow-timeline .is-error .workflow-marker { border-color: currentColor; }
@media (max-width: 720px) {
  .workflow-timeline { display: block; }
  .workflow-timeline li { padding-bottom: 18px; }
  .workflow-timeline li::after { top: 24px; bottom: 0; left: 11px; right: auto; width: 2px; height: auto; }
}
</style>
