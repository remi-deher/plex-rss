<template>
  <div class="page discover-page">
    <PageHeader title="Découvrir" description="Trouvez votre prochaine histoire et demandez-la en un geste." />

    <nav class="discover-mode" aria-label="Mode de découverte">
      <button :class="{ active: mode === 'home' }" :aria-pressed="mode === 'home'" @click="showHome">Accueil</button>
      <button :class="{ active: mode === 'explore' }" :aria-pressed="mode === 'explore'" @click="showExplorer">Explorer</button>
    </nav>

    <UiFeedback v-if="requestError" type="error" :message="requestError" dismissible @dismiss="requestError=''" />
    <UiFeedback v-if="requestSuccess" type="success" :message="requestSuccess" dismissible @dismiss="requestSuccess=''" />

    <template v-if="mode === 'home'">
      <section class="home-search">
        <Search aria-hidden="true" />
        <input
          v-model="query"
          type="search"
          placeholder="Rechercher un film ou une série"
          aria-label="Rechercher un film ou une série"
          @input="startSearch"
        >
      </section>

      <DiscoverHero :item="home.hero.item" :loading="home.hero.loading" />
      <UiFeedback v-if="home.hero.error" type="error" :message="home.hero.error" retry @retry="loadHomeGroup" />

      <div class="discover-home-rails">
        <MediaRail
          title="Tendances aujourd’hui"
          :items="home.trending.items"
          :loading="home.trending.loading"
          :error="home.trending.error"
          allow-request
          :requesting="requesting"
          @retry="loadHomeGroup"
          @request="requestMedia"
        />
        <MediaRail
          title="Films populaires"
          :items="home.popular_movies.items"
          :loading="home.popular_movies.loading"
          :error="home.popular_movies.error"
          allow-request
          :requesting="requesting"
          @retry="loadHomeSection('popular_movies')"
          @request="requestMedia"
        />
        <MediaRail
          title="Séries populaires"
          :items="home.popular_tv.items"
          :loading="home.popular_tv.loading"
          :error="home.popular_tv.error"
          allow-request
          :requesting="requesting"
          @retry="loadHomeSection('popular_tv')"
          @request="requestMedia"
        />

        <section class="discover-sources" aria-labelledby="sources-heading">
          <header>
            <div><span class="eyebrow">Explorer autrement</span><h2 id="sources-heading">Diffuseurs & studios</h2></div>
            <span v-if="sourcesRegion">Catalogue {{ sourcesRegion }}</span>
          </header>
          <MediaRailSkeleton v-if="sourcesLoading" :count="5" />
          <UiFeedback v-else-if="sourcesError" type="error" :message="sourcesError" retry @retry="loadSources" />
          <div v-else class="source-track">
            <DiscoverSourceCard
              v-for="source in sources"
              :key="`${source.kind}:${source.id}`"
              :source="source"
              :to="sourcePath(source)"
            />
          </div>
        </section>

        <MediaRail
          title="Prochainement"
          :items="home.upcoming.items"
          :loading="home.upcoming.loading"
          :error="home.upcoming.error"
          allow-request
          :requesting="requesting"
          @retry="loadHomeSection('upcoming')"
          @request="requestMedia"
        />
        <MediaRail
          title="Ajouts récents dans Plex"
          :items="home.recent_plex.items"
          :loading="home.recent_plex.loading"
          :error="home.recent_plex.error"
          :requesting="requesting"
          @retry="loadHomeSection('recent_plex')"
        />
        <MediaRail
          v-if="home.most_requested.loading || home.most_requested.items.length || home.most_requested.error"
          title="Les plus demandés"
          :items="home.most_requested.items"
          :loading="home.most_requested.loading"
          :error="home.most_requested.error"
          :requesting="requesting"
          @retry="loadHomeSection('most_requested')"
        />

        <section v-if="personalized.loading || personalized.available || personalized.error" class="personalized-discovery" aria-labelledby="personalized-heading">
          <header class="personalized-header">
            <div>
              <span class="eyebrow">Selon votre historique Plex</span>
              <h2 id="personalized-heading">Pour vous</h2>
              <p v-if="personalized.seeds.length">Inspiré par {{ personalized.seeds.map(item => item.title).join(', ') }}</p>
            </div>
            <div class="personalized-options" aria-label="Préférences de recommandation">
              <label><input v-model="hideAvailable" type="checkbox" @change="reloadPersonalized"> Masquer les médias dans Plex</label>
              <label><input v-model="hideWatched" type="checkbox" @change="reloadPersonalized"> Masquer les médias déjà vus</label>
            </div>
          </header>
          <UiFeedback v-if="personalized.error" type="error" :message="personalized.error" retry @retry="loadPersonalized" />
          <MediaRail
            v-else
            title="Parce que vous avez regardé…"
            :items="personalized.recommended.items"
            :loading="personalized.loading"
            allow-request
            :requesting="requesting"
            @request="requestMedia"
          />
          <MediaRail
            v-if="personalized.preferred_genres.items.length"
            title="Dans vos genres préférés"
            :items="personalized.preferred_genres.items"
            allow-request
            :requesting="requesting"
            @request="requestMedia"
          />
          <MediaRail
            v-if="personalized.unwatched_popular.items.length"
            title="Populaires et jamais vus"
            :items="personalized.unwatched_popular.items"
            allow-request
            :requesting="requesting"
            @request="requestMedia"
          />
          <MediaRail
            v-if="personalized.followed_series.items.length"
            title="Nouveaux épisodes de vos séries suivies"
            :items="personalized.followed_series.items"
            allow-request
            :requesting="requesting"
            @request="requestMedia"
          />
        </section>
      </div>
    </template>

    <template v-else>
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
          >{{ entry.label }}</button>
        </div>

        <div id="discover-filters" class="discover-filters" :class="{ open: filtersOpen }">
          <div class="segmented" aria-label="Type de média">
            <button
              v-for="entry in mediaTypes"
              :key="entry.value"
              :class="{ active: mediaType === entry.value }"
              :aria-pressed="mediaType === entry.value"
              @click="setMediaType(entry.value)"
            >{{ entry.label }}</button>
          </div>
          <select v-if="section === 'genres' && !query" v-model="genre" aria-label="Genre" @change="reload">
            <option value="">Tous les genres</option>
            <option v-for="entry in genres" :key="entry.id" :value="entry.id">{{ entry.name }}</option>
          </select>
          <select v-model="availability" aria-label="Disponibilité" @change="reload">
            <option value="">Tous les états</option>
            <option value="available">Disponible sur Plex</option>
            <option value="requested">Déjà demandé</option>
            <option value="new">À demander</option>
          </select>
          <select v-model="sourceKey" aria-label="Diffuseur ou studio" @change="selectSource">
            <option value="">Tous les diffuseurs et studios</option>
            <option v-for="source in sources" :key="`${source.kind}:${source.id}`" :value="`${source.kind}:${source.id}`">
              {{ source.name }}
            </option>
          </select>
          <button v-if="activeFilterCount" class="secondary" @click="resetFilters">Réinitialiser</button>
        </div>
      </section>

      <div class="discover-heading">
        <div>
          <span class="eyebrow">{{ query ? 'Résultats' : sectionLabel }}</span>
          <h2>{{ query ? `Recherche « ${query.trim()} »` : sectionDescription }}</h2>
        </div>
        <span aria-live="polite">{{ displayedItems.length }} affiché{{ displayedItems.length > 1 ? 's' : '' }}<template v-if="totalResults"> sur {{ totalResults }}</template></span>
      </div>

      <UiFeedback v-if="error" type="error" :message="error" retry @retry="reload" />
      <UiFeedback v-if="loading" type="loading" message="Chargement du catalogue…" />
      <template v-else>
        <section class="media-grid discover-grid" aria-live="polite" :aria-busy="loadingMore">
          <MediaPosterCard
            v-for="item in displayedItems"
            :key="mediaRequestKey(item)"
            :to="detailPath(item)"
            :item="item"
            :action-label="cardActionLabel(item)"
            :requestable="canRequest(item)"
            :request-busy="requesting.includes(mediaRequestKey(item))"
            @request="requestMedia"
          />
        </section>
        <p v-if="!displayedItems.length" class="empty">Aucun média ne correspond à ces filtres.</p>
        <LoadMore :has-more="hasMore" :loading="loadingMore" label="Charger plus de médias" @load="loadMore" />
      </template>
    </template>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { Search, SlidersHorizontal } from '@lucide/vue';
import { api } from '@/api';
import DiscoverHero from '@/components/discover/DiscoverHero.vue';
import DiscoverSourceCard from '@/components/discover/DiscoverSourceCard.vue';
import MediaPosterCard from '@/components/discover/MediaPosterCard.vue';
import MediaRail from '@/components/discover/MediaRail.vue';
import MediaRailSkeleton from '@/components/discover/MediaRailSkeleton.vue';
import LoadMore from '@/components/ui/LoadMore.vue';
import { useDebounced } from '@/composables/useDebounced';
import { mediaRequestKey, useDirectMediaRequest } from '@/composables/useDirectMediaRequest';
import { useLatestRequest } from '@/composables/useLatestRequest';
import { mediaDetailPath } from '@/mediaUrl';

const initialParams = new URLSearchParams(window.location.search);
const initialMode = window.location.pathname === '/discover/explore' || initialParams.get('mode') === 'explore';
const validMediaTypes = new Set(['all', 'movie', 'show']);
const validSections = new Set(['trending', 'popular', 'coming-soon', 'genres']);
const mode = ref(initialMode ? 'explore' : 'home');
const items = ref([]);
const query = ref(initialParams.get('q') || '');
const mediaType = ref(validMediaTypes.has(initialParams.get('type')) ? initialParams.get('type') : 'all');
const section = ref(validSections.has(initialParams.get('section')) ? initialParams.get('section') : 'trending');
const genre = ref(initialParams.get('genre') || '');
const availability = ref(['available', 'requested', 'new'].includes(initialParams.get('availability')) ? initialParams.get('availability') : '');
const sourceKey = ref(initialParams.get('source') || '');
const genres = ref([]);
const loading = ref(false);
const loadingMore = ref(false);
const error = ref('');
const page = ref(1);
const totalPages = ref(1);
const totalResults = ref(0);
const filtersOpen = ref(!window.matchMedia('(max-width:640px)').matches);
const request = useLatestRequest();
const sources = ref([]);
const sourcesRegion = ref('');
const sourcesLoading = ref(true);
const sourcesError = ref('');
const homeLoaded = ref(false);
const hideAvailable = ref(localStorage.getItem('discover.hideAvailable') === 'true');
const hideWatched = ref(localStorage.getItem('discover.hideWatched') === 'true');

function emptyPersonalizedRail() {
  return { items: [] };
}
const personalized = reactive({
  available: false,
  loading: false,
  error: '',
  seeds: [],
  recommended: emptyPersonalizedRail(),
  preferred_genres: emptyPersonalizedRail(),
  unwatched_popular: emptyPersonalizedRail(),
  followed_series: emptyPersonalizedRail(),
});

function sectionState() {
  return { item: null, items: [], loading: true, error: '' };
}
const home = reactive({
  hero: sectionState(),
  trending: sectionState(),
  popular_movies: sectionState(),
  popular_tv: sectionState(),
  upcoming: sectionState(),
  recent_plex: sectionState(),
  most_requested: sectionState(),
});

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
const activeFilterCount = computed(() => [mediaType.value !== 'all', genre.value, availability.value, sourceKey.value].filter(Boolean).length);
const displayedItems = computed(() => items.value.filter(item => {
  if (availability.value === 'available') return item.available || item.in_library;
  if (availability.value === 'requested') return item.requested && !item.available && !item.in_library;
  if (availability.value === 'new') return !item.requested && !item.available && !item.in_library;
  return true;
}));
const hasMore = computed(() => page.value < totalPages.value);
const { requesting, requestError, requestSuccess, requestMedia } = useDirectMediaRequest({ onUpdated: updateMatchingMedia });

function updateMatchingMedia(changed, update) {
  const key = mediaRequestKey(changed);
  for (const item of items.value) if (mediaRequestKey(item) === key) Object.assign(item, update);
  for (const state of Object.values(home)) {
    if (state.item && mediaRequestKey(state.item) === key) Object.assign(state.item, update);
    for (const item of state.items) if (mediaRequestKey(item) === key) Object.assign(item, update);
  }
  for (const name of ['recommended', 'preferred_genres', 'unwatched_popular', 'followed_series']) {
    for (const item of personalized[name].items) if (mediaRequestKey(item) === key) Object.assign(item, update);
  }
}
function detailPath(item) {
  const kind = item.library_id ? 'library' : item.request_id ? 'request' : 'discover';
  return mediaDetailPath(item, kind);
}
function cardActionLabel(item) {
  if (item.in_library || item.library_id) return 'Voir la fiche';
  if (item.requested || item.request_id) return 'Suivre la demande';
  return 'Demander';
}
function canRequest(item) {
  return !item.in_library && !item.library_id && !item.requested && !item.request_id;
}
function sourcePath(source) {
  return { path: `/discover/source/${source.kind}/${source.id}`, query: { name: source.name } };
}
function showHome() {
  request.abort();
  mode.value = 'home';
  window.history.replaceState(window.history.state, '', '/discover');
  if (!homeLoaded.value) loadHome();
}
async function showExplorer() {
  mode.value = 'explore';
  syncExplorerUrl();
  if (!genres.value.length) loadGenres();
  if (!sources.value.length) loadSources();
  await load();
}
function startSearch() {
  mode.value = 'explore';
  syncExplorerUrl();
  scheduleSearch();
}

function syncExplorerUrl() {
  if (mode.value !== 'explore') return;
  const params = new URLSearchParams();
  if (query.value.trim()) params.set('q', query.value.trim());
  if (mediaType.value !== 'all') params.set('type', mediaType.value);
  if (section.value !== 'trending') params.set('section', section.value);
  if (genre.value) params.set('genre', genre.value);
  if (availability.value) params.set('availability', availability.value);
  if (sourceKey.value) params.set('source', sourceKey.value);
  const suffix = params.toString();
  window.history.replaceState(window.history.state, '', `/discover/explore${suffix ? `?${suffix}` : ''}`);
}

function applyExplorerUrl() {
  if (window.location.pathname !== '/discover/explore') return;
  const params = new URLSearchParams(window.location.search);
  mode.value = 'explore';
  query.value = params.get('q') || '';
  mediaType.value = validMediaTypes.has(params.get('type')) ? params.get('type') : 'all';
  section.value = validSections.has(params.get('section')) ? params.get('section') : 'trending';
  genre.value = params.get('genre') || '';
  availability.value = ['available', 'requested', 'new'].includes(params.get('availability')) ? params.get('availability') : '';
  sourceKey.value = params.get('source') || '';
  loadGenres();
  load();
}

async function loadHomeGroup() {
  home.hero.loading = true;
  home.trending.loading = true;
  home.hero.error = '';
  home.trending.error = '';
  try {
    const payload = await api('/api/discover/home?sections=hero,trending');
    Object.assign(home.hero, payload.sections.hero, { loading: false, error: payload.sections.hero.error || '' });
    Object.assign(home.trending, payload.sections.trending, { loading: false, error: payload.sections.trending.error || '' });
  } catch (loadError) {
    home.hero.error = loadError.message;
    home.trending.error = loadError.message;
    home.hero.loading = false;
    home.trending.loading = false;
  }
}
async function loadHomeSection(name) {
  home[name].loading = true;
  home[name].error = '';
  try {
    const payload = await api(`/api/discover/home?sections=${name}`);
    Object.assign(home[name], payload.sections[name], { loading: false, error: payload.sections[name].error || '' });
  } catch (loadError) {
    home[name].error = loadError.message;
    home[name].loading = false;
  }
}
async function loadSources() {
  sourcesLoading.value = true;
  sourcesError.value = '';
  try {
    const payload = await api('/api/discover/sources');
    sources.value = payload.items || [];
    sourcesRegion.value = payload.region || '';
  } catch (loadError) {
    sourcesError.value = loadError.message;
  } finally {
    sourcesLoading.value = false;
  }
}
function loadHome() {
  homeLoaded.value = true;
  loadHomeGroup();
  for (const name of ['popular_movies', 'popular_tv', 'upcoming', 'recent_plex', 'most_requested']) loadHomeSection(name);
  loadSources();
  loadPersonalized();
}

async function loadPersonalized() {
  personalized.loading = true;
  personalized.error = '';
  try {
    const params = new URLSearchParams({
      hide_available: String(hideAvailable.value),
      hide_watched: String(hideWatched.value),
    });
    const payload = await api(`/api/discover/personalized?${params}`);
    personalized.available = Boolean(payload.available);
    personalized.seeds = payload.seeds || [];
    personalized.error = payload.error || '';
    for (const name of ['recommended', 'preferred_genres', 'unwatched_popular', 'followed_series']) {
      personalized[name].items = payload.sections?.[name]?.items || [];
    }
  } catch (loadError) {
    personalized.available = true;
    personalized.error = loadError.message;
  } finally {
    personalized.loading = false;
  }
}

function reloadPersonalized() {
  localStorage.setItem('discover.hideAvailable', String(hideAvailable.value));
  localStorage.setItem('discover.hideWatched', String(hideWatched.value));
  loadPersonalized();
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
  sourceKey.value = '';
  reload();
}
function selectSource() {
  query.value = '';
  genre.value = '';
  reload();
}
async function resetFilters() {
  mediaType.value = 'all';
  genre.value = '';
  availability.value = '';
  sourceKey.value = '';
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
  if (sourceKey.value) {
    const [kind, id] = sourceKey.value.split(':');
    return `/api/discover/source/${kind}/${id}?${type}&${pagination}`;
  }
  if (section.value === 'trending') return `/api/discover/trending?${type}&${pagination}`;
  if (section.value === 'popular') return `/api/discover/popular?${type}&${pagination}`;
  if (section.value === 'coming-soon') return `/api/discover/coming-soon?${type}&${pagination}`;
  return `/api/discover/discover?${type}&${pagination}${genre.value ? `&genre=${genre.value}` : ''}`;
}
async function load({ append = false } = {}) {
  syncExplorerUrl();
  const targetPage = append ? page.value + 1 : 1;
  const { signal, isCurrent } = append ? request.extend() : request.begin();
  if (append) loadingMore.value = true;
  else loading.value = true;
  error.value = '';
  try {
    const payload = await api(endpoint(targetPage), { signal });
    if (!isCurrent()) return;
    const incoming = payload.items || [];
    if (append) {
      const known = new Set(items.value.map(mediaRequestKey));
      items.value = [...items.value, ...incoming.filter(item => !known.has(mediaRequestKey(item)))];
    } else {
      items.value = incoming;
    }
    page.value = payload.page || targetPage;
    totalPages.value = payload.total_pages || 1;
    totalResults.value = payload.total_results || incoming.length;
  } catch (loadError) {
    if (!request.isAbort(loadError) && isCurrent()) {
      error.value = loadError.message;
      if (!append) items.value = [];
    }
  } finally {
    if (isCurrent()) {
      loading.value = false;
      loadingMore.value = false;
    }
  }
}
function reload() { return load(); }
function loadMore() { if (!loadingMore.value && hasMore.value) load({ append: true }); }
const debouncedReload = useDebounced(reload, 300);
function scheduleSearch() {
  request.abort();
  syncExplorerUrl();
  debouncedReload();
}

onMounted(() => {
  window.addEventListener('popstate', applyExplorerUrl);
  if (mode.value === 'home') loadHome();
  else showExplorer();
});
onBeforeUnmount(() => window.removeEventListener('popstate', applyExplorerUrl));
</script>

<style scoped>
.discover-page { gap: 20px; }
.discover-mode { display: inline-flex; justify-self: start; gap: 4px; padding: 4px; border: 1px solid var(--border); border-radius: 999px; background: var(--surface); }
.discover-mode button { padding: 7px 14px; border: 0; border-radius: 999px; color: var(--muted); background: transparent; }
.discover-mode button.active { color: #111; background: var(--accent); }
.home-search { display: flex; align-items: center; gap: 10px; max-width: 760px; padding: 12px 15px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }
.home-search svg { width: 19px; color: var(--muted); }
.home-search input { flex: 1; min-width: 0; border: 0; outline: 0; color: var(--text); background: transparent; font-size: 1rem; }
.discover-home-rails { display: grid; gap: 30px; }
.discover-sources { display: grid; gap: 12px; min-width: 0; }
.discover-sources header { display: flex; align-items: end; justify-content: space-between; gap: 16px; }
.discover-sources h2 { margin: 2px 0 0; font-size: 1.15rem; }
.discover-sources header > span { font-size: .75rem; }
.source-track { display: grid; grid-auto-columns: clamp(145px, 18vw, 210px); grid-auto-flow: column; gap: 12px; padding-bottom: 8px; overflow-x: auto; scroll-snap-type: x proximity; }
.source-track > * { scroll-snap-align: start; }
.personalized-discovery { display: grid; gap: 22px; padding: 20px; border: 1px solid var(--border); border-radius: 16px; background: color-mix(in srgb, var(--surface) 92%, var(--accent) 8%); }
.personalized-header { display: flex; align-items: start; justify-content: space-between; gap: 18px; }
.personalized-header h2 { margin: 2px 0 0; font-size: 1.25rem; }
.personalized-header p { max-width: 680px; margin: 5px 0 0; color: var(--muted); font-size: .78rem; }
.personalized-options { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.personalized-options label { display: flex; align-items: center; gap: 6px; color: var(--muted); font-size: .75rem; cursor: pointer; }
.personalized-options input { accent-color: var(--accent); }
.discover-command{position:sticky;top:8px;z-index:20;display:grid;gap:9px;padding:12px;border:1px solid var(--border);border-radius:12px;background:color-mix(in srgb,var(--surface) 94%,transparent);backdrop-filter:blur(12px)}.discover-search{display:flex;align-items:center;gap:9px}.discover-search>svg{width:18px;color:var(--muted)}.discover-search input{flex:1;min-width:0;border:0;background:transparent;color:var(--text);font-size:15px;outline:0}.filter-toggle{display:flex;align-items:center;gap:6px;padding:7px 9px;border:1px solid var(--border);border-radius:8px;background:transparent;color:var(--muted)}.filter-toggle svg{width:15px}.filter-toggle span{padding:2px 5px;border-radius:999px;background:var(--accent);color:#111;font-size:9px}.filter-toggle.active{color:var(--text)}.discover-sections,.discover-filters{display:flex;align-items:center;gap:6px;overflow-x:auto}.discover-sections button{padding:6px 10px;border:0;border-radius:999px;background:transparent;color:var(--muted);white-space:nowrap}.discover-sections button.active{background:var(--accent);color:#111}.discover-filters{display:none;padding-top:8px;border-top:1px solid var(--border)}.discover-filters.open{display:flex}.discover-heading{display:flex;align-items:end;justify-content:space-between;gap:12px;margin-top:6px}.discover-heading>div{display:grid;gap:2px}.discover-heading h2{margin:0;font-size:17px}.discover-heading>span{color:var(--muted);font-size:10px}.discover-grid{grid-template-columns:repeat(auto-fill,minmax(220px,1fr));align-items:start;gap:18px}.load-more{display:flex;justify-content:center;padding:20px}.load-more button{display:flex;align-items:center;gap:8px}.load-more svg{width:16px}
@media(max-width:700px){.discover-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}
@media(max-width:640px){.discover-mode{width:100%}.discover-mode button{flex:1}.discover-command{top:6px;padding:10px}.filter-toggle{font-size:0}.filter-toggle span{font-size:9px}.discover-filters{align-items:stretch;flex-direction:column;overflow:visible}.discover-filters .segmented{display:flex}.discover-filters .segmented button{flex:1}.discover-filters select{width:100%}.discover-heading h2{font-size:14px}.source-track{grid-auto-columns:minmax(145px,52vw);margin-right:-12px}.personalized-discovery{padding:14px}.personalized-header{display:grid}.personalized-options{display:grid}}
</style>
