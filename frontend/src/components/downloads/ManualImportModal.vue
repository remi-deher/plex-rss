<template>
  <div class="drawer-backdrop" @click.self="$emit('close')">
    <aside class="modal-panel import-modal">
      <div class="panel-head">
        <div>
          <h2>Associer / Importer</h2>
          <p style="font-size:13px;margin-top:4px">{{ row.title }}</p>
        </div>
        <button class="icon-button" title="Fermer" @click="$emit('close')"><X/></button>
      </div>

      <p v-if="error" class="notice error-text">{{ error }}</p>

      <div class="import-steps">
        <div class="import-step">
          <div class="step-num">1</div>
          <div class="step-body">
            <strong>Identifier le media</strong>
            <div class="inline-row" style="margin-top:8px">
              <input v-model="lookupQuery" placeholder="Chercher dans Sonarr/Radarr">
              <button class="secondary" @click="lookup"><Search/>Chercher</button>
            </div>
            <div v-if="manual.arr_id && !lookupResults.length" class="notice" style="margin-top:8px">
              ✅ Média auto-détecté : <strong>{{ manual.title }}</strong>
            </div>
            <div v-if="lookupResults.length" class="lookup-list">
              <button v-for="item in lookupResults" :key="`${item.title}:${item.year}`" class="lookup-result" :class="{selected:manual.arr_id===item.arr_id}" @click="pickLookup(item)">
                <strong>{{ item.title }}</strong>
                <span>{{ item.year }} · {{ item.already_added?'Déjà dans Sonarr/Radarr':'Non ajouté' }}</span>
              </button>
            </div>
          </div>
        </div>

        <div class="import-step">
          <div class="step-num">2</div>
          <div class="step-body">
            <strong>Informations du media</strong>
            <div class="settings-grid two" style="margin-top:8px">
              <label>Titre<input v-model="manual.title"></label>
              <label>Annee<input v-model.number="manual.year" type="number"></label>
            </div>
          </div>
        </div>

        <div v-if="row.arr_type==='sonarr'" class="import-step">
          <div class="step-num">3</div>
          <div class="step-body">
            <strong>Episode a importer</strong>
            <p v-if="targetsLoading" style="margin-top:8px">Chargement des saisons et episodes...</p>
            <template v-else>
              <div class="settings-grid two" style="margin-top:8px">
                <label>Saison<select v-model.number="episodeForm.season"><option v-for="season in seasonOptions" :key="season" :value="season">Saison {{ season }}</option></select></label>
                <label>Episode<select v-model.number="episodeForm.episode_id"><option v-for="episode in filteredEpisodes" :key="episode.id" :value="episode.id">E{{ String(episode.episodeNumber).padStart(2,'0') }} · {{ episode.title||'Sans titre' }}</option></select></label>
              </div>
              <label v-if="episodeCandidates.length" style="margin-top:8px">Fichier a importer<select v-model.number="episodeForm.candidate"><option v-for="(candidate,index) in episodeCandidates" :key="candidate.path" :value="index">{{ candidate.path }}</option></select></label>
              <p v-else class="warning-text" style="margin-top:8px">Aucun fichier importable detecte. L'association a la serie reste possible.</p>
            </template>
          </div>
        </div>

        <div v-if="row.arr_type==='radarr'" class="import-step">
          <div class="step-num">3</div>
          <div class="step-body">
            <strong>Fichier a importer</strong>
            <p v-if="targetsLoading" style="margin-top:8px">Chargement des fichiers...</p>
            <template v-else>
              <label v-if="episodeCandidates.length" style="margin-top:8px">Fichier<select v-model.number="episodeForm.candidate"><option v-for="(candidate,index) in episodeCandidates" :key="candidate.path" :value="index">{{ candidate.path }}</option></select></label>
              <p v-else class="warning-text" style="margin-top:8px">Aucun fichier importable detecte. L'association au film reste possible.</p>
            </template>
          </div>
        </div>
      </div>

      <div class="form-actions" style="margin-top:16px">
        <button class="secondary" @click="$emit('close')">Annuler</button>
        <button class="primary" :disabled="busy||targetsLoading||!manual.title||!manual.arr_id||(row.arr_type==='sonarr'&&!episodeForm.episode_id)" @click="submitManual">
          <Clapperboard v-if="(row.arr_type==='sonarr'||row.arr_type==='radarr')&&episodeCandidates.length"/>
          <Link v-else/>
          {{ (row.arr_type==='sonarr'||row.arr_type==='radarr')&&episodeCandidates.length?'Associer et importer':'Associer' }}
        </button>
      </div>
    </aside>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { Clapperboard, Link, Search, X } from '@lucide/vue';
import { api } from '@/api';

const props = defineProps({ row: { type: Object, required: true } });
const emit = defineEmits(['close', 'submitted']);

const lookupQuery = ref(''), lookupResults = ref([]), episodeCandidates = ref([]), episodeOptions = ref([]);
const targetsLoading = ref(false), busy = ref(false), error = ref('');
const manual = reactive({ title: '', year: null, tmdb_id: null, tvdb_id: null, poster_url: null, arr_id: null });
const episodeForm = reactive({ candidate: 0, season: null, episode_id: null });

const seasonOptions = computed(() => [...new Set(episodeOptions.value.map(x => x.seasonNumber).filter(x => x != null && x > 0))].sort((a, b) => a - b));
const filteredEpisodes = computed(() => episodeOptions.value.filter(x => x.seasonNumber === episodeForm.season).sort((a, b) => a.episodeNumber - b.episodeNumber));

async function lookup() {
  lookupResults.value = await api(`/api/media/lookup?query=${encodeURIComponent(lookupQuery.value)}&type=${props.row.arr_type === 'sonarr' ? 'show' : 'movie'}`);
}

async function pickLookup(item) {
  Object.assign(manual, { title: item.title, year: item.year, tmdb_id: item.tmdb_id, tvdb_id: item.tvdb_id, poster_url: item.poster, arr_id: item.arr_id });
  if (props.row.arr_type === 'sonarr' && item.arr_id) await loadSonarrTargets();
  if (props.row.arr_type === 'radarr' && item.arr_id) await loadRadarrTargets();
}

async function loadSonarrTargets() {
  targetsLoading.value = true;
  try {
    const download = props.row.download_id ? `&download_id=${encodeURIComponent(props.row.download_id)}` : '';
    const data = await api(`/api/downloads/sonarr-manual-import?instance_id=${props.row.instance_id}&series_id=${manual.arr_id}${download}`);
    episodeCandidates.value = data.candidates || [];
    episodeOptions.value = data.episodes || [];
    episodeForm.season = seasonOptions.value.includes(episodeForm.season) ? episodeForm.season : seasonOptions.value[0] || null;
    const preferred = filteredEpisodes.value.find(x => x.episodeNumber === props.row.episode_number);
    episodeForm.episode_id = preferred?.id || filteredEpisodes.value[0]?.id || null;
  } catch (e) { error.value = e.message; } finally { targetsLoading.value = false; }
}

async function loadRadarrTargets() {
  targetsLoading.value = true;
  try {
    const download = props.row.download_id ? `&download_id=${encodeURIComponent(props.row.download_id)}` : '';
    const data = await api(`/api/downloads/radarr-manual-import?instance_id=${props.row.instance_id}&movie_id=${manual.arr_id}${download}`);
    episodeCandidates.value = data.candidates || [];
  } catch (e) { error.value = e.message; } finally { targetsLoading.value = false; }
}

async function submitManual() {
  busy.value = true;
  try {
    await api('/api/downloads/manual-import', { method: 'POST', body: JSON.stringify({ instance_id: props.row.instance_id, media_type: props.row.arr_type === 'sonarr' ? 'show' : 'movie', title: manual.title, arr_id: manual.arr_id, year: manual.year, tmdb_id: manual.tmdb_id, tvdb_id: manual.tvdb_id, poster_url: manual.poster_url }) });
    const candidate = episodeCandidates.value[episodeForm.candidate];
    if (props.row.arr_type === 'sonarr' && candidate && episodeForm.episode_id) {
      await api('/api/downloads/sonarr-manual-import', { method: 'POST', body: JSON.stringify({ instance_id: props.row.instance_id, series_id: manual.arr_id, episode_id: episodeForm.episode_id, path: candidate.path, folder_name: candidate.folderName || candidate.folder_name, download_id: props.row.download_id, quality: candidate.quality, languages: candidate.languages, release_group: candidate.releaseGroup, indexer_flags: candidate.indexerFlags }) });
    }
    if (props.row.arr_type === 'radarr' && candidate) {
      await api('/api/downloads/radarr-manual-import', { method: 'POST', body: JSON.stringify({ instance_id: props.row.instance_id, movie_id: manual.arr_id, path: candidate.path, folder_name: candidate.folderName || candidate.folder_name, download_id: props.row.download_id, quality: candidate.quality, languages: candidate.languages, release_group: candidate.releaseGroup, indexer_flags: candidate.indexerFlags }) });
    }
    emit('submitted');
  } catch (e) { error.value = e.message; } finally { busy.value = false; }
}

watch(() => episodeForm.season, () => {
  if (!filteredEpisodes.value.some(x => x.id === episodeForm.episode_id)) episodeForm.episode_id = filteredEpisodes.value[0]?.id || null;
});

onMounted(() => {
  Object.assign(manual, { title: props.row.series_title || props.row.title || '', year: props.row.year || null, tmdb_id: props.row.tmdb_id || null, tvdb_id: props.row.tvdb_id || null, poster_url: props.row.poster_url || null, arr_id: props.row.arr_media_id || null });
  lookupQuery.value = manual.title;
  episodeForm.season = props.row.season_number || null;
  if (props.row.arr_type === 'sonarr' && manual.arr_id) loadSonarrTargets();
  if (props.row.arr_type === 'radarr' && manual.arr_id) loadRadarrTargets();
});
</script>
