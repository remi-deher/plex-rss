<template>
  <div class="page calendar-page">
    <PageHeader title="Calendrier" :description="`Sorties de ${periodLabel}`">
      <div class="calendar-navigation">
        <button class="icon-button" title="Mois précédent" aria-label="Mois précédent" @click="move(-1)"><ChevronLeft/></button>
        <button class="secondary" @click="today">Aujourd'hui</button>
        <button class="icon-button" title="Mois suivant" aria-label="Mois suivant" @click="move(1)"><ChevronRight/></button>
        <button class="icon-button" :disabled="loading" title="Actualiser" aria-label="Actualiser" @click="load"><RefreshCw :class="{spin:loading}"/></button>
      </div>
    </PageHeader>

    <div class="calendar-command-bar">
      <!-- La grille mensuelle ne tient pas sous 640px : le sélecteur disparaît -->
      <div v-if="!compact" class="segmented calendar-view-switch" aria-label="Mode d'affichage">
        <button :class="{active:view==='agenda'}" @click="view='agenda'"><List/>Agenda</button>
        <button :class="{active:view==='month'}" @click="view='month'"><CalendarDays/>Mois</button>
      </div>
      <FilterBar :active-count="activeFilterCount" :result-count="filtered.length" @reset="resetFilters">
        <template #primary>
          <input v-model="search" class="search" type="search" placeholder="Filtrer les titres" aria-label="Filtrer le calendrier">
        </template>
        <template #filters>
          <select v-model="type">
            <option value="">Films et séries</option>
            <option value="movie">Films</option>
            <option value="episode">Séries</option>
          </select>
          <label class="check">
            <input v-model="tracked" type="checkbox" @change="load"> Suivis uniquement
          </label>
        </template>
      </FilterBar>
    </div>

    <div class="calendar-legend" aria-label="Légende">
      <span><i class="available"></i>Disponible</span>
    </div>
    <UiFeedback v-if="error" type="error" title="Calendrier indisponible" :message="error" retry @retry="load" />

    <!-- Vue Grille Mensuelle (conservée intacte) -->
    <div v-if="view==='month'" class="month-calendar-shell" tabindex="0" aria-label="Calendrier mensuel, défilement horizontal disponible">
      <div class="month-calendar">
        <div v-for="label in weekLabels" :key="label" class="month-weekday">{{ label }}</div>
        <div v-for="cell in monthCells" :key="cell.key" class="month-cell" :class="{outside:!cell.current,today:cell.date===todayStr}">
          <header><span>{{ cell.day }}</span><small v-if="cell.date===todayStr">Aujourd'hui</small></header>
          <button v-for="event in cell.events.slice(0,3)" :key="eventKey(event)" class="month-event" :class="eventState(event)" :title="`${event.title} — ${event.subtitle}`" @click="openDetail(event)"><span v-if="formatTime(event.date)">{{ formatTime(event.date) }}</span><strong>{{ event.title }}</strong></button>
          <button v-if="cell.events.length>3" class="month-more" @click="showDay(cell.date)">+ {{ cell.events.length-3 }} autre{{ cell.events.length>4?'s':'' }}</button>
        </div>
      </div>
    </div>

    <!-- Vue Agenda Améliorée -->
    <div v-else class="calendar-agenda">
      <section v-for="group in shownGroups" :key="group.date" :id="'date-' + group.date" class="calendar-day" :class="{today:group.date===todayStr}">
        <div class="calendar-day-header">
          <h2>{{ longDate(group.date) }}</h2>
          <div class="calendar-day-sub">
            <span v-if="group.date===todayStr" class="today-badge">Aujourd'hui</span>
            <span class="day-event-count">{{ group.events.length }} sortie{{ group.events.length > 1 ? 's' : '' }}</span>
          </div>
        </div>

        <div class="calendar-events">
          <article
            v-for="event in group.events"
            :key="eventKey(event)"
            class="calendar-event-card"
            :class="{ interactive: event.library_item_id || event.request_id, 'has-fanart': !!event.fanart_url }"
            :role="event.library_item_id || event.request_id ? 'link' : undefined"
            :tabindex="event.library_item_id || event.request_id ? 0 : undefined"
            :aria-label="event.library_item_id || event.request_id ? `Ouvrir la fiche de ${event.title}` : undefined"
            @click="openDetail(event)"
            @keydown.enter.prevent="openDetail(event)"
            @keydown.space.prevent="openDetail(event)"
          >
            <!-- Background Backdrop & Overlay -->
            <div v-if="event.fanart_url" class="card-backdrop" :style="{ backgroundImage: `url(${event.fanart_url})` }"></div>
            <div v-if="event.fanart_url" class="card-backdrop-overlay"></div>

            <div class="card-poster">
              <img v-if="event.poster_url" :src="event.poster_url" :alt="event.title" loading="lazy" decoding="async">
              <div v-else class="poster-fallback"><Film v-if="event.type==='movie'"/><Tv v-else/></div>
            </div>

            <div class="card-info">
              <div class="card-title-row">
                <strong class="card-title">{{ event.title }}</strong>
                <span v-if="event.rating" class="rating-badge" title="Note TMDB/Plex"><Star /> {{ event.rating }}</span>
              </div>

              <div class="card-meta">
                <span v-if="formatTime(event.date)" class="time-badge"><Clock />{{ formatTime(event.date) }}</span>
                <span class="subtitle-text">{{ event.subtitle }}</span>
                <span v-if="event.instance" class="instance-tag">{{ event.instance }}</span>
              </div>

              <div v-if="event.genres && event.genres.length" class="card-genres">
                <span v-for="g in event.genres" :key="g" class="genre-pill">{{ g }}</span>
              </div>
            </div>

            <div class="card-actions" @click.stop>
              <!-- Show status badge ONLY when available -->
              <span v-if="event.has_file" class="status-badge available">
                Disponible
              </span>

              <!-- Action button when available in Plex -->
              <button
                v-if="event.has_file"
                type="button"
                class="plex-action-btn"
                title="Regarder sur Plex"
                @click.stop="openPlex(event, $event)"
              >
                <Play /> <span>Regarder sur Plex</span>
              </button>
            </div>
          </article>
        </div>
      </section>

      <LoadMore
        :has-more="shownGroups.length < grouped.length"
        :label="`Afficher plus de jours (${shownGroups.length} sur ${grouped.length})`"
        @load="visibleDays += DAYS_PAGE"
      />
      <InfiniteScrollTrigger
        :has-more="shownGroups.length < grouped.length"
        :loading="loading"
        @load="visibleDays += DAYS_PAGE"
      />
    </div>

    <p v-if="!loading && !filtered.length" class="empty">Aucune sortie sur cette période.</p>
  </div>
</template>

<script setup>
import { formatLongDay as longDate, formatMonthYear } from '@/utils/format';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { CalendarDays, ChevronLeft, ChevronRight, Clock, Film, List, Play, RefreshCw, Star, Tv } from '@lucide/vue';
import { api } from '@/api';
import { useRouter } from 'vue-router';
import { formatPlexWebUrl, mediaDetailPath } from '@/mediaUrl';
import LoadMore from '@/components/ui/LoadMore.vue';
import InfiniteScrollTrigger from '@/components/ui/InfiniteScrollTrigger.vue';
import { useSession } from '@/composables/useSession';

const router = useRouter();
const { session, isAdmin, ready: sessionReady } = useSession();

const myRequestsOnly = computed(() => !isAdmin.value);
const events = ref([]), search = ref(''), type = ref(''), tracked = ref(false), loading = ref(false), error = ref(''), cursor = ref(new Date());
const compactQuery = window.matchMedia('(max-width:640px)');
const compact = ref(compactQuery.matches);
const view = ref(localStorage.getItem('calendar.view') || (compact.value ? 'agenda' : 'month'));
const todayStr = localIso(new Date()), weekLabels = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'];
const bounds = computed(() => { const y = cursor.value.getFullYear(), m = cursor.value.getMonth(); return { start: new Date(y, m, 1), end: new Date(y, m + 1, 1) }; });
const periodLabel = computed(() => formatMonthYear(cursor.value));
const filtered = computed(() => events.value.filter(e => (!search.value || e.title.toLowerCase().includes(search.value.toLowerCase())) && (!type.value || e.type === type.value)));
const eventsByDate = computed(() => { const map = new Map(); filtered.value.forEach(e => { const key = e.date.slice(0, 10); if (!map.has(key)) map.set(key, []); map.get(key).push(e); }); return map; });
const grouped = computed(() => [...eventsByDate.value].map(([date, items]) => ({ date, events: items })));

const DAYS_PAGE = 7;
const visibleDays = ref(DAYS_PAGE);
const shownGroups = computed(() => grouped.value.slice(0, visibleDays.value));
watch(grouped, () => { visibleDays.value = DAYS_PAGE; });

const monthCells = computed(() => {
  const start = bounds.value.start, first = (start.getDay() + 6) % 7, cells = [];
  for (let i = -first; i < 42 - first; i++) {
    const d = new Date(start.getFullYear(), start.getMonth(), i + 1), date = localIso(d);
    cells.push({ key: date, date, day: d.getDate(), current: d.getMonth() === start.getMonth(), events: eventsByDate.value.get(date) || [] });
  }
  return cells;
});

const activeFilterCount = computed(() => [search.value, type.value, tracked.value].filter(Boolean).length);
watch(view, value => { if (!compact.value) localStorage.setItem('calendar.view', value); });

function localIso(d) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; }
function formatTime(v) { if (!v) return ''; const d = new Date(v); if (isNaN(d.getTime()) || v.endsWith('T00:00:00Z') || v.endsWith('T00:00:00.000Z')) return ''; return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }); }
function eventKey(event) { return `${event.instance}:${event.date}:${event.title}:${event.subtitle}`; }
function eventState(event) { return event.has_file ? 'available' : ''; }

function openDetail(event) {
  if (event.library_item_id) router.push(mediaDetailPath({ id: event.library_item_id }, 'library'));
  else if (event.request_id) router.push(mediaDetailPath({ id: event.request_id }, 'request'));
}

function openPlex(event, e) {
  if (e) {
    e.stopPropagation();
    e.preventDefault();
  }
  const plexUrl = formatPlexWebUrl(event.plex_guid);
  if (plexUrl) {
    window.open(plexUrl, '_blank');
  } else {
    openDetail(event);
  }
}

function revealDate(date) { const i = grouped.value.findIndex(g => g.date === date); if (i < 0) return false; if (i >= visibleDays.value) visibleDays.value = i + DAYS_PAGE; return true; }
function scrollToDate(date) { if (!revealDate(date)) return; nextTick(() => document.getElementById(`date-${date}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })); }
function showDay(date) { view.value = 'agenda'; scrollToDate(date); }
function resetFilters() { search.value = ''; type.value = ''; tracked.value = false; load(); }
async function load() { loading.value = true; error.value = ''; try { const userParam = myRequestsOnly.value && session.value?.plex_user_id ? `&user=${encodeURIComponent(session.value.plex_user_id)}` : ''; events.value = await api(`/api/calendar?start=${localIso(bounds.value.start)}&end=${localIso(bounds.value.end)}&tracked_only=${tracked.value}${userParam}`); if (view.value === 'agenda') nextTick(() => setTimeout(() => { const target = grouped.value.find(g => g.date >= todayStr); if (target) scrollToDate(target.date); }, 100)); } catch (e) { error.value = e.message; } finally { loading.value = false; } }
function move(delta) { cursor.value = new Date(cursor.value.getFullYear(), cursor.value.getMonth() + delta, 1); load(); }
function today() { cursor.value = new Date(); load(); }
function applyCompact(matches) { if (matches === compact.value) return; compact.value = matches; view.value = matches ? 'agenda' : (localStorage.getItem('calendar.view') || 'month'); }
function syncCompact() { applyCompact(compactQuery.matches); }

onMounted(async () => {
  compact.value = !compactQuery.matches; syncCompact();
  compactQuery.addEventListener('change', syncCompact); window.addEventListener('resize', syncCompact);
  if (!sessionReady.value) { await new Promise(resolve => { const stop = watch(sessionReady, v => { if (v) { stop(); resolve(); } }); }); }
  load();
});
onBeforeUnmount(() => { compactQuery.removeEventListener('change', syncCompact); window.removeEventListener('resize', syncCompact); });
</script>

<style scoped>
.calendar-navigation, .calendar-command-bar, .calendar-legend { display: flex; align-items: center; gap: var(--space-2); }
.calendar-command-bar { align-items: stretch; }
.calendar-command-bar :deep(.ui-filter-bar) { flex: 1; }
.calendar-view-switch button { gap: var(--space-2); min-width: 92px; }
.calendar-view-switch svg { width: 15px; }

.calendar-legend { justify-content: flex-end; color: var(--muted); font-size: var(--fs-xs); margin-bottom: var(--space-3); }
.calendar-legend span { display: flex; align-items: center; gap: var(--space-1); }
.calendar-legend i { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); }
.calendar-legend i.available { background: var(--success); }

/* Vue Grille Mensuelle */
.month-calendar-shell { max-width: 100%; overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); scrollbar-width: thin; overscroll-behavior-x: contain; }
.month-calendar { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); min-width: 0; }
.month-weekday { position: sticky; top: 0; z-index: 2; padding: 8px; text-align: center; border-bottom: 1px solid var(--border); background: var(--surface); color: var(--muted); font-size: var(--fs-xs); font-weight: 700; text-transform: uppercase; }
.month-cell { min-width: 0; min-height: 132px; padding: 8px; border-right: 1px solid var(--border); border-bottom: 1px solid var(--border); background: rgba(255, 255, 255, 0.008); overflow: hidden; }
.month-cell:nth-child(7n) { border-right: 0; }
.month-cell:nth-last-child(-n+7) { border-bottom: 0; }
.month-cell.outside { opacity: 0.35; }
.month-cell.today { background: rgba(229, 160, 13, 0.06); box-shadow: inset 0 0 0 1px rgba(229, 160, 13, 0.3); }
.month-cell header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.month-cell header > span { color: var(--text); font-weight: 700; }
.month-cell header small { color: var(--accent); font-size: var(--fs-xs); }
.month-event, .month-more { display: flex; align-items: center; gap: var(--space-1); width: 100%; min-width: 0; margin: 3px 0; padding: 4px 5px; border: 0; border-left: 2px solid var(--muted); border-radius: var(--radius-xs); background: rgba(255, 255, 255, 0.035); color: var(--text); font-size: var(--fs-xs); text-align: left; cursor: pointer; }
.month-event.available { border-color: var(--success); }
.month-event span { flex: 0 0 auto; font-size: var(--fs-xs); }
.month-event strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--fs-xs); }
.month-more { display: block; border: 0; background: transparent; color: var(--accent); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Vue Agenda Améliorée */
.calendar-agenda { display: flex; flex-direction: column; gap: var(--space-5); width: 100%; }

.calendar-day {
  display: flex !important;
  flex-direction: column !important;
  gap: var(--space-3) !important;
  width: 100% !important;
  padding-bottom: var(--space-4) !important;
  border-bottom: 1px solid var(--border) !important;
}
.calendar-day:last-child { border-bottom: 0 !important; }

.calendar-day-header { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; width: 100%; }
.calendar-day-header h2 { margin: 0; font-size: var(--fs-lg); font-weight: 700; color: var(--text); line-height: 1.25; text-transform: capitalize; }
.calendar-day-sub { display: flex; align-items: center; gap: var(--space-2); }
.day-event-count { color: var(--muted); font-size: var(--fs-xs); font-weight: 600; }
.today-badge { display: inline-flex; padding: 2px 8px; border-radius: var(--radius-pill); background: rgba(229, 160, 13, 0.15); color: var(--accent); font-size: var(--fs-xs); font-weight: 700; }

/* Vertically stacked full-width cards */
.calendar-events { display: flex; flex-direction: column; gap: var(--space-2); width: 100%; }

.calendar-event-card {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  padding: 12px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background-color: var(--surface);
  transition: transform 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
}

.calendar-event-card.interactive { cursor: pointer; }
.calendar-event-card.interactive:hover {
  border-color: var(--accent);
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35);
}

.card-backdrop {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-size: cover;
  background-position: center right;
  background-repeat: no-repeat;
  z-index: 0;
}

.card-backdrop-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(90deg, #101016 0%, rgba(16, 16, 22, 0.8) 45%, rgba(16, 16, 22, 0.35) 100%);
  z-index: 1;
}

.card-poster,
.card-info,
.card-actions {
  position: relative;
  z-index: 2;
}

.card-poster {
  flex: 0 0 54px;
  height: 80px;
  border-radius: var(--radius-xs);
  overflow: hidden;
  background: var(--surface-2);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35);
}

.card-poster img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.poster-fallback {
  color: var(--muted);
  display: grid;
  place-items: center;
}
.poster-fallback svg { width: 24px; height: 24px; }

.card-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.card-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.card-title {
  font-size: var(--fs-md);
  font-weight: 700;
  color: #ffffff;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rating-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 7px;
  border-radius: var(--radius-pill);
  background: rgba(229, 160, 13, 0.22);
  color: var(--accent);
  font-size: 11px;
  font-weight: 700;
}
.rating-badge svg { width: 12px; height: 12px; fill: currentColor; }

.card-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  color: #a0a0ab;
  font-size: var(--fs-xs);
}

.time-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--accent);
  font-weight: 600;
}
.time-badge svg { width: 13px; height: 13px; }

.subtitle-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.instance-tag {
  padding: 1px 6px;
  border-radius: var(--radius-xs);
  background: rgba(255, 255, 255, 0.08);
  font-size: 11px;
}

.card-genres {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 2px;
}

.genre-pill {
  padding: 1px 6px;
  border-radius: var(--radius-xs);
  background: rgba(255, 255, 255, 0.1);
  color: var(--muted);
  font-size: 10px;
  font-weight: 500;
}

.card-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.plex-action-btn,
.plex-action-btn *,
.plex-action-btn span {
  color: #000000 !important;
}

.plex-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: var(--radius-sm);
  background: #e5a00d !important;
  font-size: var(--fs-xs);
  font-weight: 700;
  border: 0;
  cursor: pointer;
  text-decoration: none;
  box-shadow: 0 2px 8px rgba(229, 160, 13, 0.35);
  transition: transform 0.15s ease, background 0.15s ease, box-shadow 0.15s ease;
}
.plex-action-btn:hover {
  background: #f5b01d !important;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(229, 160, 13, 0.45);
}
.plex-action-btn svg { width: 14px; height: 14px; fill: #000000 !important; color: #000000 !important; }

.status-badge.available {
  padding: 4px 10px;
  border-radius: var(--radius-pill);
  font-size: var(--fs-xs);
  font-weight: 700;
  background: #22c55e !important;
  color: #ffffff !important;
  opacity: 1 !important;
}

/* Adaptations Responsives Mobile */
@media (max-width: 900px) {
  .month-calendar { min-width: 760px; }
  .month-cell { min-height: 112px; padding: 6px; }
  .calendar-command-bar { display: grid; grid-template-columns: 1fr; gap: var(--space-2); }
  .calendar-view-switch { justify-self: start; }
  .calendar-legend { justify-content: flex-start; }
}

@media (max-width: 640px) {
  .calendar-navigation { width: 100%; justify-content: space-between; }
  .calendar-command-bar { position: sticky; top: 8px; z-index: 20; padding: 8px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); }
  .calendar-command-bar :deep(.ui-filter-bar) { position: static; padding: 0; border: 0; background: transparent; }
  .calendar-events { gap: var(--space-2); width: 100%; }
  .calendar-event-card { padding: 10px 12px; gap: var(--space-2); width: 100%; flex-wrap: wrap; }
  .card-poster { flex: 0 0 44px; height: 64px; }
  .card-title { font-size: var(--fs-sm); }

  /* Sizing compact pour mobile */
  .rating-badge { padding: 1px 5px; font-size: 10px; }
  .rating-badge svg { width: 10px; height: 10px; }

  .card-actions { width: 100%; margin-top: 4px; justify-content: space-between; gap: 8px; }
  .plex-action-btn { padding: 5px 10px; font-size: 11px; max-width: max-content; }
  .status-badge.available { padding: 3px 8px; font-size: 11px; }
  .calendar-view-switch button:last-child { display: none; }
}
</style>
