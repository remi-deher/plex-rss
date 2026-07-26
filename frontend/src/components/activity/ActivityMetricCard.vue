<template>
  <article class="metric-card activity-metric-card" :class="{ accent }">
    <component :is="icon" v-if="icon" />
    <div><span>{{ label }}</span><strong>{{ value }}</strong><small v-if="detail">{{ detail }}</small></div>
  </article>
</template>

<script setup>
defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: '—' },
  detail: { type: String, default: '' },
  icon: { type: [Object, Function], default: null },
  accent: { type: Boolean, default: false },
});
</script>

<style scoped>
.activity-metric-card{display:grid;grid-template-columns:auto minmax(0,1fr);align-items:center;gap:12px}.activity-metric-card>svg{width:22px;color:var(--muted)}.activity-metric-card.accent>svg{color:var(--accent)}.activity-metric-card div{display:grid;min-width:0}.activity-metric-card span,.activity-metric-card small{overflow:hidden;color:var(--muted);font-size:10px;text-overflow:ellipsis;white-space:nowrap}.activity-metric-card strong{font-size:24px;line-height:1.2}
</style>
