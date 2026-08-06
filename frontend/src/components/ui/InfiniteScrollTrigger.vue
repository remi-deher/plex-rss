<template>
  <div v-if="hasMore" ref="sentinel" class="infinite-scroll-trigger" aria-hidden="true">
    <LoaderCircle v-if="loading" class="spin" />
  </div>
</template>

<script setup>
// Sentinelle observée pour déclencher le chargement de la page suivante
// automatiquement quand elle entre dans le viewport, sans bouton.
import { ref, watch, onMounted, onBeforeUnmount } from 'vue';
import { LoaderCircle } from '@lucide/vue';

const props = defineProps({
  hasMore: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
});
const emit = defineEmits(['load']);

const sentinel = ref(null);
let observer = null;

function trigger(entries) {
  if (entries[0]?.isIntersecting && props.hasMore && !props.loading) emit('load');
}

onMounted(() => {
  observer = new IntersectionObserver(trigger, { rootMargin: '400px' });
  if (sentinel.value) observer.observe(sentinel.value);
});
onBeforeUnmount(() => observer?.disconnect());
watch(sentinel, (el, prev) => {
  if (!observer) return;
  if (prev) observer.unobserve(prev);
  if (el) observer.observe(el);
});
</script>

<style scoped>
.infinite-scroll-trigger { display: flex; justify-content: center; padding: var(--space-4) 0; min-height: 1px; }
</style>
