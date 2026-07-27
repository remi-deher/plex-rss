<template>
  <div class="page analytics-page">
    <PageHeader
      title="Insights médiathèque"
      description="Inventaire technique et exploration interactive des fichiers présents sur Plex."
      eyebrow="Statistiques"
    >
      <button type="button" class="secondary" :disabled="loading" @click="load(true)">
        <RefreshCw /> Actualiser Plex
      </button>
      <a class="primary export-link" :href="exportUrl"><FileDown /> Exporter CSV</a>
    </PageHeader>

    <UiFeedback v-if="error" type="error" :message="error" retry @retry="load()" />
    <UiFeedback v-if="loading && !data.summary" type="loading" message="Analyse du catalogue Plex…" />

    <section class="workspace-section inventory-section">
      <header class="section-heading">
        <div><span class="eyebrow">Inventaire</span><h2>Fichiers analysés</h2></div>
        <small>{{ date(data.generated_at) }}</small>
      </header>

      <div class="inventory-filters" role="search" aria-label="Filtres de l’inventaire">
        <input
          v-model="filters.search"
          class="search"
          type="search"
          placeholder="Titre, série ou studio"
          aria-label="Rechercher"
          @keyup.enter="load()"
        >
        <select v-model="filters.media_type" aria-label="Type" @change="load">
          <option value="">Tous les médias</option><option value="movie">Films</option>
          <option value="episode">Épisodes</option><option value="track">Musique</option>
        </select>
        <select v-model="filters.library" aria-label="Bibliothèque" @change="load">
          <option value="">Toutes les bibliothèques</option>
          <option v-for="value in data.options?.library || []" :key="value">{{ value }}</option>
        </select>
        <select v-model="filters.studio" aria-label="Studio" @change="load">
          <option value="">Tous les studios</option>
          <option v-for="value in data.options?.studio || []" :key="value">{{ value }}</option>
        </select>
        <select v-model="filters.video_codec" aria-label="Codec vidéo" @change="load">
          <option value="">Vidéo : tous</option>
          <option v-for="value in data.options?.video_codec || []" :key="value">{{ value }}</option>
        </select>
        <select v-model="filters.audio_codec" aria-label="Codec audio" @change="load">
          <option value="">Audio : tous</option>
          <option v-for="value in data.options?.audio_codec || []" :key="value">{{ value }}</option>
        </select>
        <select v-model="filters.container" aria-label="Conteneur" @change="load">
          <option value="">Conteneurs : tous</option>
          <option v-for="value in data.options?.container || []" :key="value">{{ value }}</option>
        </select>
        <select v-model="filters.subtitle" aria-label="Sous-titres" @change="load">
          <option value="">Sous-titres : tous</option><option value="with">Avec</option>
          <option value="without">Sans</option>
        </select>
        <select v-model="filters.watched" aria-label="Visionnage" @change="load">
          <option value="">Visionnage : tous</option><option value="yes">Déjà visionnés</option>
          <option value="no">Jamais visionnés</option>
        </select>
        <input v-model.number="filters.min_size_gb" type="number" min="0" step="0.5" placeholder="Min. Go" aria-label="Poids minimal en Go" @change="load">
        <input v-model.number="filters.max_size_gb" type="number" min="0" step="0.5" placeholder="Max. Go" aria-label="Poids maximal en Go" @change="load">
        <button v-if="activeCount" type="button" class="secondary reset-button" @click="reset">
          <RotateCcw /> Effacer
        </button>
      </div>

      <div class="inventory-meta">
        <span>{{ number(data.items?.length || 0) }} résultat(s)</span>
        <span v-if="activeCount">{{ activeCount }} filtre(s) actif(s)</span>
      </div>
      <MediaRowsTable :items="visibleItems" />
      <button v-if="limit < (data.items?.length || 0)" type="button" class="secondary load-more" @click="limit += 100">
        Afficher 100 lignes de plus
      </button>
      <p v-if="!loading && !data.items?.length" class="empty">Aucun fichier ne correspond aux filtres.</p>
    </section>

    <section class="workspace-section insights-section">
      <header class="section-heading">
        <div><span class="eyebrow">Exploration</span><h2>Insights interactifs</h2></div>
        <small>Cliquez sur une carte ou une catégorie pour actualiser le tableau.</small>
      </header>

      <MetricGrid v-if="data.summary" class="analytics-metrics">
        <MetricCard label="Fichiers" :value="number(data.summary.items)" detail="filtre actuel" />
        <MetricCard label="Poids total" :value="bytes(data.summary.size_bytes)" detail="stockage observé" />
        <MetricCard label="Durée" :value="duration(data.summary.duration_ms)" detail="contenu cumulé" />
        <MetricCard label="Lectures" :value="number(data.summary.plays)" :detail="`${data.summary.viewers} spectateur(s)`" />
      </MetricGrid>

      <div class="insight-grid">
        <button
          v-for="insight in data.insights || []"
          :key="insight.kind"
          type="button"
          class="panel insight-card"
          :class="{ active: selectedInsight.kind === insight.kind }"
          :aria-pressed="selectedInsight.kind === insight.kind"
          @click="selectInsight(insight)"
        >
          <Lightbulb />
          <div><span>{{ insight.title }}</span><strong>{{ insight.unit === 'bytes' ? bytes(insight.value) : number(insight.value) }}</strong></div>
          <ChevronRight />
        </button>
      </div>

      <div class="analytics-grid">
        <BreakdownPanel
          v-for="chart in charts"
          :key="chart.key"
          :title="chart.title"
          :eyebrow="chart.eyebrow"
          :tone="chart.tone"
          :interactive="!!chart.field"
          :items="breakdown(chart.key)"
          @select="selectDistribution(chart, $event)"
        />
      </div>

      <section class="panel insight-results" aria-live="polite">
        <div class="panel-head">
          <div><span class="eyebrow">Sélection active</span><h2>{{ selectedInsight.title }}</h2></div>
          <strong>{{ number(selectedRows.length) }} fichier(s)</strong>
        </div>
        <MediaRowsTable :items="selectedVisibleRows" />
        <button v-if="insightLimit < selectedRows.length" type="button" class="secondary load-more" @click="insightLimit += 100">
          Afficher 100 lignes de plus
        </button>
        <p v-if="!selectedRows.length" class="empty">Aucun fichier pour cet insight.</p>
      </section>
    </section>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref } from 'vue';
import { ChevronRight, FileDown, Lightbulb, RefreshCw, RotateCcw } from '@lucide/vue';

import { api } from '@/api';
import BreakdownPanel from '@/components/activity/BreakdownPanel.vue';
import MetricCard from '@/components/ui/MetricCard.vue';
import MetricGrid from '@/components/ui/MetricGrid.vue';
import { useRealtime } from '@/events';
import {
  DEFAULT_INSIGHT,
  distributionSelection,
  insightRows,
  insightSelection,
} from '@/libraryAnalyticsInsights';
import {
  formatDateTime,
  formatDurationRoundHours as duration,
  formatFileSize as bytes,
  formatInteger as number,
} from '@/utils/format';

const MediaRowsTable = defineComponent({
  name: 'MediaRowsTable',
  props: { items: { type: Array, default: () => [] } },
  setup(props) {
    const title = row => row.grandparent_title ? `${row.grandparent_title} · ${row.title}` : row.title;
    return () => h('div', { class: 'media-rows', role: 'table', 'aria-label': 'Fichiers média' }, [
      h('div', { class: 'media-row media-row-head', role: 'row' }, ['Titre', 'Vidéo', 'Audio', 'Sous-titres', 'Poids', 'Audience'].map(label => h('span', { role: 'columnheader' }, label))),
      ...props.items.map(row => h('article', { class: 'media-row', role: 'row', key: `${row.rating_key}:${row.title}` }, [
        h('div', { class: 'media-title', role: 'cell' }, [h('strong', title(row)), h('small', `${row.library || '—'} · ${row.studio || '—'}`)]),
        h('span', { role: 'cell' }, `${row.video_codec || '—'} · ${row.video_resolution || '—'}`),
        h('span', { role: 'cell' }, `${row.audio_codec || '—'} · ${row.audio_track_count || 0} piste(s)`),
        h('span', { role: 'cell' }, `${row.subtitle_count || 0} · ${(row.subtitle_languages || []).join(', ') || 'aucun'}`),
        h('span', { role: 'cell' }, bytes(row.size_bytes)),
        h('span', { role: 'cell' }, `${row.play_count || 0} lecture(s) · ${(row.viewers || []).join(', ') || 'personne'}`),
      ])),
    ]);
  },
});

const data = ref({ items: [], options: {}, distributions: {} });
const loading = ref(false);
const error = ref('');
const limit = ref(100);
const insightLimit = ref(100);
const selectedInsight = ref({ ...DEFAULT_INSIGHT });
const filters = reactive({
  search: '', media_type: '', library: '', studio: '', video_codec: '',
  audio_codec: '', container: '', subtitle: '', watched: '',
  min_size_gb: '', max_size_gb: '',
});
const charts = [
  { key: 'types', title: 'Types de médias', eyebrow: 'Catalogue', tone: 'blue', field: 'media_type' },
  { key: 'studios', title: 'Studios principaux', eyebrow: 'Origine', tone: 'accent', field: 'studio' },
  { key: 'video_codecs', title: 'Codecs vidéo', eyebrow: 'Vidéo', tone: 'green', field: 'video_codec' },
  { key: 'audio_codecs', title: 'Codecs audio', eyebrow: 'Audio', tone: 'purple', field: 'audio_codec' },
  { key: 'resolutions', title: 'Résolutions', eyebrow: 'Qualité', tone: 'blue', field: 'video_resolution' },
  { key: 'containers', title: 'Conteneurs', eyebrow: 'Fichiers', tone: 'red', field: 'container' },
];

const params = computed(() => {
  const value = new URLSearchParams();
  Object.entries(filters).forEach(([key, item]) => { if (item !== '' && item != null) value.set(key, item); });
  return value;
});
const activeCount = computed(() => [...params.value].length);
const exportUrl = computed(() => `/api/library-analytics/export.csv?${params.value}`);
const visibleItems = computed(() => (data.value.items || []).slice(0, limit.value));
const selectedRows = computed(() => insightRows(data.value.items || [], selectedInsight.value));
const selectedVisibleRows = computed(() => selectedRows.value.slice(0, insightLimit.value));

function breakdown(key) {
  return (data.value.distributions?.[key] || []).map(item => ({
    label: item.label, value: item.count, detail: `${item.percent} % du catalogue filtré`,
  }));
}
function selectInsight(insight) {
  selectedInsight.value = insightSelection(insight);
  insightLimit.value = 100;
}
function selectDistribution(chart, value) {
  selectedInsight.value = distributionSelection(chart, value);
  insightLimit.value = 100;
}
async function load(refresh = false) {
  loading.value = true;
  error.value = '';
  limit.value = 100;
  insightLimit.value = 100;
  try {
    const query = new URLSearchParams(params.value);
    if (refresh) query.set('refresh', 'true');
    data.value = await api(`/api/library-analytics?${query}`);
  } catch (exception) {
    error.value = exception.message;
  } finally {
    loading.value = false;
  }
}
function reset() {
  Object.keys(filters).forEach(key => { filters[key] = ''; });
  load();
}
function date(value) {
  return value ? `Actualisé ${formatDateTime(value)}` : '';
}

onMounted(() => load());
useRealtime(['library.analytics.updated'], () => load());
</script>

<style scoped>
.export-link{display:inline-flex;align-items:center;gap:7px;text-decoration:none}
.workspace-section{display:grid;gap:16px;padding-top:4px}
.workspace-section+.workspace-section{margin-top:18px;padding-top:28px;border-top:1px solid var(--border)}
.section-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:20px}
.section-heading h2{margin:3px 0 0}.section-heading small,.panel-head small{color:var(--muted)}
.inventory-filters{display:flex;align-items:center;gap:8px;overflow-x:auto;padding:10px;border:1px solid var(--border);border-radius:12px;background:var(--surface)}
.inventory-filters>*{flex:0 0 auto;min-width:130px}.inventory-filters .search{flex:1 0 240px}.inventory-filters input[type=number]{width:105px;min-width:105px}
.inventory-filters .reset-button{min-width:auto}.inventory-meta{display:flex;gap:14px;color:var(--muted);font-size:11px}
.analytics-metrics{grid-template-columns:repeat(4,minmax(0,1fr))}
.insight-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.insight-card{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:12px;width:100%;color:var(--text);text-align:left;cursor:pointer;transition:border-color .2s,transform .2s,background .2s}
.insight-card:hover,.insight-card.active{transform:translateY(-2px);border-color:var(--accent);background:color-mix(in srgb,var(--accent) 8%,var(--surface))}
.insight-card>svg:first-child{width:22px;color:var(--accent)}.insight-card>svg:last-child{width:16px;color:var(--muted)}
.insight-card>div,.media-title{display:grid;min-width:0}.insight-card span{color:var(--muted);font-size:10px}.insight-card strong{font-size:18px}
.analytics-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.insight-results{display:grid;gap:12px}.panel-head>strong{color:var(--accent)}
:deep(.media-rows){display:grid;min-width:0;overflow-x:auto}
:deep(.media-row){display:grid;grid-template-columns:minmax(230px,1.6fr) repeat(5,minmax(115px,1fr));gap:12px;align-items:center;min-width:900px;padding:11px 2px;border-bottom:1px solid var(--border);font-size:11px}
:deep(.media-row-head){position:sticky;top:0;z-index:1;padding-block:8px;background:var(--surface);color:var(--muted);font-size:9px;font-weight:700;text-transform:uppercase}
:deep(.media-row small){overflow:hidden;color:var(--muted);font-size:9px;text-overflow:ellipsis;white-space:nowrap}
:deep(.media-row strong){overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.load-more{justify-self:center}
@media(max-width:900px){.analytics-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.insight-grid{grid-template-columns:1fr}.inventory-filters{align-items:stretch}.section-heading{align-items:flex-start}}
@media(max-width:720px){.analytics-grid{grid-template-columns:1fr}.section-heading{display:grid}.inventory-filters .search{flex-basis:200px}}
@media(max-width:420px){.analytics-metrics{grid-template-columns:1fr}}
</style>
