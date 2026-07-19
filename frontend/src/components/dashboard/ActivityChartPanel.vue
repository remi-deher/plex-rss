<template>
  <section class="panel span-two">
    <div class="panel-head">
      <h2>Activite sur 30 jours</h2>
      <strong>{{ total }} demandes</strong>
    </div>
    <div class="activity-chart">
      <div class="y-axis">
        <span>{{ max }}</span>
        <span>{{ Math.round(max / 2) }}</span>
        <span>0</span>
      </div>
      <div class="chart-area">
        <div
          v-for="(value, index) in timeline.values || []"
          :key="index"
          class="bar-wrapper"
        >
          <div class="bar-value-top" v-if="value > 0 && (value / max) < 0.15">{{ value }}</div>
          <div
            class="bar"
            :style="{ height: `${Math.max(2, value / max * 100)}%` }"
            :title="`${timeline.labels[index]} : ${value}`"
          >
            <span class="bar-value" v-if="value > 0 && (value / max) >= 0.15">{{ value }}</span>
          </div>
          <div class="x-label" v-if="index % 4 === 0 || index === (timeline.values?.length || 0) - 1">
            {{ formatChartDate(timeline.labels[index]) }}
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({ timeline: { type: Object, default: () => ({ labels: [], values: [] }) } });

const total = computed(() => (props.timeline.values || []).reduce((a, b) => a + b, 0));
const max = computed(() => Math.max(1, ...(props.timeline.values || [1])));

function formatChartDate(v) {
  if (!v) return '';
  const d = new Date(v);
  return `${d.getDate().toString().padStart(2, '0')}/${(d.getMonth() + 1).toString().padStart(2, '0')}`;
}
</script>
