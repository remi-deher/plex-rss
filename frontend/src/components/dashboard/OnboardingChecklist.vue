<template>
  <section v-if="onboarding.steps?.length && !onboarding.complete && show" class="panel">
    <div class="panel-head">
      <div>
        <h2>Configuration initiale</h2>
        <p>{{ doneSteps }}/{{ onboarding.steps.length }} etapes terminees</p>
      </div>
      <div class="actions">
        <RouterLink class="secondary" to="/settings">Continuer</RouterLink>
        <button class="secondary" @click="$emit('dismiss')">
          <X />Masquer
        </button>
      </div>
    </div>
    <div class="checklist">
      <span v-for="step in onboarding.steps" :key="step.id">
        <CheckCircle2 v-if="step.done" class="success-text" />
        <Circle v-else />
        {{ step.label }}
      </span>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue';
import { CheckCircle2, Circle, X } from '@lucide/vue';

const props = defineProps({
  onboarding: { type: Object, default: () => ({}) },
  show: { type: Boolean, default: true },
});
defineEmits(['dismiss']);

const doneSteps = computed(() => props.onboarding.steps?.filter(x => x.done).length || 0);
</script>
