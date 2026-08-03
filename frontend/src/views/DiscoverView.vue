<template>
  <div class="page discover-page">
    <PageHeader title="Découvrir" description="Trouvez un média et voyez immédiatement s’il est disponible, demandé ou à découvrir." />

    <section class="discover-command">
      <div class="discover-search">
        <Search aria-hidden="true" />
        <input
          v-model="query"
          type="search"
          placeholder="Rechercher un film ou une série"
          aria-label="Rechercher un film ou une série"
          @input="scheduleSearch"
        >
        <button
          class="filter-toggle"
          :class="{ active: filtersOpen || activeFilterCount }"
          :aria-expanded="filtersOpen"
          aria-controls="discover-filters"
          @click="filtersOpen = !filtersOpen"
        >
          <SlidersHorizontal aria-hidden="true" />Filtres
          <span v-if="activeFilterCount" :aria-label="`${activeFilterCount} filtres actifs`">{{ activeFilterCount }}</span>
        </button>
      </div>

      <div class="discover-sections" aria-label="Sélection du catalogue">
        <button
          v-for="entry in sections"
          :key="entry.value"
          :class="{ active: section === entry.value && !query }"
          :aria-pressed="section === entry.value && !query"
          @click="setSection(entry.value)"
        >
          {{ entry.label }}
        </button>
      </div>

      <div id="discover-filters" class="discover-filters" :class="{ open: filtersOpen }">
        <div class="segmented" aria-label="Type de média">
          <button
            v-for="entry in mediaTypes"
            :key="entry.value"
            :class="{ active: mediaType === entry.value }"
            :aria-pressed="mediaType === entry.value"
            @click="setMediaType(entry.value)"
          >
            {{ entry.label }}
          </button>
        </div>
        <select v-if="section === 'genres' && !query" v-model="genre" aria-label="Genre" @change="reload">
          <option value="">Tous les genres</option>
          <option v-for="entry in genres" :key="entry.id" :value="entry.id">{{ entry.name }}</option>
        </select>
        <select v-model="availability" aria-label="Disponibilité">
          <option value="">Tous les états</option>
          <option value="available">Disponible sur Plex</option>
          <option value="requested">Déjà demandé</option>
          <option value="new">À découvrir</option>
        </select>
        <button v-if="activeFilterCount" class="secondary" @click="resetFilters">Réinitialiser</button>
      </div>
    </section>

    <div class="discover-heading">
      <div>
        <span class="eyebrow">{{ query ? 'Résultats' : sectionLabel }}</span>
        <h2>{{ query ? `Recherche « ${query.trim()} »` : sectionDescription }}</h2>
      </div>
      <span aria-live="polite">
        {{ displayedItems.length }} affiché{{ displayedItems.length > 1 ? 's' : '' }}
        <template v-if="totalResults"> sur {{ totalResults }}</template>
      </span>
    </div>

    <UiFeedback v-if="error" type="error" :message="error" retry @retry="reload" />
    <UiFeedback v-if="loading" type="loading" message="Chargement du catalogue…" />
    <template v-else>
      <section class="media-grid discover-grid" aria-live="polite" :aria-busy="loadingMore">
        <MediaPosterCard
          v-for="item in displayedItems"
          :key="`${item.media_type}:${item.tmdb_id || item.id}`"
          :to="detailPath(item)"
          :item="item"
          :action-label="cardActionLabel(item)"
        />
      </section>

      <p v-if="!displayedItems.length" class="empty">Aucun média ne correspond à ces filtres.</p>
      <LoadMore :has-more="hasMore" :loading="loadingMore" label="Charger plus de médias" @load="loadMore"/>
    </template>
  </div>
</template>

<script setup>
import LoadMore from '@/components/ui/LoadMore.vue';
import MediaPosterCard from '@/components/discover/MediaPosterCard.vue';
import { computed, onMounted, ref } from 'vue';
import { useDebounced } from '@/composables/useDebounced';
import { useLatestRequest } from '@/composables/useLatestRequest';
import { Search, SlidersHorizontal } from '@lucide/vue';
import { api } from '@/api';
import { mediaDetailPath } from '@/mediaUrl';

const items = ref([]);
const query = ref('');
const mediaType = ref('all');
const section = ref('trending');
const genre = ref('');
const availability = ref('');
const genres = ref([]);
const loading = ref(false);
const loadingMore = ref(false);
const error = ref('');
const page = ref(1);
const totalPages = ref(1);
const totalResults = ref(0);
const filtersOpen = ref(!window.matchMedia('(max-width:640px)').matches);
const request = useLatestRequest();

const mediaTypes = [
  { value: 'all', label: 'Tout' },
  { value: 'movie', label: 'Films' },
  { value: 'show', label: 'Séries' },
];
const sections = [
  { value: 'trending', label: 'Tendances' },
  { value: 'popular', label: 'Populaires' },
  { value: 'coming-soon', label: 'Bientôt' },
  { value: 'genres', label: 'Par genre' },
];

const sectionLabel = computed(() => sections.find(entry => entry.value === section.value)?.label || 'Catalogue');
const sectionDescription = computed(() => ({
  trending: 'Les médias qui attirent le plus l’attention',
  popular: 'Les incontournables du moment',
  'coming-soon': 'Les prochaines sorties à surveiller',
  genres: 'Explorez le catalogue par univers',
})[section.value]);
const activeFilterCount = computed(() => [
  mediaType.value !== 'all',
  genre.value,
  availability.value,
].filter(Boolean).length);
const displayedItems = computed(() => items.value.filter(item => {
  if (availability.value === 'available') return item.available || item.in_library;
  if (availability.value === 'requested') return item.requested && !item.available && !item.in_library;
  if (availability.value === 'new') return !item.requested && !item.available && !item.in_library;
  return true;
}));
const hasMore = computed(() => page.value < totalPages.value);

function detailPath(item) {
  const kind = item.library_id ? 'library' : item.request_id ? 'request' : 'discover';
  return mediaDetailPath(item, kind);
}

function cardActionLabel(item) {
  if (item.in_library || item.library_id) return 'Voir la fiche';
  if (item.requested || item.request_id) return 'Suivre la demande';
  return 'Demander';
}

async function setMediaType(value) {
  mediaType.value = value;
  genre.value = '';
  await loadGenres();
  await reload();
}

function setSection(value) {
  section.value = value;
  query.value = '';
  genre.value = '';
  reload();
}

async function resetFilters() {
  mediaType.value = 'all';
  genre.value = '';
  availability.value = '';
  section.value = 'trending';
  await loadGenres();
  await reload();
}

async function loadGenres() {
  try {
    genres.value = await api(`/api/discover/genres?media_type=${mediaType.value}`);
  } catch {
    genres.value = [];
  }
}

function endpoint(targetPage) {
  const type = `media_type=${mediaType.value}`;
  const pagination = `page=${targetPage}&paginated=true`;
  const q = query.value.trim();
  if (q) return `/api/discover/search?query=${encodeURIComponent(q)}&${type}&${pagination}`;
  if (section.value === 'trending') return `/api/discover/trending?${type}&${pagination}`;
  if (section.value === 'popular') return `/api/discover/popular?${type}&${pagination}`;
  if (section.value === 'coming-soon') return `/api/discover/coming-soon?${type}&${pagination}`;
  return `/api/discover/discover?${type}&${pagination}${genre.value ? `&genre=${genre.value}` : ''}`;
}

async function load({ append = false } = {}) {
  const targetPage = append ? page.value + 1 : 1;
  // « Charger plus » prolonge la requete en cours (ne pas annuler la page deja demandee) ;
  // un nouveau chargement abandonne la precedente.
  const { signal, isCurrent } = append ? request.extend() : request.begin();
  if (append) loadingMore.value = true;
  else loading.value = true;
  error.value = '';

  try {
    const payload = await api(endpoint(targetPage), { signal });
    if (!isCurrent()) return;
    const incoming = payload.items || [];
    if (append) {
      const known = new Set(items.value.map(item => `${item.media_type}:${item.tmdb_id}`));
      items.value = [...items.value, ...incoming.filter(item => !known.has(`${item.media_type}:${item.tmdb_id}`))];
    } else {
      items.value = incoming;
    }
    page.value = payload.page || targetPage;
    totalPages.value = payload.total_pages || 1;
    totalResults.value = payload.total_results || incoming.length;
  } catch (e) {
    if (!request.isAbort(e) && isCurrent()) {
      error.value = e.message;
      if (!append) items.value = [];
    }
  } finally {
    if (isCurrent()) {
      loading.value = false;
      loadingMore.value = false;
    }
  }
}

function reload() {
  return load();
}

function loadMore() {
  if (!loadingMore.value && hasMore.value) load({ append: true });
}

const debouncedReload = useDebounced(reload, 300);
function scheduleSearch() {
  request.abort();
  debouncedReload();
}

onMounted(async () => {
  await loadGenres();
  await load();
});
</script>

<style scoped>
.discover-command{position:sticky;top:8px;z-index:20;display:grid;gap:9px;padding:12px;border:1px solid var(--border);border-radius:12px;background:color-mix(in srgb,var(--surface) 94%,transparent);backdrop-filter:blur(12px)}.discover-search{display:flex;align-items:center;gap:9px}.discover-search>svg{width:18px;color:var(--muted)}.discover-search input{flex:1;min-width:0;border:0;background:transparent;color:var(--text);font-size:15px;outline:0}.filter-toggle{display:flex;align-items:center;gap:6px;padding:7px 9px;border:1px solid var(--border);border-radius:8px;background:transparent;color:var(--muted)}.filter-toggle svg{width:15px}.filter-toggle span{padding:2px 5px;border-radius:999px;background:var(--accent);color:#111;font-size:9px}.filter-toggle.active{color:var(--text)}.discover-sections,.discover-filters{display:flex;align-items:center;gap:6px;overflow-x:auto}.discover-sections button{padding:6px 10px;border:0;border-radius:999px;background:transparent;color:var(--muted);white-space:nowrap}.discover-sections button.active{background:var(--accent);color:#111}.discover-filters{display:none;padding-top:8px;border-top:1px solid var(--border)}.discover-filters.open{display:flex}.discover-heading{display:flex;align-items:end;justify-content:space-between;gap:12px;margin-top:6px}.discover-heading>div{display:grid;gap:2px}.discover-heading h2{margin:0;font-size:17px}.discover-heading>span{color:var(--muted);font-size:10px}.discover-grid{align-items:start}.load-more{display:flex;justify-content:center;padding:20px}.load-more button{display:flex;align-items:center;gap:8px}.load-more svg{width:16px}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:640px){.discover-command{top:6px;padding:10px}.filter-toggle{font-size:0}.filter-toggle span{font-size:9px}.discover-filters{align-items:stretch;flex-direction:column;overflow:visible}.discover-filters .segmented{display:flex}.discover-filters .segmented button{flex:1}.discover-filters select{width:100%}.discover-heading h2{font-size:14px}}
</style>
