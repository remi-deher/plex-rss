<template>
  <div class="person-page">
    <button class="person-back" type="button" @click="goBack"><ArrowLeft /> Retour</button>
    <div v-if="loading" class="person-state"><LoaderCircle class="spin" /> Chargement</div>
    <UiFeedback v-else-if="error" type="error" :message="error" />
    <template v-else-if="person">
      <header class="person-hero">
        <img v-if="person.profile_url" :src="person.profile_url" :alt="`Portrait de ${person.name}`">
        <div v-else class="person-placeholder"><UserRound /></div>
        <div class="person-copy">
          <span class="eyebrow">{{ person.known_for_department || 'Interprétation' }}</span>
          <h1>{{ person.name }}</h1>
          <p class="person-meta">{{ lifeSummary }}</p>
          <p v-if="person.biography" class="biography" :class="{ expanded: bioExpanded }">{{ person.biography }}</p>
          <button v-if="person.biography?.length > 420" class="bio-toggle" type="button" @click="bioExpanded = !bioExpanded">{{ bioExpanded ? 'Réduire' : 'Lire la suite' }}</button>
        </div>
      </header>

      <section class="credits-section">
        <div class="credits-heading">
          <div><span class="eyebrow">Filmographie</span><h2>Films et séries</h2></div>
          <div class="credit-filters" aria-label="Filtrer la filmographie">
            <button v-for="option in filters" :key="option.value" :class="{ active: filter === option.value }" @click="filter = option.value">{{ option.label }}</button>
          </div>
        </div>
        <div v-if="visibleCredits.length" class="media-grid credits-grid">
          <MediaPosterCard v-for="item in visibleCredits" :key="`${item.media_type}:${item.tmdb_id}`" :item="item" :to="detailPath(item)" :action-label="item.character || 'Voir la fiche'" />
        </div>
        <p v-else class="empty-state">Aucun média trouvé dans cette catégorie.</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { ArrowLeft, LoaderCircle, UserRound } from '@lucide/vue';
import { useRoute, useRouter } from 'vue-router';
import { api } from '@/api';
import { mediaDetailPath } from '@/mediaUrl';
import MediaPosterCard from '@/components/discover/MediaPosterCard.vue';

const route = useRoute();
const router = useRouter();
const person = ref(null);
const loading = ref(false);
const error = ref('');
const filter = ref('all');
const bioExpanded = ref(false);
const filters = [{ value: 'all', label: 'Tout' }, { value: 'movie', label: 'Films' }, { value: 'show', label: 'Séries' }];
const visibleCredits = computed(() => (person.value?.credits || []).filter(item => filter.value === 'all' || item.media_type === filter.value));
const lifeSummary = computed(() => [person.value?.birthday && `Né(e) le ${formatDate(person.value.birthday)}`, person.value?.deathday && `décédé(e) le ${formatDate(person.value.deathday)}`, person.value?.place_of_birth].filter(Boolean).join(' · '));

function formatDate(value) { return new Intl.DateTimeFormat('fr-FR', { dateStyle: 'long' }).format(new Date(`${value}T12:00:00`)); }
function detailPath(item) { return mediaDetailPath(item, item.library_id ? 'library' : item.request_id ? 'request' : 'discover', { discover: true }); }
function goBack() { if (window.history.state?.back) router.back(); else router.push('/discover'); }
async function load() {
  loading.value = true; error.value = ''; person.value = null; filter.value = 'all'; bioExpanded.value = false;
  try { person.value = await api(`/api/discover/person/${route.params.id}`); }
  catch (e) { error.value = e.message; }
  finally { loading.value = false; }
}
watch(() => route.params.id, load, { immediate: true });
</script>

<style scoped>
.person-page { display: grid; gap: var(--space-5); max-width: 1440px; margin: 0 auto; padding: 24px clamp(16px, 3vw, 42px) 48px; }
.person-back { display: inline-flex; align-items: center; gap: var(--space-2); justify-self: start; border: 0; background: transparent; color: var(--muted); }
.person-back svg { width: 18px; }
.person-state { display: flex; align-items: center; justify-content: center; gap: var(--space-2); min-height: 45vh; color: var(--muted); }
.person-hero { display: grid; grid-template-columns: minmax(180px, 280px) minmax(0, 760px); gap: clamp(24px, 4vw, 56px); align-items: start; }
.person-hero > img, .person-placeholder { width: 100%; aspect-ratio: 2 / 3; border-radius: var(--radius-lg); background: var(--surface-2); object-fit: cover; box-shadow: 0 20px 50px rgba(0,0,0,.35); }
.person-placeholder { display: grid; place-items: center; color: var(--muted); }
.person-placeholder svg { width: 34%; height: 34%; }
.person-copy { display: grid; gap: var(--space-3); padding-top: 12px; }
.eyebrow { color: var(--accent); font-size: var(--fs-xs); font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
.person-copy h1, .credits-heading h2 { margin: 0; }
.person-copy h1 { font-size: clamp(2.2rem, 5vw, 4.5rem); line-height: .98; }
.person-meta { margin: 0; color: var(--muted); }
.biography { display: -webkit-box; overflow: hidden; max-width: 72ch; margin: var(--space-2) 0 0; line-height: 1.7; -webkit-box-orient: vertical; -webkit-line-clamp: 7; }
.biography.expanded { display: block; }
.bio-toggle { justify-self: start; padding: 0; border: 0; background: transparent; color: var(--accent); font-weight: 750; }
.credits-section { display: grid; gap: var(--space-4); }
.credits-heading { display: flex; align-items: end; justify-content: space-between; gap: var(--space-3); }
.credits-heading > div:first-child { display: grid; gap: var(--space-1); }
.credit-filters { display: flex; gap: var(--space-1); padding: 4px; border: 1px solid var(--border); border-radius: var(--radius-pill); background: var(--surface-2); }
.credit-filters button { padding: 7px 13px; border: 0; border-radius: var(--radius-pill); background: transparent; color: var(--muted); }
.credit-filters button.active { background: var(--accent); color: #111; }
.credits-grid { grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: var(--space-4); }
.empty-state { padding: 40px; color: var(--muted); text-align: center; }
@media (max-width: 640px) { .person-page { padding-top: 16px; } .person-hero { grid-template-columns: 110px minmax(0, 1fr); gap: 18px; } .person-copy { padding: 0; } .person-copy h1 { font-size: 2rem; } .person-meta { font-size: var(--fs-xs); } .biography, .bio-toggle { grid-column: 1 / -1; } .credits-heading { align-items: stretch; flex-direction: column; } .credit-filters { align-self: start; } .credits-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); } }
</style>
