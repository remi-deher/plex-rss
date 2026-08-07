<template>
  <nav class="subnav-bar" :aria-label="ariaLabel">
    <template v-for="(item, i) in items" :key="item.key">
      <span v-if="i > 0 && item.group && item.group !== items[i - 1].group" class="subnav-separator" aria-hidden="true" />
      <RouterLink
        :to="item.to"
        :class="{ active: item.key === active }"
        :aria-current="item.key === active ? 'page' : undefined"
      >
        <component :is="item.icon" v-if="item.icon" />
        <span>{{ item.label }}</span>
        <small v-if="item.count != null">{{ item.count }}</small>
      </RouterLink>
    </template>
  </nav>
</template>

<script setup>
defineProps({
  items: { type: Array, required: true },
  active: { type: String, default: '' },
  ariaLabel: { type: String, default: 'Navigation' },
});
</script>

<style scoped>
.subnav-bar { display: flex; width: fit-content; max-width: 100%; gap: var(--space-1); margin: 0 auto 16px; padding: 5px; overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); scrollbar-width: none; scroll-snap-type: x proximity; overscroll-behavior-x: contain; }
.subnav-bar::-webkit-scrollbar { display: none; }
.subnav-bar a { display: flex; align-items: center; gap: var(--space-2); flex: none; min-height: 44px; padding: 7px 11px; border-radius: var(--radius-sm); color: var(--muted); font-size: var(--fs-sm); font-weight: 650; text-decoration: none; white-space: nowrap; scroll-snap-align: start; }
.subnav-bar a:hover { color: var(--text); background: rgba(255, 255, 255, .04); }
.subnav-bar a.active { color: var(--text); background: var(--surface-2); box-shadow: inset 0 0 0 1px var(--border); }
.subnav-bar svg { width: 15px; }
.subnav-bar a.active svg { color: var(--accent); }
.subnav-bar small { display: grid; place-items: center; min-width: 19px; height: 19px; padding: 0 5px; border-radius: var(--radius-pill); background: rgba(229, 160, 13, .15); color: var(--accent); font-size: var(--fs-xs); }
.subnav-separator { flex: none; width: 1px; align-self: stretch; margin: 6px 2px; background: var(--border); }
@media (max-width: 640px) {
  .subnav-bar a { padding-inline: 10px; }
  .subnav-bar svg { display: none; }
}
</style>
