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
        <UiFeedback v-if="successMessage" type="success" :message="successMessage" dismissible @dismiss="successMessage=''"/>

        <MediaRequestForm
          v-if="kind === 'discover'"
          :detail="detail"
          :form="requestForm"
          :requesters="requesters"
          :folders="folders"
          :busy="busy"
          :admin="admin"
          :current-user-id="sessionUserId"
          @submit="submitRequest"
          @join="joinRequest"
          @retry="requestAction(detail.request_id, 'retry')"
          @approve="requestAction(detail.request_id, 'approve')"
        />

        <template v-if="kind !== 'discover'">
          <nav class="detail-tabs" style="overflow-x: auto; display: flex; gap: 0.5rem; white-space: nowrap; padding-bottom: 0.5rem;">
            <button v-for="entry in tabs" :key="entry" :class="{active:tab===entry}" @click="tab=entry">{{ tabLabel(entry) }}</button>
          </nav>

          <MediaRequestsTab
            v-if="tab === 'requests'"
            :requests="detail.requests"
            :detail="detail"
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
            @withdraw-request="withdrawRequest"
            @notify-user="notifyUser"
            @promote-requester="promoteRequester"
            @remove-requester="removeRequester"
            @approve="id => requestAction(id, 'approve')"
            @reject="rejectRequest"
          />

          <MediaCalendarTab v-else-if="tab === 'calendar'" :events="detail.calendar" />

          <MediaAudioSection
            v-else-if="tab === 'audio'"
            :vf-detail="mergedVfDetail"
            :busy="busy"
            :available="Boolean(detail?.in_library)"
            :envelope-error="envelopeError"
            :availability-error="availabilityError"
            :vf-status-error="vfStatusError"
            @scan="scanVff"
            @correction="openCorrection"
            @expand-season="seasons.loadSeason"
          />

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
            @expand-season="seasons.loadSeason"
          />
        </template>

        <MediaCast :items="detail.cast || []" />

        <MediaSaga v-if="detail.saga" :saga="detail.saga" />

        <MediaRecommendations
          title="Recommandés pour vous"
          :items="detail.recommendations || []"
          @open="item => router.push(relatedMediaPath(item))"
        />
        <MediaRecommendations
          title="Titres similaires"
          :items="detail.similar || []"
          @open="item => router.push(relatedMediaPath(item))"
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
import MediaAudioSection from "@/components/media/MediaAudioSection.vue";
import MediaRequestForm from "@/components/media/MediaRequestForm.vue";
import MediaRecommendations from "@/components/media/MediaRecommendations.vue";
import MediaCast from "@/components/media/MediaCast.vue";
import MediaSaga from "@/components/media/MediaSaga.vue";
import ConfirmModal from "@/components/ConfirmModal.vue";
import { useConfirm } from "@/composables/useConfirm";
import { canModerateSession, loadSession } from "@/composables/useSession";
import { useSeasonEpisodes } from "@/composables/useSeasonEpisodes";
import { useRequestActions } from "@/composables/useRequestActions";

const route = useRoute();
const router = useRouter();

const detail = ref(null), requesters = ref([]), folders = ref([]);
const loading = ref(false), busy = ref(false), error = ref(''), successMessage = ref(''), tab = ref('summary');
const requestForm = reactive({ plex_user_id: '', root_folder: '', seasons: [] });
const tabs = computed(() => detail.value?.media_type === 'show'
  ? ['summary', 'audio', 'requests', 'calendar']
  : ['summary', 'requests', 'calendar']);
const admin = ref(false);
const sessionUserId = ref('');
let loadGeneration = 0;
let usersPromise;
const { dialog: confirmDialog, askConfirm, resolveConfirm } = useConfirm();

const showIssueForm = ref(false), showCorrectionForm = ref(false);
const users = ref([]), correctionOptions = ref([]);
const correctionForm = reactive({ scope: 'media', season_number: null, episode_number: null, recipient_user_ids: [], corrections: [], note: '' });
const newRequesterId = ref('');

const kind = computed(() => route.params.kind);
const inDiscoverShell = computed(() => route.path.startsWith('/discover/'));

const statusLabel = computed(() => detail.value?.operational_status_label || (detail.value?.available || detail.value?.in_library ? 'Disponible' : detail.value?.requested ? 'Deja demande' : detail.value?.request_status || ''));
const statusClass = computed(() => detail.value?.available || detail.value?.in_library ? 'available' : 'pending');
const seasonNumbers = computed(() => Array.from({ length: Number(detail.value?.number_of_seasons || 0) + 1 }, (_, i) => i));
const addableUsers = computed(() => {
  const already = new Set((detail.value?.requests || []).flatMap(row => row.requester_ids || [row.plex_user_id]));
  return users.value.filter(u => !already.has(u.plex_user_id));
});

// vf_source_id peut pointer vers un LibraryItem meme si la page a ete ouverte via une
// MediaRequest (des qu'un media est aussi present dans la bibliotheque Plex) -- le
// backend renvoie toujours vf_source_type/vf_source_id ensemble (une seule source de
// verite, jamais de repli sur kind.value/route.params.id qui pourraient diverger).
const seasons = useSeasonEpisodes(() => {
  const media = detail.value?.media;
  if (!media?.vf_source_id) return null;
  return {
    source: media.vf_source_type === 'library' ? 'library' : 'requests',
    id: media.vf_source_id,
    mediaType: detail.value?.media_type,
  };
});
const mergedVfDetail = seasons.detail;
const { envelopeError, availabilityError, vfStatusError } = seasons;

function tabLabel(value) { return ({ summary: 'Resume', audio: 'Saisons & épisodes', requests: 'Demandes', calendar: 'Calendrier' })[value]; }

function mediaPath(core = false) {
  const id = route.params.id;
  if (kind.value === 'discover') {
    const p = new URLSearchParams();
    p.set('media_type', route.query.media_type || '');
    if (route.query.id_type === 'tvdb') p.set('tvdb_id', id); else p.set('tmdb_id', id);
    return `/api/discover/detail?${p}`;
  }
  if (kind.value === 'request') return `/api/media/detail?request_id=${id}${core ? '&core=true' : ''}`;
  return `/api/media/detail?library_id=${id}${core ? '&core=true' : ''}`;
}

async function loadUsers() {
  if (usersPromise) return usersPromise;
  usersPromise = (async () => {
    try {
      const [userRows, options] = await Promise.all([
        api('/api/users'),
        api('/api/media/corrections/options'),
      ]);
      users.value = userRows;
      correctionOptions.value = options;
    } catch (e) {}
  })();
  return usersPromise;
}

async function loadAdminFlag() {
  admin.value = canModerateSession(await loadSession());
}

async function load() {
  const generation = ++loadGeneration;
  loading.value = true; error.value = '';
  seasons.reset();
  usersPromise = undefined;
  users.value = [];
  correctionOptions.value = [];
  tab.value = 'summary';
  try {
    // La fiche locale commence par une enveloppe DB minimale. Les jointures de
    // demandes, l'historique, TMDB et le calendrier *arr arrivent ensuite sans
    // retenir le hero derriere l'appel le plus lent.
    const payload = await api(mediaPath(kind.value !== 'discover'));
    if (generation !== loadGeneration) return;
    detail.value = kind.value === 'discover' ? payload : { ...payload.media, ...payload };
    if (kind.value === 'discover') {
      const session = await loadSession();
      admin.value = canModerateSession(session);
      sessionUserId.value = session?.plex_user_id || '';
      if (admin.value) {
        const service = detail.value.media_type === 'show' ? 'sonarr' : 'radarr';
        [requesters.value, folders.value] = await Promise.all([
          api('/api/discover/requesters'),
          api(`/api/${service}/folders`).catch(() => []),
        ]);
      } else {
        requesters.value = [];
        folders.value = [];
      }
      requestForm.plex_user_id = requesters.value.find(user => user.plex_user_id === sessionUserId.value)?.plex_user_id
        || sessionUserId.value || requesters.value[0]?.plex_user_id || '';
      requestForm.seasons = seasonNumbers.value.filter(season => season !== 0);
    }
  } catch (e) {
    if (generation === loadGeneration) error.value = e.message;
  } finally {
    if (generation === loadGeneration) loading.value = false;
  }

  if (kind.value !== 'discover') {
    api(mediaPath()).then(payload => {
      if (generation !== loadGeneration) return;
      detail.value = {
        ...detail.value,
        ...(payload.media || {}),
        ...payload,
        media: payload.media || detail.value?.media,
      };
    }).catch(e => {
      if (generation === loadGeneration) error.value = e.message;
    });
    // Chaque appel se resout independamment -- l'enveloppe (rapide, TMDB) affiche
    // l'accordeon des qu'elle arrive, sans attendre disponibilite/VF (Sonarr/BDD),
    // qui completent ensuite les badges au fil de l'eau (voir mergedVfDetail).
    if (detail.value?.media_type === 'show') {
      Promise.all([seasons.loadAll(), loadAdminFlag()]).catch(() => {});
    } else {
      seasons.loadMovieVf().catch(() => { envelopeError.value = true; });
      loadAdminFlag().catch(() => {});
    }
  }
}

const {
  requestAction, rejectRequest, closeRequest, resendMail, notifyUser,
  addRequester, catchUpAll, promoteRequester, removeRequester, deleteRequest, withdrawRequest,
} = useRequestActions({
  detail, newRequesterId, askConfirm, busy, error,
  reload: load,
  onDeleted: () => router.push('/library'),
});

function goBack() {
  if (window.history.state?.back) router.back();
  else router.push(inDiscoverShell.value ? '/discover' : '/library');
}

function relatedMediaPath(item) {
  return mediaDetailPath(item, 'discover', { discover: inDiscoverShell.value });
}

async function openCorrection(scope, season, episode) {
  await loadUsers().catch(() => {});
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
    detail.value.just_requested = true;
    detail.value.request_id = data.request_id || detail.value.request_id || null;
    detail.value.request_status = data.pending_approval ? 'pending_approval' : 'sent_to_arr';
    detail.value.operational_status = data.pending_approval ? 'not_submitted' : 'submitted';
    detail.value.operational_status_label = data.pending_approval ? "En attente d'approbation" : 'Transmis à Sonarr / Radarr';
    detail.value.waiting_reason = data.pending_approval
      ? "Un administrateur doit encore approuver la demande."
      : 'Le média est suivi et la recherche automatique est lancée.';
  } catch (e) { error.value = e.message; } finally { busy.value = false; }
}

async function joinRequest() {
  if (!detail.value?.request_id || !sessionUserId.value) return;
  busy.value = true; error.value = '';
  try {
    const data = await api(`/api/requests/${detail.value.request_id}/join`, { method: 'POST' });
    detail.value.requester_ids = data.requester_ids;
    successMessage.value = data.already_joined ? 'Cette demande est déjà dans votre suivi.' : 'Demande ajoutée à votre suivi.';
  } catch (e) { error.value = e.message; } finally { busy.value = false; }
}

async function scanVff() {
  busy.value = true;
  try { await seasons.rescan(); }
  catch (e) { error.value = e.message; } finally { busy.value = false; }
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
    successMessage.value = 'Correction envoyée !';
  } catch (e) { error.value = e.message; } finally { busy.value = false; }
}

watch(tab, value => { if (value === 'requests') loadUsers().catch(() => {}); });
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
  gap: var(--space-4);
}
.drawer-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: 80px 0;
  color: var(--muted);
}
@media (max-width: 720px) {
  .media-detail-body { padding-bottom: calc(var(--mobile-nav-h) + var(--safe-bottom) + 76px); }
}
@media (min-width: 1025px) {
  .media-detail-body { font-size: var(--fs-md); gap: var(--space-5); }
  .media-detail-body :deep(.drawer-section > h2),
  .media-detail-body :deep(.drawer-section > h3) { font-size: var(--fs-lg); }
  .media-detail-body :deep(.detail-row > div:first-child > strong) { font-size: var(--fs-md); }
  .media-detail-body :deep(.detail-row > div:first-child > span),
  .media-detail-body :deep(.detail-row > div:first-child > small) { font-size: var(--fs-sm); line-height: 1.45; }
  .media-detail-body :deep(.detail-tabs button) { font-size: var(--fs-md); }
  .media-detail-body :deep(.badge) { font-size: var(--fs-sm); }
}
</style>
