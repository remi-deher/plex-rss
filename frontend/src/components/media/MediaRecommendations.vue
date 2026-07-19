<template>
  <section v-if="items.length" class="drawer-section">
    <h3>Recommandations</h3>
    <div class="mini-media-grid">
      <button v-for="item in items" :key="`${item.media_type}:${item.tmdb_id}`" @click="$emit('open',item)">
        <img v-if="item.poster_url" :src="item.poster_url" alt="">
        <span>{{ item.title }}</span>
      </button>
    </div>
  </section>
</template>

<script setup>
defineProps({
  items: { type: Array, default: () => [] },
});
defineEmits(['open']);
</script>
