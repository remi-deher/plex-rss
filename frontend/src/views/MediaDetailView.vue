<template>
  <div class="media-detail-page">
    <div v-if="loading" class="drawer-loading"><LoaderCircle class="spin" /> Chargement</div>
    <template v-else-if="detail">
      <MediaDetailHero
        :detail="detail"
        :status-label="statusLabel"
        :status-class="statusClass"
        :admin="admin"
        @back="goBack"
        @report-issue="showIssueForm = !showIssueForm"
      />

      <div class="media-detail-body">
        <p v-if="error" class="notice error-text">{{ error }}</p>

        <MediaRequestForm
          v-if="canRequest"
          :detail="detail"
          :form="requestForm"
          :requesters="requesters"
          :folders="folders"
          :busy="busy"
          @submit="submitRequest"
        />

        <template v-if="kind !== 'discover'">
          <nav class="detail-tabs" style="overflow-x: auto; display: flex; gap: 0.5rem; white-space: nowrap; padding-bottom: 0.5rem;">
            <button v-for="entry in tabs" :key="entry" :class="{active:tab===entry}" @click="tab=entry">{{ tabLabel(entry) }}</button>
          </nav>

          <MediaRequestsTab
            v-if="tab === 'requests'"
            :requests="detail.requests"
            :admin="admin"
            :busy="busy"
            :addable-users="addableUsers"
            v-model:new-requester-id="newRequesterId"
            @add-requester="addRequester"
            @open-release="id => router.push(`/releases/${id}`)"
            @retry="id => requestAction(id, 'retry')"
            @catch-up-all="catchUpAll"
            @resend-mail="resendMail"
            @close-request="closeRequest"
            @delete-request="deleteRequest"
            @notify-user="notifyUser"
            @promote-requester="promoteRequester"
            @remove-requester="removeRequester"
          />

          <MediaCalendarTab v-else-if="tab === 'calendar'" :events="detail.calendar" />

          <MediaSummaryTab
            v-else
            :detail="detail"
            :busy="busy"
            :show-issue-form="showIssueForm"
            :show-correction-form="showCorrectionForm"
            :users="users"
            :correction-options="correctionOptions"
            :correction-form="correctionForm"
            :vf-detail="mergedVfDetail"
            :envelope-error="envelopeError"
            :availability-error="availabilityError"
            :vf-status-error="vfStatusError"
            @recheck-plex="recheckPlex"
            @open-correction="openCorrection"
            @report-issue="reportIssue"
            @cancel-issue="showIssueForm = false"
            @submit-correction="sendCorrection"
            @cancel-correction="showCorrectionForm = false"
            @scan-vff="scanVff"
            @expand-season="loadSeasonEpisodes"
          />
        </template>

        <MediaRecommendations
          v-if="kind === 'discover'"
          :items="recommendations"
          @open="item => router.push(mediaDetailPath(item, 'discover'))"
        />
      </div>
    </template>
  </div>
  <ConfirmModal v-bind="confirmDialog" @cancel="resolveConfirm(false)" @confirm="resolveConfirm(true)" />
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { LoaderCircle } from "@lucide/vue";
import { useRoute, useRouter } from "vue-router";
import { api } from "@/api";
import { mediaDetailPath } from "@/mediaUrl";
import MediaDetailHero from "@/components/media/MediaDetailHero.vue";
import MediaSummaryTab from "@/components/media/MediaSummaryTab.vue";
import MediaRequestsTab from "@/components/media/MediaRequestsTab.vue";
import MediaCalendarTab from "@/components/media/MediaCalendarTab.vue";
import MediaRequestForm from "@/components/media/MediaRequestForm.vue";
import MediaRecommendations from "@/components/media/MediaRecommendations.vue";
import ConfirmModal from "@/components/ConfirmModal.vue";
import { useConfirm } from "@/composables/useConfirm";

const route = useRoute();
const router = useRouter();

const detail = ref(null), requesters = ref([]), folders = ref([]), vfDetail = ref(null);
// Chargement progressif de l'accordeon saisons/episodes (facon Seerr) : l'enveloppe
// (titres/numeros, TMDB) s'affiche des qu'elle arrive, disponibilite (Sonarr) et
// statut VF/VO (BDD) se completent ensuite en parallele sans bloquer l'affichage.
// Les films restent sur l'ancien flux vfDetail (scan Plex des pistes audio, deja
// hors-chemin critique du reste de la page).
const episodesEnvelope = ref(null), availability = ref(null), vfStatus = ref(null);
const envelopeError = ref(false);
// Episodes charges saison par saison, uniquement quand l'utilisateur deplie la saison
// (facon Seerr : GET /tv/:id/season/:n) -- l'enveloppe ne contient que le nombre de
// saisons/episodes, jamais le detail episode par episode de toutes les saisons d'un coup.
const seasonEpisodes = ref({}), seasonLoading = ref({}), seasonErrors = ref({});
const loading = ref(false), busy = ref(false), error = ref(''), tab = ref('summary');
const requestForm = reactive({ plex_user_id: '', root_folder: '', seasons: [] });
const tabs = ['summary', 'requests', 'calendar'];
const admin = ref(false);
const { dialog: confirmDialog, askConfirm, resolveConfirm } = useConfirm();

const showIssueForm = ref(false), showCorrectionForm = ref(false);
const users = ref([]), correctionOptions = ref([]);
const correctionForm = reactive({ scope: 'media', season_number: null, episode_number: null, recipient_user_ids: [], corrections: [], note: '' });
const newRequesterId = ref('');

const kind = computed(() => route.params.kind);

const typeLabel = computed(() => detail.value?.media_type === 'show' ? 'Serie' : 'Film');
const statusLabel = computed(() => detail.value?.available || detail.value?.in_library ? 'Disponible' : detail.value?.requested ? 'Deja demande' : detail.value?.request_status || '');
const statusClass = computed(() => detail.value?.available || detail.value?.in_library ? 'available' : 'pending');
const canRequest = computed(() => kind.value === 'discover' && !detail.value?.available && !detail.value?.in_library && !detail.value?.requested);
const seasonNumbers = computed(() => Array.from({ length: Number(detail.value?.number_of_seasons || 0) + 1 }, (_, i) => i));
const recommendations = computed(() => [...(detail.value?.recommendations || []), ...(detail.value?.similar || [])].slice(0, 6));
const addableUsers = computed(() => {
  const already = new Set((detail.value?.requests || []).flatMap(row => row.requester_ids || [row.plex_user_id]));
  return users.value.filter(u => !already.has(u.plex_user_id));
});

// Fusionne les 3 sources independantes (enveloppe TMDB, disponibilite Sonarr,
// statut VF/VO en BDD) des qu'elles arrivent -- reactif : chaque champ se met a
// jour a mesure que son fetch resout, sans attendre les deux autres.
const mergedVfDetail = computed(() => {
  if (detail.value?.media_type !== 'show') return vfDetail.value;
  if (!episodesEnvelope.value) return null;
  const availBySeason = Object.fromEntries((availability.value?.seasons || []).map(s => [s.season_number, s.episodes]));
  const vfBySeason = Object.fromEntries((vfStatus.value?.seasons || []).map(s => [s.season_number, s.episodes]));
  const seasons = episodesEnvelope.value.seasons.map(season => {
    const episodesData = seasonEpisodes.value[season.season_number];
    if (!episodesData) {
      // Saison pas encore depliee : ni compteurs ni episodes tant que TMDB n'a pas ete
      // interroge pour CETTE saison precise (voir loadSeasonEpisodes, declenche par
      // @expand-season au deploiement du <details> cote MediaAudioSection).
      return {
        season_number: season.season_number, name: season.name, episode_count: season.episode_count,
        loaded: false, loading: !!seasonLoading.value[season.season_number], error: !!seasonErrors.value[season.season_number],
        counts: {}, episodes: [],
      };
    }
    const availEps = availBySeason[season.season_number] || {};
    const vfEps = vfBySeason[season.season_number] || {};
    const counts = { vf: 0, vf_secondary: 0, vo: 0, present: 0, absent: 0, tba: 0, unknown: 0 };
    const episodes = episodesData.map(ep => {
      const availInfo = availEps[ep.episode_number];
      const hasFile = availInfo?.has_file;
      // Sonarr (air_date_utc) fait foi car precis a l'heure pres ; TMDB (air_date,
      // date seule) sert de repli quand Sonarr n'a pas repondu.
      const airDate = availInfo?.air_date_utc || ep.air_date;
      const hasAired = !airDate || new Date(airDate) <= new Date();
      let status;
      if (vfEps[ep.episode_number]) status = vfEps[ep.episode_number];
      else if (hasFile === undefined) status = 'unknown';
      else if (hasFile) status = 'present';
      else status = hasAired ? 'absent' : 'tba';
      counts[status] = (counts[status] || 0) + 1;
      return {
        episode: ep.episode_number, title: ep.title, air_date: airDate, status, has_file: hasFile,
        overview: ep.overview, still_url: ep.still_url,
      };
    });
    return { season_number: season.season_number, name: season.name, loaded: true, counts, episodes };
  });
  return { enabled: true, media_type: 'show', vf_available: true, seasons };
});

function tabLabel(value) { return ({ summary: 'Resume', requests: 'Demandes', calendar: 'Calendrier' })[value]; }

function mediaPath() {
  const id = route.params.id;
  if (kind.value === 'discover') {
    const p = new URLSearchParams();
    p.set('media_type', route.query.media_type || '');
    if (route.query.id_type === 'tvdb') p.set('tvdb_id', id); else p.set('tmdb_id', id);
    return `/api/discover/detail?${p}`;
  }
  if (kind.value === 'request') return `/api/media/detail?request_id=${id}`;
  return `/api/media/detail?library_id=${id}`;
}

async function loadUsers() {
  try {
    users.value = await api('/api/users');
    correctionOptions.value = await api('/api/media/corrections/options');
  } catch (e) {}
}

async function loadSession() {
  try {
    const session = await api('/api/session');
    admin.value = Boolean(session?.is_owner || session?.role === 'admin');
  } catch (e) { admin.value = false; }
}

async function load() {
  loading.value = true; error.value = ''; vfDetail.value = null;
  episodesEnvelope.value = null; availability.value = null; vfStatus.value = null;
  envelopeError.value = false; availabilityError.value = false; vfStatusError.value = false;
  seasonEpisodes.value = {}; seasonLoading.value = {}; seasonErrors.value = {};
  tab.value = 'summary';
  try {
    const payload = await api(mediaPath());
    detail.value = kind.value === 'discover' ? payload : { ...payload.media, ...payload };
    if (kind.value === 'discover') {
      requesters.value = await api('/api/discover/requesters');
      requestForm.plex_user_id = requesters.value[0]?.plex_user_id || '';
      requestForm.seasons = seasonNumbers.value.filter(season => season !== 0);
      const service = detail.value.media_type === 'show' ? 'sonarr' : 'radarr';
      folders.value = await api(`/api/${service}/folders`).catch(() => []);
    }
  } catch (e) { error.value = e.message; } finally { loading.value = false; }

  if (kind.value !== 'discover') {
    // Chaque appel se resout independamment -- l'enveloppe (rapide, TMDB) affiche
    // l'accordeon des qu'elle arrive, sans attendre disponibilite/VF (Sonarr/BDD),
    // qui completent ensuite les badges au fil de l'eau (voir mergedVfDetail).
    Promise.all([loadEpisodesEnvelope(), loadAvailability(), loadVfStatus(), loadUsers(), loadSession()]).catch(() => {});
  } else {
    loadSession().catch(() => {});
  }
}

function goBack() {
  if (window.history.state?.back) router.back();
  else router.push('/library');
}

function openCorrection(scope, season, episode) {
  correctionForm.scope = scope;
  correctionForm.season_number = season;
  correctionForm.episode_number = episode;
  const reqIds = (detail.value?.requests || []).map(r => r.plex_user_id);
  correctionForm.recipient_user_ids = users.value.filter(u => reqIds.includes(u.plex_user_id)).map(u => u.id);
  showCorrectionForm.value = true;
  showIssueForm.value = false;
}

async function submitRequest() {
  busy.value = true; error.value = '';
  try {
    const data = await api('/api/media/add', { method: 'POST', body: JSON.stringify({ title: detail.value.title, year: detail.value.year, media_type: detail.value.media_type, tmdb_id: detail.value.tmdb_id, tvdb_id: detail.value.tvdb_id, imdb_id: detail.value.imdb_id, poster_url: detail.value.poster_url, overview: detail.value.overview, plex_user_id: requestForm.plex_user_id, root_folder: requestForm.root_folder || null, seasons: detail.value.media_type === 'show' ? requestForm.seasons : null, auto_search: true }) });
    detail.value.requested = true;
    detail.value.request_status = data.pending_approval ? 'pending_approval' : 'sent_to_arr';
  } catch (e) { error.value = e.message; } finally { busy.value = false; }
}

async function requestAction(id, action) {
  busy.value = true;
  try { await api(`/api/requests/${id}/${action}`, { method: 'POST' }); await load(); }
  catch (e) { error.value = e.message; } finally { busy.value = false; }
}

async function closeRequest(row) {
  const notify = await askConfirm({ title: 'Notifier la disponibilité ?', message: 'Un email de disponibilité sera envoyé au demandeur.', confirmLabel: 'Notifier' });
  let stopVfTracking = false;
  if (row.has_vf !== true) {
    stopVfTracking = await askConfirm({ title: 'Arrêter la surveillance VO → VF ?', message: 'La demande ne sera plus vérifiée pour une amélioration en VF.', confirmLabel: 'Arrêter la surveillance', danger: true });
  }
  busy.value = true;
  try {
    await api(`/api/requests/${row.id}/mark-processed?event=available&notify=${notify}&stop_vf_tracking=${stopVfTracking}`, { method: 'POST' });
    await load();
  } catch (e) { error.value = e.message; } finally { busy.value = false; }
}

async function resendMail(id, event) {
  busy.value = true;
  try { await api(`/api/requests/${id}/resend-mail?event=${event}`, { method: 'POST' }); await load(); }
  catch (e) { error.value = e.message; } finally { busy.value = false; }
}

async function notifyUser(requestId, plexUserId, events) {
  busy.value = true; error.value = '';
  try {
    await api(`/api/requests/${requestId}/notify-user`, { method: 'POST', body: JSON.stringify({ plex_user_id: plexUserId, events }) });
    await load();
  } catch (e) { error.value = e.message; } finally { busy.value = false; }
}

async function addRequester() {
  busy.value = true; error.value = '';
  try {
    const rows = detail.value.requests || [];
    const newUserId = newRequesterId.value;
    const rowsAlreadyInProgress = rows.filter(row => row.request_mail_sent || row.status === 'available');
    for (const row of rows) {
      const ids = [...(row.requester_ids || [row.plex_user_id])];
      if (!ids.includes(newUserId)) ids.push(newUserId);
      await api(`/api/requests/${row.id}/requesters`, { method: 'PUT', body: JSON.stringify({ requester_ids: ids }) });
    }
    await load();
    newRequesterId.value = '';
    if (rowsAlreadyInProgress.length && await askConfirm({ title: 'Renvoyer les notifications précédentes ?', message: 'Le nouveau co-demandeur recevra également les emails déjà envoyés pour cette demande.', confirmLabel: 'Renvoyer les notifications' })) {
      for (const row of rowsAlreadyInProgress) {
        const events = [];
        if (row.request_mail_sent) events.push('request');
        if (row.status === 'available') events.push('available');
        if (events.length) await notifyUser(row.id, newUserId, events);
      }
    }
  } catch (e) { error.value = e.message; } finally { busy.value = false; }
}

async function catchUpAll(row) {
  busy.value = true; error.value = '';
  try {
    for (const uid of row.requester_ids || []) {
      const n = row.requester_notifications?.[uid];
      const wanted = row.status === 'available' ? n?.available : n?.request;
      if (wanted !== false) continue;
      const events = row.status === 'available' ? ['available'] : ['request'];
      await api(`/api/requests/${row.id}/notify-user`, { method: 'POST', body: JSON.stringify({ plex_user_id: uid, events }) });
    }
    await load();
  } catch (e) { error.value = e.message; } finally { busy.value = false; }
}

async function promoteRequester(row, uid) {
  busy.value = true; error.value = '';
  try {
    const ids = [uid, ...(row.requester_ids || []).filter(id => id !== uid)];
    await api(`/api/requests/${row.id}/requesters`, { method: 'PUT', body: JSON.stringify({ requester_ids: ids }) });
    await load();
  } catch (e) { error.value = e.message; } finally { busy.value = false; }
}

async function removeRequester(row, uid) {
  if (!await askConfirm({ title: 'Retirer ce demandeur ?', message: 'Il ne recevra plus les notifications de cette demande.', confirmLabel: 'Retirer', danger: true })) return;
  busy.value = true; error.value = '';
  try {
    const ids = (row.requester_ids || []).filter(id => id !== uid);
    await api(`/api/requests/${row.id}/requesters`, { method: 'PUT', body: JSON.stringify({ requester_ids: ids }) });
    await load();
  } catch (e) { error.value = e.message; } finally { busy.value = false; }
}

async function deleteRequest(id) {
  if (!await askConfirm({ title: 'Supprimer cette demande ?', message: 'La demande sera supprimée définitivement.', confirmLabel: 'Supprimer', danger: true })) return;
  busy.value = true;
  try { await api(`/api/requests/${id}`, { method: 'DELETE' }); router.push('/requests'); }
  catch (e) { error.value = e.message; } finally { busy.value = false; }
}

// vf_source_id peut pointer vers un LibraryItem meme si la page a ete ouverte via une
// MediaRequest (des qu'un media est aussi present dans la bibliotheque Plex) -- le
// backend renvoie toujours vf_source_type/vf_source_id ensemble (une seule source de
// verite, jamais de repli sur kind.value/route.params.id qui pourraient diverger).
function sourcePath() { return detail.value?.media?.vf_source_type === 'library' ? 'library' : 'requests'; }
function sourceId() { return detail.value?.media?.vf_source_id; }

const availabilityError = ref(false), vfStatusError = ref(false);

async function loadVf() {
  // Films uniquement (scan Plex des pistes audio, deja hors du chemin critique) --
  // les series passent par loadEpisodesEnvelope/loadAvailability/loadVfStatus.
  vfDetail.value = await api(`/api/${sourcePath()}/${sourceId()}/vf-detail`);
}

async function loadEpisodesEnvelope() {
  if (detail.value?.media_type !== 'show') return;
  envelopeError.value = false;
  try { episodesEnvelope.value = await api(`/api/${sourcePath()}/${sourceId()}/episodes`); }
  catch (e) { envelopeError.value = true; }
}

async function loadAvailability(force = false) {
  if (detail.value?.media_type !== 'show') return;
  availabilityError.value = false;
  // Erreur geree ici (pas de propagation) : une panne Sonarr ne doit jamais empecher
  // l'enveloppe (TMDB) ou le statut VF (BDD) de s'afficher -- chaque source est
  // independante, une panne reste localisee et visible plutot que de tout bloquer.
  // Par defaut lecture DB pure (alimentee en arriere-plan) ; force=true (bouton
  // "Actualiser") resynchronise Sonarr immediatement au lieu d'attendre le prochain
  // cycle planifie.
  try { availability.value = await api(`/api/${sourcePath()}/${sourceId()}/episodes-availability${force ? '?force=true' : ''}`); }
  catch (e) { availabilityError.value = true; }
}

async function loadVfStatus() {
  if (detail.value?.media_type !== 'show') return;
  vfStatusError.value = false;
  try { vfStatus.value = await api(`/api/${sourcePath()}/${sourceId()}/episodes-vf-status`); }
  catch (e) { vfStatusError.value = true; }
}

async function loadSeasonEpisodes(seasonNumber) {
  // Deplie une saison (facon Seerr) : les episodes de CETTE saison ne sont demandes a
  // TMDB qu'a ce moment-la, jamais toutes les saisons d'un coup au chargement de la
  // fiche. Ne recharge pas une saison deja chargee ou en cours de chargement.
  if (seasonEpisodes.value[seasonNumber] || seasonLoading.value[seasonNumber]) return;
  seasonLoading.value = { ...seasonLoading.value, [seasonNumber]: true };
  seasonErrors.value = { ...seasonErrors.value, [seasonNumber]: false };
  try {
    const data = await api(`/api/${sourcePath()}/${sourceId()}/episodes/${seasonNumber}`);
    seasonEpisodes.value = { ...seasonEpisodes.value, [seasonNumber]: data.episodes };
  } catch (e) {
    seasonErrors.value = { ...seasonErrors.value, [seasonNumber]: true };
  } finally {
    seasonLoading.value = { ...seasonLoading.value, [seasonNumber]: false };
  }
}

async function scanVff() {
  busy.value = true;
  try {
    await api(`/api/${sourcePath()}/${sourceId()}/vff-scan`, { method: 'POST' });
    if (detail.value?.media_type === 'show') await Promise.all([loadAvailability(true), loadVfStatus()]);
    else await loadVf();
  } catch (e) { error.value = e.message; } finally { busy.value = false; }
}

async function recheckPlex() {
  busy.value = true;
  try {
    const media = detail.value.media || {};
    await api(`/api/media/recheck-plex?${media.library_id ? `library_id=${media.library_id}` : `request_id=${media.request_id}`}`, { method: 'POST' });
    await load();
  } catch (e) { error.value = e.message; } finally { busy.value = false; }
}

async function reportIssue(issueMessage) {
  busy.value = true;
  try {
    const media = detail.value.media || {};
    await api('/api/media/issues', { method: 'POST', body: JSON.stringify({ library_id: media.library_id, request_id: media.request_id, issue_type: 'other', message: issueMessage }) });
    showIssueForm.value = false;
    await load();
  } catch (e) { error.value = e.message; } finally { busy.value = false; }
}

async function sendCorrection(formPayload) {
  busy.value = true; error.value = '';
  try {
    const media = detail.value.media || {};
    await api('/api/media/send-correction', { method: 'POST', body: JSON.stringify({ ...formPayload, library_id: media.library_id, request_id: media.request_id }) });
    showCorrectionForm.value = false;
    alert('Correction envoyee !');
  } catch (e) { error.value = e.message; } finally { busy.value = false; }
}

watch(() => [route.params.kind, route.params.id, route.query.media_type, route.query.id_type], load);
onMounted(load);
</script>

<style scoped>
.media-detail-page {
  min-height: 100%;
}
.media-detail-body {
  max-width: 1280px;
  margin: 0 auto;
  padding: 0 28px 40px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.drawer-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 80px 0;
  color: var(--muted);
}
</style>
