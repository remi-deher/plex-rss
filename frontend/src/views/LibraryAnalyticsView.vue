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

    <nav class="analytics-tabs" aria-label="Vues de la médiathèque">
      <button type="button" :class="{ active: activeTab === 'table' }" @click="activeTab = 'table'">Tableau</button>
      <button type="button" :class="{ active: activeTab === 'insights' }" @click="activeTab = 'insights'">Insights</button>
    </nav>

    <section v-if="activeTab === 'table'" class="workspace-section inventory-section">
      <header class="section-heading">
        <div><span class="eyebrow">Inventaire</span><h2>Fichiers analysés</h2></div>
        <small>{{ date(data.generated_at) }}</small>
      </header>

      <div class="inventory-meta">
        <span>{{ number(data.items?.length || 0) }} résultat(s)</span>
        <span v-if="activeCount">{{ activeCount }} filtre(s) actif(s)</span>
      </div>
      <MediaRowsTable :items="visibleItems" :filters="filters" :options="data.options" :active-count="activeCount" filterable @update-filter="updateFilter" @reset="reset" />
      <button v-if="limit < (data.items?.length || 0)" type="button" class="secondary load-more" @click="limit += 100">
        Afficher 100 lignes de plus
      </button>
      <p v-if="!loading && !data.items?.length" class="empty">Aucun fichier ne correspond aux filtres.</p>
    </section>

    <section v-else class="workspace-section insights-section">
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
import { computed, onMounted, reactive, ref } from 'vue';
import { ChevronRight, FileDown, Lightbulb, RefreshCw } from '@lucide/vue';

import { api } from '@/api';
import BreakdownPanel from '@/components/activity/BreakdownPanel.vue';
import MetricCard from '@/components/ui/MetricCard.vue';
import MetricGrid from '@/components/ui/MetricGrid.vue';
import MediaRowsTable from '@/components/library/MediaRowsTable.vue';
import { useRealtime } from '@/events';
import {
  DEFAULT_INSIGHT,
  analyticsForFilters,
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

const snapshot = ref({ items: [], options: {}, distributions: {} });
const activeTab = ref('table');
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
const data = computed(() => analyticsForFilters(snapshot.value, filters));
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
    snapshot.value = await api(`/api/library-analytics?${refresh ? 'refresh=true' : ''}`);
  } catch (exception) {
    error.value = exception.message;
  } finally {
    loading.value = false;
  }
}
function reset() {
  Object.keys(filters).forEach(key => { filters[key] = ''; });
}
function updateFilter({ key, value }) {
  filters[key] = ['min_size_gb', 'max_size_gb'].includes(key) && value !== '' ? Number(value) : value;
  limit.value = 100;
}
function date(value) {
  return value ? `Actualisé ${formatDateTime(value)}` : '';
}

onMounted(() => load());
useRealtime(['library.analytics.updated'], () => load());
</script>

<style scoped>
.export-link{display:inline-flex;align-items:center;gap:7px;text-decoration:none}
.analytics-tabs{display:flex;gap:4px;margin-bottom:18px;padding:4px;border:1px solid var(--border);border-radius:12px;background:var(--surface)}
.analytics-tabs button{flex:1;border:0;border-radius:8px;background:transparent;color:var(--muted)}
.analytics-tabs button.active{background:var(--surface-2);color:var(--text);box-shadow:0 1px 4px rgba(0,0,0,.16)}
.workspace-section{display:grid;gap:16px;padding-top:4px}
.section-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:20px}
.section-heading h2{margin:3px 0 0}.section-heading small,.panel-head small{color:var(--muted)}
.inventory-meta{display:flex;gap:14px;color:var(--muted);font-size:11px}
.analytics-metrics{grid-template-columns:repeat(4,minmax(0,1fr))}
.insight-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.insight-card{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:12px;width:100%;color:var(--text);text-align:left;cursor:pointer;transition:border-color .2s,transform .2s,background .2s}
.insight-card:hover,.insight-card.active{transform:translateY(-2px);border-color:var(--accent);background:color-mix(in srgb,var(--accent) 8%,var(--surface))}
.insight-card>svg:first-child{width:22px;color:var(--accent)}.insight-card>svg:last-child{width:16px;color:var(--muted)}
.insight-card>div,.media-title{display:grid;min-width:0}.insight-card span{color:var(--muted);font-size:10px}.insight-card strong{font-size:18px}
.analytics-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.insight-results{display:grid;gap:12px}.panel-head>strong{color:var(--accent)}
.load-more{justify-self:center}
@media(max-width:900px){.analytics-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.insight-grid{grid-template-columns:1fr}.section-heading{align-items:flex-start}}
@media(max-width:720px){.analytics-grid{grid-template-columns:1fr}.section-heading{display:grid}}
@media(max-width:420px){.analytics-metrics{grid-template-columns:1fr}}
</style>
