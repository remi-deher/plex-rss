<template>
  <section v-if="items.length" class="drawer-section cast-section">
    <h3>Casting</h3>
    <div class="cast-rail" role="list">
      <RouterLink v-for="person in items" :key="person.tmdb_id" :to="`/discover/person/${person.tmdb_id}`" class="cast-card" :aria-label="`Voir la fiche de ${person.name}`">
        <img v-if="person.profile_url" :src="person.profile_url" :alt="`Portrait de ${person.name}`" loading="lazy" decoding="async">
        <span v-else class="cast-placeholder" aria-hidden="true"><UserRound /></span>
        <strong>{{ person.name }}</strong>
        <small v-if="person.character">{{ person.character }}</small>
      </RouterLink>
    </div>
  </section>
</template>

<script setup>
import { UserRound } from '@lucide/vue';
defineProps({ items: { type: Array, default: () => [] } });
</script>

<style scoped>
.cast-rail { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(118px, 145px); gap: var(--space-3); padding: 2px 2px 10px; overflow-x: auto; scroll-snap-type: x proximity; }
.cast-card { display: grid; grid-template-rows: auto auto 1fr; gap: 5px; min-width: 0; color: inherit; text-decoration: none; scroll-snap-align: start; }
.cast-card img, .cast-placeholder { width: 100%; aspect-ratio: 2 / 3; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface-2); object-fit: cover; transition: transform .2s ease, border-color .2s ease; }
.cast-placeholder { display: grid; place-items: center; color: var(--muted); }
.cast-placeholder svg { width: 38%; height: 38%; }
.cast-card:hover img, .cast-card:hover .cast-placeholder, .cast-card:focus-visible img, .cast-card:focus-visible .cast-placeholder { border-color: var(--accent); transform: translateY(-3px); }
.cast-card strong { overflow: hidden; font-size: var(--fs-sm); line-height: 1.2; text-overflow: ellipsis; white-space: nowrap; }
.cast-card small { display: -webkit-box; overflow: hidden; color: var(--muted); line-height: 1.25; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
@media (max-width: 640px) { .cast-rail { grid-auto-columns: 108px; } }
</style>
