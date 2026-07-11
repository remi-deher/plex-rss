const LIBRARY_CONFIG = window.PLEXARR_LIBRARY || {};
const VFF_ENABLED = !!LIBRARY_CONFIG.vffEnabled;
const ACTIVE_VIEW = LIBRARY_CONFIG.activeView || 'all';
const LIBRARY_FILTERS = LIBRARY_CONFIG.filters || {};
// Profil portail : un utilisateur non-admin consulte la bibliothèque en lecture seule
// (aucune action *arr / VFF / suppression) et ne peut qu'annuler ses propres demandes.
const IS_ADMIN = !!LIBRARY_CONFIG.isAdmin;
const CURRENT_UID = LIBRARY_CONFIG.currentUid || null;
function _isOwnRequest(r) {
  return !!(CURRENT_UID && _reqIds(r).includes(CURRENT_UID));
}
const mediaModal = new bootstrap.Modal(document.getElementById('mediaModal'));
let currentMediaDetail = null;
let episodeFilter = 'all';

function escHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;');
}
function fmtDate(iso) {
  if (!iso) return '-';
  const d = new Date(String(iso).includes('T') ? iso : iso + 'T00:00:00');
  return isNaN(d) ? '-' : d.toLocaleDateString('fr-FR', { day:'2-digit', month:'2-digit', year:'numeric' });
}
function fmtDateTime(iso) {
  if (!iso) return '-';
  const s = String(iso).endsWith('Z') || String(iso).includes('+') ? iso : iso + 'Z';
  const d = new Date(s);
  return isNaN(d) ? '-' : d.toLocaleString('fr-FR');
}
function formatBytes(bytes, decimals = 1) {
  if (!bytes) return '-';
  const k = 1024, sizes = ['B','Ko','Mo','Go','To'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(decimals)) + ' ' + sizes[i];
}
function typeLabel(mt) { return mt === 'show' ? 'Serie' : 'Film'; }
function sourcePath(kind) { return kind === 'library' ? 'library' : 'requests'; }

const PREF_KEY = 'library_view_mode';
let currentViewMode = localStorage.getItem(PREF_KEY) || 'grid';
function setViewMode(v) {
  currentViewMode = v;
  localStorage.setItem(PREF_KEY, v);
  document.getElementById('view-grid')?.style.setProperty('display', v === 'grid' ? '' : 'none', v === 'grid' ? '' : 'important');
  const list = document.getElementById('view-list');
  if (list) list.style.display = v === 'list' ? '' : 'none';
  document.getElementById('btn-grid')?.classList.toggle('active', v === 'grid');
  document.getElementById('btn-list')?.classList.toggle('active', v === 'list');
}
if (ACTIVE_VIEW !== 'calendar') document.addEventListener('DOMContentLoaded', () => setViewMode(currentViewMode));

// Ouverture directe de la fiche depuis un lien externe (ex: Découvrir), via
// /library?open_library=<id> ou /library?open_request=<id>.
(function _openFromQuery() {
  const params = new URLSearchParams(window.location.search);
  const libId = params.get('open_library');
  const reqId = params.get('open_request');
  if (libId != null) openMediaDetail(parseInt(libId), null);
  else if (reqId != null) openMediaDetail(null, parseInt(reqId));
})();

function statusBadge(status) {
  const map = {
    available: '<span class="badge badge-available"><i class="bi bi-check-circle-fill me-1"></i>Disponible</span>',
    sent_to_arr: '<span class="badge badge-sent"><i class="bi bi-send-fill me-1"></i>Demande en cours</span>',
    failed: '<span class="badge badge-failed"><i class="bi bi-x-circle-fill me-1"></i>Echec</span>',
    pending: '<span class="badge badge-pending"><i class="bi bi-hourglass-split me-1"></i>Demande en cours</span>',
  };
  return map[status] || `<span class="badge bg-secondary">${escHtml(status || 'Aucune demande')}</span>`;
}
function vfBadge(hasVf, inLibrary = true, vfGranularity = null) {
  if (!inLibrary) return '<span class="badge bg-secondary"><i class="bi bi-inbox me-1"></i>Hors Plex</span>';
  if (hasVf === true) return '<span class="badge badge-available"><i class="bi bi-translate me-1"></i>VF</span>';
  if (hasVf === false) {
    if (vfGranularity === 'season_partial') return '<span class="badge bg-warning text-dark" style="white-space:normal;text-align:left;line-height:1.3" title="Au moins une saison entière est en VF, mais la série n\'est pas totalement en VF"><i class="bi bi-translate me-1"></i>VF partielle · saisons</span>';
    if (vfGranularity === 'episode_partial') return '<span class="badge bg-info text-dark" style="white-space:normal;text-align:left;line-height:1.3" title="Seulement quelques épisodes sont en VF (aucune saison complète)"><i class="bi bi-translate me-1"></i>VF partielle · épisodes</span>';
    return '<span class="badge badge-sent"><i class="bi bi-translate me-1"></i>VF en attente</span>';
  }
  return '<span class="badge badge-pending"><i class="bi bi-translate me-1"></i>Non analyse</span>';
}

async function openMediaDetail(libraryId, requestId) {
  document.getElementById('mediaModalTitle').textContent = 'Chargement...';
  document.getElementById('mediaModalBody').innerHTML = '<div class="text-center py-4"><span class="spinner-border text-warning"></span></div>';
  mediaModal.show();
  const params = new URLSearchParams();
  if (libraryId != null) params.set('library_id', libraryId);
  else if (requestId != null) params.set('request_id', requestId);
  try {
    currentMediaDetail = await fetch(`/api/media/detail?${params.toString()}`).then(r => {
      if (!r.ok) throw new Error('Detail introuvable');
      return r.json();
    });
    renderMediaModal(currentMediaDetail);
  } catch (e) {
    document.getElementById('mediaModalBody').innerHTML = `<div class="alert alert-danger">${escHtml(e.message)}</div>`;
  }
}

function renderMediaModal(d) {
  const m = d.media;
  document.getElementById('mediaModalTitle').textContent = `${m.title}${m.year ? ' (' + m.year + ')' : ''}`;
  document.getElementById('mediaModalBody').innerHTML = `
    <ul class="nav nav-tabs mb-3" role="tablist">
      <li class="nav-item"><button class="nav-link active" data-bs-toggle="tab" data-bs-target="#tab-summary" type="button"><i class="bi bi-info-circle me-1"></i>Resume</button></li>
      <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#tab-requests" type="button"><i class="bi bi-inbox me-1"></i>Demandes <span class="badge bg-secondary ms-1">${d.requests.length}</span></button></li>
      <li class="nav-item"><button class="nav-link" id="tab-vf-btn" data-bs-toggle="tab" data-bs-target="#tab-vf" type="button"><i class="bi bi-translate me-1"></i>${m.media_type === 'show' ? 'Episodes' : 'Pistes audio'}</button></li>
      <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#tab-calendar" type="button"><i class="bi bi-calendar3 me-1"></i>Calendrier</button></li>
      ${IS_ADMIN ? '<li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#tab-search" type="button"><i class="bi bi-search me-1"></i>Recherche</button></li>' : ''}
    </ul>
    <div class="tab-content">
      <div class="tab-pane fade show active" id="tab-summary">${renderSummary(d)}</div>
      <div class="tab-pane fade" id="tab-requests">${renderRequestsTab(d.requests)}</div>
      <div class="tab-pane fade" id="tab-vf"><div id="vf-tab-body">${VFF_ENABLED || m.media_type === 'show' ? '<div class="text-center py-4"><span class="spinner-border spinner-border-sm text-warning"></span></div>' : '<div class="text-muted small">Suivi VFF desactive.</div>'}</div></div>
      <div class="tab-pane fade" id="tab-calendar">${renderCalendarTab(d)}</div>
      ${IS_ADMIN ? '<div class="tab-pane fade" id="tab-search"><div id="search-tab-body"><div class="text-center py-3"><span class="spinner-border spinner-border-sm text-warning"></span></div></div></div>' : ''}
    </div>`;
  loadVfDetail(d.media);
  if (IS_ADMIN) loadSearchTab(m);
}

async function recheckPlex(btn, requestId, libraryId) {
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Vérification...';
  try {
    const params = new URLSearchParams();
    if (libraryId != null) params.set('library_id', libraryId);
    else if (requestId != null) params.set('request_id', requestId);
    const r = await fetch(`/api/media/recheck-plex?${params.toString()}`, { method: 'POST' });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || 'Erreur');
    if (d.found) {
      showToast('Média trouvé dans Plex — bibliothèque mise à jour', 'success');
      setTimeout(() => location.reload(), 1200);
    } else {
      showToast('Toujours introuvable dans Plex', 'warning');
      btn.disabled = false;
      btn.innerHTML = orig;
    }
  } catch (e) {
    showToast('Erreur : ' + e.message, 'danger');
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

function renderSummary(d) {
  const m = d.media, t = d.timeline || {};
  const poster = m.poster_url
    ? `<img src="${escHtml(m.poster_url)}" class="img-fluid rounded" style="width:120px;object-fit:cover">`
    : `<div class="rounded bg-secondary d-flex align-items-center justify-content-center" style="width:120px;height:180px"><i class="bi bi-image fs-2 text-muted"></i></div>`;
  const requestStatus = d.requests.length ? d.requests.map(r => statusBadge(r.status)).join(' ') : '<span class="badge bg-secondary">Aucune demande</span>';
  const requesterNames = [...new Set(d.requests.flatMap(r => r.requesters || []))].join(', ') || '-';
  const openIssueCount = (d.issues || []).filter(i => i.status !== 'closed').length;
  // En cours de téléchargement : au moins une demande a un item actif dans la file *arr.
  const isDownloading = !m.in_library && d.requests.some(r => r.is_downloading);
  // Anomalie Plex : traité/disponible côté *arr mais introuvable dans la bibliothèque Plex
  // (et pas simplement en cours de téléchargement/import).
  const isAnomaly = !isDownloading && !m.in_library && d.requests.some(r => r.status === 'available');
  const scheduleRows = m.media_type === 'show'
    ? `
      <tr><td class="text-muted">Premiere diffusion</td><td>${fmtDate(t.first_aired)}</td></tr>
      <tr><td class="text-muted">Prochaine diffusion</td><td>${fmtDateTime(t.next_episode_at)}</td></tr>
      <tr><td class="text-muted">Fin de diffusion</td><td>${t.ended_at ? fmtDate(t.ended_at) : (t.series_status === 'ended' ? fmtDate(t.last_aired_at) : 'En cours')}</td></tr>`
    : `
      <tr><td class="text-muted">Sortie cinema</td><td>${fmtDate(t.in_cinemas)}</td></tr>
      <tr><td class="text-muted">Sortie digitale</td><td>${fmtDate(t.digital_release)}</td></tr>
      <tr><td class="text-muted">Sortie physique</td><td>${fmtDate(t.physical_release)}</td></tr>`;
  return `<div class="row g-3">
    <div class="col-auto">${poster}</div>
    <div class="col">
      <div class="mb-2">
        <span class="badge ${m.media_type === 'show' ? 'bg-info text-dark' : 'bg-primary'}">${typeLabel(m.media_type)}</span>
        ${m.in_library ? '<span class="badge bg-success ms-1">Plex</span>' : (isDownloading ? '<span class="badge bg-info text-dark ms-1"><i class="bi bi-cloud-arrow-down-fill me-1"></i>En cours de téléchargement</span>' : (isAnomaly ? '<span class="badge bg-danger ms-1"><i class="bi bi-exclamation-triangle-fill me-1"></i>Anomalie Plex</span>' : '<span class="badge bg-secondary ms-1">Demande hors Plex</span>'))}
        <span class="ms-1">${vfBadge(m.has_vf, m.in_library, m.vf_granularity)}</span>
      </div>
      ${IS_ADMIN && !m.in_library ? `<div class="mb-2">
        <button class="btn btn-sm btn-outline-danger d-inline-flex align-items-center gap-1"
                onclick="recheckPlex(this, ${m.request_id == null ? 'null' : m.request_id}, ${m.library_id == null ? 'null' : m.library_id})">
          <i class="bi bi-arrow-repeat"></i> Revérifier dans Plex
        </button>
        <div class="text-muted small mt-1">${isAnomaly
          ? 'Traité par Sonarr/Radarr mais introuvable dans Plex. Relance une recherche ciblée dans les bibliothèques Plex configurées.'
          : "Vérifie si le média est désormais présent dans les bibliothèques Plex configurées."}</div>
      </div>` : ''}
      <div class="mb-2 d-flex flex-wrap align-items-center gap-2">
        <button class="btn btn-sm btn-outline-warning d-inline-flex align-items-center gap-1"
                onclick="reportMediaIssue(${m.request_id == null ? 'null' : m.request_id}, ${m.library_id == null ? 'null' : m.library_id})">
          <i class="bi bi-flag"></i> Signaler un probleme
        </button>
        ${IS_ADMIN ? `<button class="btn btn-sm btn-outline-success d-inline-flex align-items-center gap-1"
                onclick="openCorrectionModal(${m.request_id == null ? 'null' : m.request_id}, ${m.library_id == null ? 'null' : m.library_id})">
          <i class="bi bi-envelope-check"></i> Signaler une correction
        </button>` : ''}
        ${openIssueCount ? `<span class="badge bg-warning text-dark">${openIssueCount} signalement${openIssueCount > 1 ? 's' : ''} ouvert${openIssueCount > 1 ? 's' : ''}</span>` : ''}
      </div>
      <table class="table table-sm table-dark table-borderless mb-0" style="font-size:13px">
        <tr><td class="text-muted" style="width:150px">Demandes</td><td>${requestStatus}</td></tr>
        <tr><td class="text-muted">Demandeurs</td><td>${escHtml(requesterNames)}</td></tr>
        ${scheduleRows}
        <tr><td class="text-muted">TMDB / TVDB / IMDB</td><td>${[m.tmdb_id && 'TMDB '+m.tmdb_id, m.tvdb_id && 'TVDB '+m.tvdb_id, m.imdb_id && 'IMDB '+m.imdb_id].filter(Boolean).map(escHtml).join(' · ') || '-'}</td></tr>
      </table>
    </div>
    ${m.overview ? `<div class="col-12"><p class="text-muted small mb-0" style="line-height:1.6">${escHtml(m.overview)}</p></div>` : ''}
  </div>`;
}

async function reportMediaIssue(requestId, libraryId) {
  const issueType = prompt('Type de probleme (audio, sous-titres, mauvais media, qualite, autre)', 'audio');
  if (!issueType) return;
  const message = prompt('Detail du probleme constate', '');
  try {
    const r = await fetch('/api/media/issues', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        request_id: requestId,
        library_id: libraryId,
        issue_type: issueType,
        message: message || null,
      }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || 'Erreur');
    showToast('Signalement enregistre', 'success');
    const m = currentMediaDetail && currentMediaDetail.media;
    if (m) openMediaDetail(m.library_id, m.request_id);
  } catch (e) {
    showToast('Erreur : ' + e.message, 'danger');
  }
}

const CORRECTION_OPTIONS = [
  'Son corrigé',
  'Synchronisation audio corrigée',
  'Sous-titres corrigés',
  'Synchronisation des sous-titres corrigée',
  'Langue audio corrigée',
  'Qualité vidéo améliorée',
  'Mauvaise version remplacée',
  'Épisode corrigé',
  'Métadonnées corrigées',
  'Affiche / jaquette corrigée',
];
let correctionModal = null;
let correctionPreviewTimer = null;
let correctionContext = { requestId: null, libraryId: null };

function ensureCorrectionModal() {
  let el = document.getElementById('correctionModal');
  if (!el) {
    document.body.insertAdjacentHTML('beforeend', `
      <div class="modal fade" id="correctionModal" tabindex="-1">
        <div class="modal-dialog modal-xl modal-dialog-scrollable">
          <div class="modal-content bg-dark border-secondary text-white">
            <div class="modal-header border-secondary">
              <h5 class="modal-title">Signaler une correction</h5>
              <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
              <div class="row g-3">
                <div class="col-lg-4">
                  <label class="form-label text-muted small">Destinataires</label>
                  <div id="correction-recipients" class="border rounded p-2" style="border-color:var(--pr-border)!important;max-height:180px;overflow:auto"></div>

                  <div id="correction-target-wrap" class="mt-3">
                    <label class="form-label text-muted small">Cible de la correction</label>
                    <select id="correction-scope" class="form-select form-select-sm bg-dark text-white border-secondary mb-2">
                      <option value="media">Média entier</option>
                      <option value="season">Une saison</option>
                      <option value="episode">Un épisode</option>
                    </select>
                    <div class="row g-2">
                      <div class="col-6">
                        <select id="correction-season" class="form-select form-select-sm bg-dark text-white border-secondary"></select>
                      </div>
                      <div class="col-6">
                        <select id="correction-episode" class="form-select form-select-sm bg-dark text-white border-secondary"></select>
                      </div>
                    </div>
                  </div>

                  <label class="form-label text-muted small mt-3">Corrections appliquées</label>
                  <div id="correction-options" class="border rounded p-2" style="border-color:var(--pr-border)!important;max-height:260px;overflow:auto"></div>

                  <label class="form-label text-muted small mt-3" for="correction-note">Note complémentaire</label>
                  <textarea class="form-control bg-dark text-white border-secondary" id="correction-note" rows="3" maxlength="2000" placeholder="Optionnel"></textarea>
                </div>
                <div class="col-lg-8">
                  <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">
                    <label class="form-label text-muted small mb-0">Aperçu du mail</label>
                    <div class="d-flex align-items-center gap-2">
                      <select id="correction-preview-user" class="form-select form-select-sm bg-dark text-white border-secondary" style="width:auto"></select>
                      <span id="correction-preview-status" class="badge bg-secondary">En attente</span>
                    </div>
                  </div>
                  <iframe id="correction-preview-frame" style="width:100%;height:560px;border:1px solid var(--pr-border);border-radius:8px;background:#111"></iframe>
                </div>
              </div>
            </div>
            <div class="modal-footer border-secondary">
              <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Annuler</button>
              <button type="button" class="btn btn-success" id="correction-send-btn" onclick="sendCorrectionEmail()">
                <i class="bi bi-send"></i> Envoyer la correction
              </button>
            </div>
          </div>
        </div>
      </div>`);
    el = document.getElementById('correctionModal');
    document.getElementById('correction-note')?.addEventListener('input', scheduleCorrectionPreview);
    document.getElementById('correction-preview-user')?.addEventListener('change', scheduleCorrectionPreview);
    document.getElementById('correction-scope')?.addEventListener('change', () => {
      updateCorrectionTargetControls();
      scheduleCorrectionPreview();
    });
    document.getElementById('correction-season')?.addEventListener('change', () => {
      populateCorrectionEpisodes();
      scheduleCorrectionPreview();
    });
    document.getElementById('correction-episode')?.addEventListener('change', scheduleCorrectionPreview);
  }
  correctionModal = correctionModal || new bootstrap.Modal(el);
  return el;
}

function correctionUserLabel(u) {
  return u.custom_name || u.display_name || u.plex_user_id || ('Utilisateur #' + u.id);
}

function correctionUserEmail(u) {
  return u.notification_email || u.plex_email || '';
}

function selectedCorrectionRecipientIds() {
  return Array.from(document.querySelectorAll('.correction-recipient:checked')).map(el => parseInt(el.value)).filter(Boolean);
}

function selectedCorrectionLabels() {
  return Array.from(document.querySelectorAll('.correction-option:checked')).map(el => el.value);
}

function getCorrectionEpisodeMap() {
  const map = new Map();
  const events = (currentMediaDetail && currentMediaDetail.calendar) || [];
  events.forEach(e => {
    const match = String(e.subtitle || '').match(/S(\d+)E(\d+)/i);
    if (!match) return;
    const season = Number(match[1]);
    const episode = Number(match[2]);
    if (!map.has(season)) map.set(season, new Set());
    map.get(season).add(episode);
  });
  const vfSeasons = (currentMediaDetail && currentMediaDetail.vf_seasons) || [];
  vfSeasons.forEach(s => {
    const season = Number(s.season_number);
    if (!season) return;
    if (!map.has(season)) map.set(season, new Set());
    (s.episodes || []).forEach(ep => {
      const episode = Number(ep.episode);
      if (episode) map.get(season).add(episode);
    });
  });
  return map;
}

function correctionAvailableSeasons() {
  const map = getCorrectionEpisodeMap();
  const seasons = Array.from(map.keys()).sort((a, b) => a - b);
  const presetSeason = correctionContext.seasonNumber;
  if (presetSeason && !seasons.includes(presetSeason)) seasons.push(presetSeason);
  return seasons.sort((a, b) => a - b);
}

function populateCorrectionSeasons() {
  const select = document.getElementById('correction-season');
  if (!select) return;
  const seasons = correctionAvailableSeasons();
  select.innerHTML = seasons.map(s => `<option value="${s}">Saison ${s}</option>`).join('');
  if (correctionContext.seasonNumber) select.value = String(correctionContext.seasonNumber);
  populateCorrectionEpisodes();
}

function populateCorrectionEpisodes() {
  const episodeSelect = document.getElementById('correction-episode');
  const seasonSelect = document.getElementById('correction-season');
  if (!episodeSelect || !seasonSelect) return;
  const season = Number(seasonSelect.value || correctionContext.seasonNumber || 0);
  const map = getCorrectionEpisodeMap();
  const episodes = Array.from(map.get(season) || []).sort((a, b) => a - b);
  if (correctionContext.seasonNumber === season && correctionContext.episodeNumber && !episodes.includes(correctionContext.episodeNumber)) {
    episodes.push(correctionContext.episodeNumber);
    episodes.sort((a, b) => a - b);
  }
  episodeSelect.innerHTML = episodes.map(e => `<option value="${e}">Épisode ${e}</option>`).join('');
  if (correctionContext.episodeNumber) episodeSelect.value = String(correctionContext.episodeNumber);
}

function updateCorrectionTargetControls() {
  const media = currentMediaDetail && currentMediaDetail.media;
  const wrap = document.getElementById('correction-target-wrap');
  const scope = document.getElementById('correction-scope');
  const season = document.getElementById('correction-season');
  const episode = document.getElementById('correction-episode');
  if (!wrap || !scope || !season || !episode) return;
  const isShow = media && media.media_type === 'show';
  wrap.style.display = isShow ? '' : 'none';
  if (!isShow) {
    scope.value = 'media';
    return;
  }
  season.style.display = scope.value === 'season' || scope.value === 'episode' ? '' : 'none';
  episode.style.display = scope.value === 'episode' ? '' : 'none';
}

function syncCorrectionPreviewUsers() {
  const select = document.getElementById('correction-preview-user');
  if (!select) return;
  const ids = selectedCorrectionRecipientIds();
  const current = select.value;
  const users = (_addUsers || []).filter(u => ids.includes(u.id));
  select.innerHTML = users.map(u => `<option value="${u.id}">${escHtml(correctionUserLabel(u))}</option>`).join('');
  if (users.some(u => String(u.id) === current)) select.value = current;
}

function renderCorrectionChoices() {
  const users = (_addUsers || []).filter(u => u.enabled && correctionUserEmail(u));
  const recipientBox = document.getElementById('correction-recipients');
  recipientBox.innerHTML = users.length ? users.map(u => `
    <div class="form-check">
      <input class="form-check-input correction-recipient" type="checkbox" value="${u.id}" id="correction-recipient-${u.id}">
      <label class="form-check-label small" for="correction-recipient-${u.id}">
        ${escHtml(correctionUserLabel(u))} <span class="text-muted">${escHtml(correctionUserEmail(u))}</span>
      </label>
    </div>`).join('') : '<div class="text-muted small">Aucun utilisateur avec email configuré.</div>';
  recipientBox.querySelectorAll('input').forEach(el => el.addEventListener('change', () => {
    syncCorrectionPreviewUsers();
    scheduleCorrectionPreview();
  }));

  const optionsBox = document.getElementById('correction-options');
  optionsBox.innerHTML = CORRECTION_OPTIONS.map((label, i) => `
    <div class="form-check">
      <input class="form-check-input correction-option" type="checkbox" value="${escHtml(label)}" id="correction-option-${i}">
      <label class="form-check-label small" for="correction-option-${i}">${escHtml(label)}</label>
    </div>`).join('');
  optionsBox.querySelectorAll('input').forEach(el => el.addEventListener('change', scheduleCorrectionPreview));
}

async function openCorrectionModal(requestId, libraryId, target = {}) {
  if (!IS_ADMIN) return;
  ensureCorrectionModal();
  if (window._addUsersPromise) await window._addUsersPromise;
  correctionContext = {
    requestId,
    libraryId,
    scope: target.scope || 'media',
    seasonNumber: target.season || null,
    episodeNumber: target.episode || null,
  };
  renderCorrectionChoices();
  document.getElementById('correction-note').value = '';
  const scopeSelect = document.getElementById('correction-scope');
  if (scopeSelect) scopeSelect.value = correctionContext.scope;
  populateCorrectionSeasons();
  updateCorrectionTargetControls();
  const firstRecipient = document.querySelector('.correction-recipient');
  if (firstRecipient) firstRecipient.checked = true;
  const firstOption = document.querySelector('.correction-option');
  if (firstOption) firstOption.checked = true;
  syncCorrectionPreviewUsers();
  correctionModal.show();
  scheduleCorrectionPreview(50);
}

function buildCorrectionPayload() {
  return {
    request_id: correctionContext.requestId,
    library_id: correctionContext.libraryId,
    recipient_user_ids: selectedCorrectionRecipientIds(),
    preview_user_id: parseInt(document.getElementById('correction-preview-user')?.value || '0') || null,
    corrections: selectedCorrectionLabels(),
    note: document.getElementById('correction-note')?.value || '',
    scope: document.getElementById('correction-scope')?.value || 'media',
    season_number: parseInt(document.getElementById('correction-season')?.value || '0') || null,
    episode_number: parseInt(document.getElementById('correction-episode')?.value || '0') || null,
  };
}

function scheduleCorrectionPreview(delay = 500) {
  clearTimeout(correctionPreviewTimer);
  correctionPreviewTimer = setTimeout(loadCorrectionPreview, delay);
}

async function loadCorrectionPreview() {
  const status = document.getElementById('correction-preview-status');
  const frame = document.getElementById('correction-preview-frame');
  const payload = buildCorrectionPayload();
  if (!payload.recipient_user_ids.length || !payload.corrections.length) {
    if (status) { status.className = 'badge bg-secondary'; status.textContent = 'En attente'; }
    if (frame) frame.srcdoc = '<div style="padding:24px;color:#aaa;font-family:sans-serif">Choisissez un destinataire et au moins une correction.</div>';
    return;
  }
  if (status) { status.className = 'badge bg-warning text-dark'; status.textContent = 'Actualisation...'; }
  try {
    const r = await fetch('/api/media/correction-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'Erreur aperçu');
    if (frame) frame.srcdoc = await r.text();
    if (status) { status.className = 'badge bg-success'; status.textContent = 'À jour'; }
  } catch (e) {
    if (status) { status.className = 'badge bg-danger'; status.textContent = 'Erreur'; }
    if (frame) frame.srcdoc = `<div style="padding:24px;color:#ff6b6b;font-family:sans-serif">${escHtml(e.message)}</div>`;
  }
}

async function sendCorrectionEmail() {
  const payload = buildCorrectionPayload();
  if (!payload.recipient_user_ids.length) { showToast('Sélectionnez au moins un destinataire', 'warning'); return; }
  if (!payload.corrections.length) { showToast('Sélectionnez au moins une correction', 'warning'); return; }
  const btn = document.getElementById('correction-send-btn');
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Envoi...';
  try {
    const r = await fetch('/api/media/send-correction', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : (d.detail?.message || 'Erreur envoi'));
    const skipped = d.skipped?.length ? ` (${d.skipped.length} ignoré${d.skipped.length > 1 ? 's' : ''})` : '';
    showToast(`${d.sent?.length || 0} email(s) envoyé(s)${skipped}`, d.errors?.length ? 'warning' : 'success');
    correctionModal?.hide();
  } catch (e) {
    showToast('Erreur : ' + e.message, 'danger');
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

function renderRequestsTab(requests) {
  if (!requests.length) return '<div class="text-muted small py-3">Aucune demande liee a ce media.</div>';
  return requests.map(r => {
    const error = r.overview && r.overview.includes('[ERREUR]') ? `<div class="text-danger small mt-2"><i class="bi bi-exclamation-triangle me-1"></i>${escHtml(r.overview.split('[ERREUR]').pop().trim())}</div>` : '';
    const adminActions = `
          ${(r.status === 'failed' || r.status === 'pending') ? `<button class="btn btn-sm btn-outline-warning" onclick="retryRequest(${r.id}, this)"><i class="bi bi-arrow-clockwise me-1"></i>Reessayer</button>` : ''}
          ${!r.request_mail_sent ? `<button class="btn btn-sm btn-outline-secondary" onclick="markProcessed(${r.id}, this, 'request')"><i class="bi bi-envelope me-1"></i>Mail demande</button>` : ''}
          ${r.status !== 'available' ? `<button class="btn btn-sm btn-outline-success" onclick="markProcessed(${r.id}, this, 'available')"><i class="bi bi-check-all me-1"></i>Cloturer</button>` : ''}
          <button class="btn btn-sm btn-outline-danger" onclick='deleteRequest(${r.id}, ${JSON.stringify(!!r.arr_id && !(r.arr_slug || "").startsWith("prowlarr:"))})'><i class="bi bi-trash"></i></button>`;
    // Non-admin : uniquement « Annuler ma demande », et seulement sur ses propres demandes.
    const cancelAction = (!IS_ADMIN && _isOwnRequest(r) && r.status !== 'available')
      ? `<button class="btn btn-sm btn-outline-danger" onclick="cancelOwnRequest(${r.id}, this)"><i class="bi bi-x-circle me-1"></i>Annuler ma demande</button>`
      : '';
    return `<div class="border rounded p-3 mb-2" style="border-color:var(--pr-border)!important;background:var(--pr-surface-2)">
      <div class="d-flex flex-wrap justify-content-between gap-2">
        <div>
          <div class="fw-semibold">${statusBadge(r.status)} <span class="badge bg-secondary ms-1">${escHtml(r.source || '?')}</span></div>
          ${IS_ADMIN ? requesterEditor(r) : ''}
          <div class="text-muted small">Demandee le ${fmtDateTime(r.requested_at)}${r.available_at ? ' · Disponible le ' + fmtDateTime(r.available_at) : ''}</div>
          ${IS_ADMIN ? `<div class="text-muted small">Email demande: ${r.request_mail_sent ? 'envoye' : 'non envoye'} · Email dispo: ${r.available_mail_sent ? 'envoye' : 'non envoye'}</div>` : ''}
          ${error}
        </div>
        <div class="d-flex flex-wrap gap-1 align-self-start">
          ${IS_ADMIN ? adminActions : cancelAction}
        </div>
      </div>
    </div>`;
  }).join('');
}

// --- Gestion des demandeurs (principal + additionnels) ---------------------
function _reqIds(r) {
  if (Array.isArray(r.requester_ids)) return r.requester_ids.filter(Boolean);
  try { return [r.plex_user_id, ...JSON.parse(r.extra_requesters || '[]').map(e => e.plex_user_id)].filter(Boolean); }
  catch (e) { return [r.plex_user_id].filter(Boolean); }
}
function requesterEditor(r) {
  const ids = _reqIds(r);
  const names = r.requesters || [];
  const chips = ids.map((id, i) =>
    `<span class="badge bg-secondary d-inline-flex align-items-center gap-1">${i === 0 ? '<i class="bi bi-star-fill text-warning" title="Demandeur principal"></i>' : ''}${escHtml(names[i] || id)}${ids.length > 1 ? `<a href="#" class="text-white ms-1" style="text-decoration:none" title="Retirer" onclick="removeRequester(event, ${r.id}, '${escHtml(id)}')">&times;</a>` : ''}</span>`
  ).join('');
  const avail = (_addUsers || []).filter(u => u.enabled && !ids.includes(u.plex_user_id));
  const opts = avail.map(u => `<option value="${escHtml(u.plex_user_id)}">${escHtml(u.custom_name || u.display_name || u.plex_user_id)}</option>`).join('');
  const add = avail.length ? `<select class="form-select form-select-sm" style="width:auto" onchange="addRequester(${r.id}, this.value)"><option value="">+ Ajouter…</option>${opts}</select>` : '';
  return `<div class="d-flex flex-wrap align-items-center gap-1 mt-1"><i class="bi bi-people me-1 text-muted" title="Demandeurs"></i>${chips}${add}</div>`;
}
function _findReq(reqId) { return ((currentMediaDetail && currentMediaDetail.requests) || []).find(x => x.id === reqId); }
async function addRequester(reqId, userId) {
  if (!userId) return;
  const r = _findReq(reqId); if (!r) return;
  const ids = _reqIds(r); if (!ids.includes(userId)) ids.push(userId);
  await _saveRequesters(reqId, ids);
}
async function removeRequester(ev, reqId, userId) {
  ev.preventDefault();
  const r = _findReq(reqId); if (!r) return;
  const ids = _reqIds(r).filter(i => i !== userId);
  if (!ids.length) { showToast('Au moins un demandeur est requis', 'warning'); return; }
  await _saveRequesters(reqId, ids);
}
async function _saveRequesters(reqId, ids) {
  try {
    // Modification manuelle : le backend n'envoie aucun mail de demande.
    const r = await fetch(`/api/requests/${reqId}/requesters`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ requester_ids: ids })
    });
    if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || 'Erreur'); }
    showToast('Demandeurs mis à jour', 'success');
    const m = currentMediaDetail && currentMediaDetail.media;
    openMediaDetail(m ? m.library_id : null, m ? m.request_id : null);
  } catch (e) { showToast('Erreur : ' + e.message, 'danger'); }
}

function renderCalendarTab(d) {
  const events = d.calendar || [];
  if (!events.length) return '<div class="text-muted small py-3">Aucune date connue pour ce media.</div>';
  return `<div class="list-group list-group-flush" style="max-height:520px;overflow:auto">
    ${events.map(e => `<div class="list-group-item bg-transparent text-white border-secondary d-flex align-items-center gap-3">
      <span class="badge ${e.type === 'episode' ? 'bg-info text-dark' : 'bg-primary'}">${e.type === 'episode' ? 'Episode' : 'Film'}</span>
      <div class="flex-grow-1">
        <div class="fw-semibold">${escHtml(e.subtitle || e.title)}</div>
        <div class="text-muted small">${fmtDateTime(e.date)}${e.instance ? ' · ' + escHtml(e.instance) : ''}</div>
      </div>
      ${e.has_file ? '<span class="badge badge-available">Disponible</span>' : '<span class="badge bg-secondary">A venir</span>'}
    </div>`).join('')}
  </div>`;
}

function renderSearchTab(m) {
  const reqId = m.request_id == null ? 'null' : m.request_id;
  const inst = m.arr_instance_id == null ? 'null' : m.arr_instance_id;
  return `<div class="d-flex justify-content-between align-items-center mb-2">
    <div class="text-muted small">Recherche interactive ${m.media_type === 'show' ? 'Sonarr' : 'Radarr'} avec les releases VF en tete.</div>
    <button class="btn btn-sm btn-outline-primary" onclick="loadReleaseSearch('${m.media_type}', ${m.arr_id}, ${inst}, ${reqId})"><i class="bi bi-search me-1"></i>Charger les releases</button>
  </div><div id="release-results"></div>`;
}

// Priorite : si le media est lie a une instance Sonarr/Radarr (arr_id present), on utilise
// leur recherche interactive native (renderSearchTab, inchange). Sinon (aucun Sonarr/Radarr
// pour ce media), on retombe sur une recherche directe Prowlarr + client torrent — mais
// seulement si ce secours est reellement configure, sinon on l'indique clairement.
async function loadSearchTab(m) {
  const body = document.getElementById('search-tab-body');
  if (!body) return;
  if (m.arr_id) {
    body.innerHTML = renderSearchTab(m);
    return;
  }
  try {
    const caps = await fetch('/api/arr/capabilities').then(r => r.json());
    if (caps.has_prowlarr && caps.has_download_clients) {
      body.innerHTML = renderProwlarrSearchTab(m);
    } else {
      body.innerHTML = '<div class="text-muted small py-3">Aucun mecanisme de recherche configure pour ce media (ni Sonarr/Radarr, ni Prowlarr + client de telechargement).</div>';
    }
  } catch (e) {
    body.innerHTML = `<div class="text-danger small">${escHtml(e.message)}</div>`;
  }
}

function renderProwlarrSearchTab(m) {
  const reqId = m.request_id == null ? 'null' : m.request_id;
  const query = escHtml(`${m.title || ''}${m.year ? ' ' + m.year : ''}`);
  return `<div class="text-muted small mb-2">Aucune instance Sonarr/Radarr liee a ce media — recherche directe via Prowlarr (mecanisme de secours).</div>
  <div class="input-group input-group-sm mb-2">
    <input type="text" id="prowlarr-search-query" class="form-control" value="${query}">
    <button class="btn btn-outline-primary" onclick="loadProwlarrSearch('${m.media_type}', ${reqId})"><i class="bi bi-search me-1"></i>Rechercher</button>
  </div><div id="prowlarr-release-results"></div>`;
}

const _FRENCH_TITLE_WORDS = new Set(['french', 'truefrench', 'vff', 'vf', 'vfi', 'vfq', 'multi']);
function _releaseLooksFrench(title) {
  const words = (title || '').toLowerCase().replace(/[._-]/g, ' ').split(/\s+/);
  return words.some(w => _FRENCH_TITLE_WORDS.has(w));
}

async function loadProwlarrSearch(mediaType, requestId) {
  const target = document.getElementById('prowlarr-release-results');
  const query = document.getElementById('prowlarr-search-query').value.trim();
  if (!query) return;
  target.innerHTML = '<div class="text-center py-3"><span class="spinner-border spinner-border-sm text-warning"></span></div>';
  try {
    const rels = await fetch(`/api/search?query=${encodeURIComponent(query)}&media_type=${mediaType}`).then(r => r.json());
    target.innerHTML = renderProwlarrReleases(rels, requestId);
  } catch (e) {
    target.innerHTML = `<div class="text-danger small">${escHtml(e.message)}</div>`;
  }
}

function renderProwlarrReleases(rels, requestId) {
  if (!rels || !rels.length) return '<div class="text-muted small py-3">Aucune release trouvee.</div>';
  const req = requestId == null ? 'null' : requestId;
  const rows = rels.map(r => {
    const vf = _releaseLooksFrench(r.title) ? '<span class="badge badge-available me-1">VF</span>' : '';
    return `<tr><td><div class="small">${vf}${escHtml(r.title)}</div><div class="text-muted" style="font-size:11px">${escHtml(r.indexer||'')}</div></td><td class="text-nowrap small">${formatBytes(r.size)}</td><td class="text-nowrap small"><span class="text-success">${r.seeders}</span></td><td><button class="btn btn-sm btn-warning py-0 px-2" onclick='grabProwlarrRelease(${JSON.stringify(r.downloadUrl)}, ${req}, this)'><i class="bi bi-download"></i></button></td></tr>`;
  }).join('');
  return `<div class="table-responsive"><table class="table table-dark table-sm table-hover align-middle mb-0"><thead><tr><th>Release</th><th>Taille</th><th>Seed</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

async function grabProwlarrRelease(downloadUrl, requestId, btn) {
  if (!downloadUrl) { showToast('Aucun lien de telechargement pour cette release', 'danger'); return; }
  btn.disabled = true; btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
  try {
    const clients = await fetch('/api/download-clients').then(r => r.json());
    const client = clients.find(c => c.enabled && c.is_default) || clients.find(c => c.enabled);
    if (!client) throw new Error('Aucun client de telechargement actif');
    const r = await fetch('/api/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: client.id, torrent_url_or_magnet: downloadUrl, request_id: requestId }),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'Erreur');
    showToast('Envoye au client de telechargement', 'success'); btn.innerHTML = '<i class="bi bi-check-lg"></i>';
  } catch (e) { showToast('Echec : ' + e.message, 'danger'); btn.disabled = false; btn.innerHTML = '<i class="bi bi-download"></i>'; }
}

async function loadVfDetail(m) {
  const body = document.getElementById('vf-tab-body');
  if (!body || !m.vf_source_id) {
    if (body) body.innerHTML = '<div class="text-muted small">Aucune source VFF disponible.</div>';
    return;
  }
  const path = sourcePath(m.vf_source_type);
  try {
    const d = await fetch(`/api/${path}/${m.vf_source_id}/vf-detail`).then(r => r.json());
    if (currentMediaDetail && m.media_type === 'show') currentMediaDetail.vf_seasons = d.seasons || [];
    const actions = (VFF_ENABLED && IS_ADMIN) ? vfActionsBar(m) : '';
    body.innerHTML = actions + (m.media_type === 'show' ? renderVfSeasons(d, m) : renderVfTracks(d));
  } catch (e) {
    body.innerHTML = `<div class="text-danger small">${escHtml(e.message)}</div>`;
  }
}
function vfActionsBar(m) {
  const force = m.media_type === 'show' ? `<button class="btn btn-sm btn-outline-warning" onclick="scanVff('${m.vf_source_type}', ${m.vf_source_id}, {force:true})"><i class="bi bi-exclamation-triangle me-1"></i>Forcer</button>` : '';
  const ignore = m.has_vf === false ? `<button class="btn btn-sm btn-outline-success" onclick="ignoreVff('${m.vf_source_type}', ${m.vf_source_id})"><i class="bi bi-bell-slash me-1"></i>Arreter le suivi</button>` : '';
  return `<div class="d-flex justify-content-end gap-2 mb-2"><button class="btn btn-sm btn-outline-warning" onclick="scanVff('${m.vf_source_type}', ${m.vf_source_id})"><i class="bi bi-arrow-clockwise me-1"></i>Verifier VFF</button>${force}${ignore}</div>`;
}
const VF_STATUS_META = {
  vf: { badge: 'badge-available', icon: 'bi-translate', label: 'VF' },
  vo: { badge: 'badge-sent', icon: 'bi-translate', label: 'VO' },
  present: { badge: 'bg-info text-dark', icon: 'bi-check-circle', label: 'Present' },
  absent: { badge: 'badge-pending', icon: 'bi-dash-circle', label: 'Absent' },
  unknown: { badge: 'bg-secondary', icon: 'bi-question-circle', label: 'Present' },
};
const VF_FILTERS = [
  { key: 'all', label: 'Tous', icon: 'bi-list-ul' },
  { key: 'vf', label: 'VF', icon: 'bi-translate' },
  { key: 'vo', label: 'VO', icon: 'bi-translate' },
  { key: 'unknown', label: 'A verifier', icon: 'bi-question-circle' },
  { key: 'absent', label: 'Absents', icon: 'bi-dash-circle' },
];
function renderVfTracks(d) {
  if (d.error) return `<div class="text-warning small py-2">${escHtml(d.error)}</div>`;
  if (d.vf_available === false) return '<div class="alert alert-secondary py-2 small">Suivi VFF desactive.</div>';
  if (!d.found) return '<div class="text-muted small py-2">Film introuvable dans les bibliotheques Plex configurees.</div>';
  if (!d.tracks || !d.tracks.length) return '<div class="text-muted small py-2">Aucune piste audio detectee.</div>';
  return `<ul class="list-unstyled mb-0">${d.tracks.map(t => `<li class="d-flex align-items-center gap-2 py-1"><span class="badge ${t.is_fr ? 'badge-available' : 'bg-secondary'}" style="min-width:42px">${t.is_fr ? 'VF' : 'VO'}</span><span class="small">${escHtml(t.label || t.lang || '?')}</span></li>`).join('')}</ul>`;
}
function episodeThumbHtml(url, fallbackUrl, icon = 'bi-tv') {
  const src = url || fallbackUrl;
  if (src) {
    return `<img src="${escHtml(src)}" alt="" loading="lazy" style="width:72px;height:42px;object-fit:cover;border-radius:6px;border:1px solid var(--pr-border);background:var(--pr-surface-2)" class="flex-shrink-0">`;
  }
  return `<div style="width:72px;height:42px;border-radius:6px;border:1px solid var(--pr-border);background:var(--pr-surface-2)" class="d-flex align-items-center justify-content-center flex-shrink-0"><i class="bi ${icon} text-muted"></i></div>`;
}
function seasonPosterHtml(url, fallbackUrl) {
  const src = url || fallbackUrl;
  if (src) {
    return `<img src="${escHtml(src)}" alt="" loading="lazy" style="width:50px;height:75px;object-fit:cover;border-radius:6px;border:1px solid var(--pr-border);background:var(--pr-surface-2)" class="flex-shrink-0">`;
  }
  return `<div style="width:50px;height:75px;border-radius:6px;border:1px solid var(--pr-border);background:var(--pr-surface-2)" class="d-flex align-items-center justify-content-center flex-shrink-0"><i class="bi bi-collection-play text-muted"></i></div>`;
}
function sumEpisodeCounts(seasons) {
  const totals = { vf: 0, vo: 0, present: 0, absent: 0, unknown: 0, all: 0 };
  (seasons || []).forEach(s => {
    const c = s.counts || {};
    ['vf', 'vo', 'present', 'absent', 'unknown'].forEach(k => { totals[k] += c[k] || 0; });
    totals.all += (s.episodes || []).length;
  });
  return totals;
}
function setEpisodeFilter(filter) {
  episodeFilter = filter || 'all';
  document.querySelectorAll('[data-vf-filter]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.vfFilter === episodeFilter);
  });
  document.querySelectorAll('.vf-episode-row').forEach(row => {
    const show = episodeFilter === 'all' || row.dataset.status === episodeFilter;
    row.style.display = show ? '' : 'none';
  });
  document.querySelectorAll('.vf-season-item').forEach(item => {
    const visible = Array.from(item.querySelectorAll('.vf-episode-row')).some(row => row.style.display !== 'none');
    item.style.display = visible ? '' : 'none';
  });
}
function renderVfSeasons(d, m) {
  if (d.error) return `<div class="text-warning small py-2">${escHtml(d.error)}</div>`;
  if (!d.seasons || !d.seasons.length) return '<div class="text-muted small py-2">Aucun episode suivi trouve.</div>';
  episodeFilter = 'all';
  const accId = 'vf-acc-' + Math.random().toString(36).slice(2, 8);
  const reqId = m.request_id == null ? 'null' : m.request_id;
  const libId = m.library_id == null ? 'null' : m.library_id;
  return `<div class="accordion mt-2" id="${accId}">${d.seasons.map((s, i) => {
    const c = s.counts || {};
    const summary = [c.vf && `${c.vf} VF`, c.vo && `${c.vo} VO`, c.present && `${c.present} presents`, c.unknown && `${c.unknown} inconnus`, c.absent && `${c.absent} absents`].filter(Boolean).join(' · ');
    // Meme principe que le badge serie, applique a l'echelle de la saison : entierement
    // en VF, partiellement (episodes VF et VO melanges), ou rien de special sinon.
    let seasonBadge = '';
    if ((c.vf || 0) > 0 && (c.vo || 0) === 0) {
      seasonBadge = '<span class="badge badge-available ms-2" style="font-size:10px"><i class="bi bi-translate me-1"></i>VF</span>';
    } else if ((c.vf || 0) > 0 && (c.vo || 0) > 0) {
      seasonBadge = '<span class="badge bg-info text-dark ms-2" style="font-size:10px" title="Episodes VF et VO melanges dans cette saison"><i class="bi bi-translate me-1"></i>VF Partiel</span>';
    }
    const eps = (s.episodes || []).map(e => {
      const meta = VF_STATUS_META[e.status] || VF_STATUS_META.unknown;
      const correctionBtn = IS_ADMIN ? `<button class="btn btn-link btn-sm p-0 text-success" title="Signaler une correction pour cet épisode" onclick="openCorrectionModal(${reqId}, ${libId}, {scope:'episode', season:${s.season_number}, episode:${e.episode}})"><i class="bi bi-envelope-check"></i></button>` : '';
      return `<li class="d-flex align-items-center gap-2 py-1" style="font-size:12px"><span class="badge ${meta.badge}" style="min-width:58px"><i class="bi ${meta.icon} me-1"></i>${meta.label}</span><span class="text-muted" style="min-width:34px">E${String(e.episode).padStart(2,'0')}</span><span class="text-truncate flex-grow-1">${escHtml(e.title || '')}</span>${correctionBtn}<button class="btn btn-link btn-sm p-0 text-muted" onclick="scanVff('${m.vf_source_type}', ${m.vf_source_id}, {force:true, season:${s.season_number}, episode:${e.episode}})"><i class="bi bi-arrow-repeat"></i></button></li>`;
    }).join('');
    const seasonCorrectionBtn = IS_ADMIN ? `<button class="btn btn-sm btn-outline-success py-0 px-2" title="Signaler une correction pour cette saison" onclick="openCorrectionModal(${reqId}, ${libId}, {scope:'season', season:${s.season_number}})"><i class="bi bi-envelope-check"></i></button>` : '';
    return `<div class="accordion-item" style="background:transparent;border-color:var(--pr-border)"><h2 class="accordion-header d-flex align-items-center" style="gap:4px"><button class="accordion-button collapsed py-2" type="button" data-bs-toggle="collapse" data-bs-target="#${accId}-c${i}" style="background:var(--pr-surface);color:var(--bs-body-color);font-size:13px;flex:1"><strong class="me-2">Saison ${s.season_number}</strong><span class="small">${summary}</span>${seasonBadge}</button>${seasonCorrectionBtn}<button class="btn btn-sm btn-outline-warning py-0 px-2" onclick="scanVff('${m.vf_source_type}', ${m.vf_source_id}, {force:true, season:${s.season_number}})"><i class="bi bi-arrow-repeat"></i></button></h2><div id="${accId}-c${i}" class="accordion-collapse collapse" data-bs-parent="#${accId}"><div class="accordion-body py-2"><ul class="list-unstyled mb-0">${eps}</ul></div></div></div>`;
  }).join('')}</div>`;
}
function renderVfSeasons(d, m) {
  if (d.error) return `<div class="text-warning small py-2">${escHtml(d.error)}</div>`;
  if (!d.seasons || !d.seasons.length) return '<div class="text-muted small py-2">Aucun episode suivi trouve.</div>';
  episodeFilter = 'all';
  const accId = 'vf-acc-' + Math.random().toString(36).slice(2, 8);
  const reqId = m.request_id == null ? 'null' : m.request_id;
  const libId = m.library_id == null ? 'null' : m.library_id;
  const totals = sumEpisodeCounts(d.seasons);
  const posterFallback = d.poster_url || m.poster_url;
  const summaryCards = [
    { label: 'Episodes', value: totals.all, icon: 'bi-collection-play', color: 'text-warning' },
    { label: 'VF', value: totals.vf, icon: 'bi-translate', color: 'text-success' },
    { label: 'VO', value: totals.vo, icon: 'bi-volume-up', color: 'text-info' },
    { label: 'A verifier', value: totals.unknown, icon: 'bi-question-circle', color: 'text-secondary' },
    { label: 'Absents', value: totals.absent, icon: 'bi-dash-circle', color: 'text-warning' },
  ].map(card => `<div class="d-flex align-items-center gap-2 px-2 py-1 rounded" style="background:var(--pr-surface);border:1px solid var(--pr-border);min-width:96px"><i class="bi ${card.icon} ${card.color}"></i><div><div class="fw-semibold lh-1">${card.value}</div><div class="text-muted" style="font-size:11px">${card.label}</div></div></div>`).join('');
  const filters = VF_FILTERS.map(f => {
    const count = f.key === 'all' ? totals.all : totals[f.key] || 0;
    return `<button type="button" class="btn btn-sm btn-outline-secondary ${episodeFilter === f.key ? 'active' : ''}" data-vf-filter="${f.key}" onclick="setEpisodeFilter('${f.key}')"><i class="bi ${f.icon} me-1"></i>${f.label}<span class="badge bg-dark ms-1">${count}</span></button>`;
  }).join('');
  const accordion = `<div class="accordion mt-2" id="${accId}">${d.seasons.map((s, i) => {
    const c = s.counts || {};
    const seasonTotal = (s.episodes || []).length || Object.values(c).reduce((a, b) => a + (b || 0), 0);
    const progressValue = d.vf_available === false ? (c.present || 0) : (c.vf || 0);
    const progressPct = seasonTotal ? Math.round(progressValue / seasonTotal * 100) : 0;
    const summary = [c.vf && `${c.vf} VF`, c.vo && `${c.vo} VO`, c.present && `${c.present} presents`, c.unknown && `${c.unknown} a verifier`, c.absent && `${c.absent} absents`].filter(Boolean).join(' - ');
    let seasonBadge = '';
    if ((c.vf || 0) > 0 && (c.vo || 0) === 0) {
      seasonBadge = '<span class="badge badge-available ms-2" style="font-size:10px"><i class="bi bi-translate me-1"></i>VF</span>';
    } else if ((c.vf || 0) > 0 && (c.vo || 0) > 0) {
      seasonBadge = '<span class="badge bg-info text-dark ms-2" style="font-size:10px" title="Episodes VF et VO melanges dans cette saison"><i class="bi bi-translate me-1"></i>VF Partiel</span>';
    }
    const eps = (s.episodes || []).map(e => {
      const meta = VF_STATUS_META[e.status] || VF_STATUS_META.unknown;
      const correctionBtn = IS_ADMIN ? `<button class="btn btn-sm btn-link p-0 text-success" title="Signaler une correction pour cet episode" onclick="openCorrectionModal(${reqId}, ${libId}, {scope:'episode', season:${s.season_number}, episode:${e.episode}})"><i class="bi bi-envelope-check"></i></button>` : '';
      const airDate = e.air_date ? `<span class="text-muted"><i class="bi bi-calendar3 me-1"></i>${fmtDate(e.air_date)}</span>` : '';
      const fileBadge = e.has_file ? '<span class="text-muted"><i class="bi bi-hdd me-1"></i>Fichier</span>' : '';
      return `<li class="vf-episode-row d-flex align-items-center gap-2 py-2 px-1 border-bottom" data-status="${escHtml(e.status || 'unknown')}" style="border-color:var(--pr-border)!important;font-size:12px">
        ${episodeThumbHtml(e.thumb_url, s.poster_url || posterFallback)}
        <div class="min-w-0 flex-grow-1">
          <div class="d-flex align-items-center gap-2">
            <span class="badge ${meta.badge}" style="min-width:58px"><i class="bi ${meta.icon} me-1"></i>${meta.label}</span>
            <span class="text-muted text-nowrap">S${String(s.season_number).padStart(2,'0')}E${String(e.episode).padStart(2,'0')}</span>
            <span class="text-truncate fw-semibold">${escHtml(e.title || 'Episode sans titre')}</span>
          </div>
          <div class="d-flex flex-wrap gap-2 mt-1" style="font-size:11px">${airDate}${fileBadge}</div>
        </div>
        <div class="d-flex align-items-center gap-2 flex-shrink-0">${correctionBtn}<button class="btn btn-sm btn-link p-0 text-muted" title="Verifier cet episode" onclick="scanVff('${m.vf_source_type}', ${m.vf_source_id}, {force:true, season:${s.season_number}, episode:${e.episode}})"><i class="bi bi-arrow-repeat"></i></button></div>
      </li>`;
    }).join('');
    const seasonCorrectionBtn = IS_ADMIN ? `<button class="btn btn-sm btn-outline-success py-1 px-2" title="Signaler une correction pour cette saison" onclick="openCorrectionModal(${reqId}, ${libId}, {scope:'season', season:${s.season_number}})"><i class="bi bi-envelope-check"></i></button>` : '';
    return `<div class="accordion-item vf-season-item" style="background:transparent;border-color:var(--pr-border)">
      <h2 class="accordion-header d-flex align-items-stretch" style="gap:6px">
        <button class="accordion-button collapsed py-2" type="button" data-bs-toggle="collapse" data-bs-target="#${accId}-c${i}" style="background:var(--pr-surface);color:var(--bs-body-color);font-size:13px;flex:1">
          <div class="d-flex align-items-center gap-3 w-100 pe-2">
            ${seasonPosterHtml(s.poster_url, posterFallback)}
            <div class="min-w-0 flex-grow-1">
              <div class="d-flex align-items-center flex-wrap gap-1"><strong>Saison ${s.season_number}</strong>${seasonBadge}</div>
              <div class="small text-muted text-truncate">${summary || 'Aucun statut'}</div>
              <div class="progress mt-2" style="height:5px;background:var(--pr-surface-2)"><div class="progress-bar bg-warning" style="width:${progressPct}%"></div></div>
            </div>
            <span class="text-muted small text-nowrap">${progressPct}%</span>
          </div>
        </button>
        <div class="d-flex align-items-center gap-1 py-2">${seasonCorrectionBtn}<button class="btn btn-sm btn-outline-warning py-1 px-2" title="Verifier cette saison" onclick="scanVff('${m.vf_source_type}', ${m.vf_source_id}, {force:true, season:${s.season_number}})"><i class="bi bi-arrow-repeat"></i></button></div>
      </h2>
      <div id="${accId}-c${i}" class="accordion-collapse collapse" data-bs-parent="#${accId}"><div class="accordion-body py-0 px-2"><ul class="list-unstyled mb-0">${eps}</ul></div></div>
    </div>`;
  }).join('')}</div>`;
  setTimeout(() => setEpisodeFilter(episodeFilter), 0);
  return `<div class="d-flex flex-wrap gap-2 mb-2">${summaryCards}</div><div class="d-flex flex-wrap gap-2 mb-2">${filters}</div>${accordion}`;
}
async function scanVff(kind, id, { force = false, season = null, episode = null } = {}) {
  if (force && !await confirmAction({ title:'Forcer la verification', body:'Purger le cache VF et re-verifier dans Plex ?', okLabel:'Forcer' })) return;
  const params = new URLSearchParams();
  if (force) params.set('force', 'true');
  if (season != null) params.set('season', season);
  if (episode != null) params.set('episode', episode);
  const qs = params.toString() ? '?' + params.toString() : '';
  const path = sourcePath(kind);
  try {
    const r = await fetch(`/api/${path}/${id}/vff-scan${qs}`, { method:'POST' });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || 'Erreur');
    showToast('Scan VFF reussi', 'success');
    setTimeout(() => location.reload(), 800);
  } catch (e) { showToast('Erreur : ' + e.message, 'danger'); }
}
async function ignoreVff(kind, id) {
  if (!await confirmAction({ title:'Arreter le suivi VFF', body:'Marquer ce media comme traite ?', okLabel:'Arreter' })) return;
  const path = sourcePath(kind);
  const r = await fetch(`/api/${path}/${id}/vff-ignore`, { method:'POST' });
  if (r.ok) { showToast('Suivi VFF arrete', 'success'); setTimeout(() => location.reload(), 800); }
  else showToast('Echec', 'danger');
}

async function loadReleaseSearch(mediaType, arrId, instanceId, requestId) {
  const target = document.getElementById('release-results');
  target.innerHTML = '<div class="text-center py-3"><span class="spinner-border spinner-border-sm text-warning"></span></div>';
  let url = `/api/arr/releases?media_type=${mediaType}&arr_id=${arrId}`;
  if (instanceId != null) url += `&instance_id=${instanceId}`;
  try {
    const rels = await fetch(url).then(r => r.json());
    target.innerHTML = renderArrReleases(rels, mediaType, instanceId, requestId);
  } catch (e) {
    target.innerHTML = `<div class="text-danger small">${escHtml(e.message)}</div>`;
  }
}
function renderArrReleases(rels, mediaType, instanceId, requestId) {
  if (!rels || !rels.length) return '<div class="text-muted small py-3">Aucune release trouvee.</div>';
  const inst = instanceId == null ? 'null' : instanceId;
  const req = requestId == null ? 'null' : requestId;
  const rows = rels.map(r => {
    const vf = r.is_french ? '<span class="badge badge-available me-1">VF</span>' : '';
    return `<tr ${r.is_french ? 'style="background:rgba(229,160,13,.08)"' : ''}><td><div class="small">${vf}${escHtml(r.title)}${r.rejected ? '<i class="bi bi-exclamation-triangle text-warning ms-1"></i>' : ''}</div><div class="text-muted" style="font-size:11px">${escHtml(r.indexer||'')} · ${escHtml(r.quality||'')}</div></td><td class="text-nowrap small">${formatBytes(r.size)}</td><td class="text-nowrap small"><span class="text-success">${r.seeders}</span></td><td class="text-nowrap small">${r.custom_format_score}</td><td><button class="btn btn-sm btn-warning py-0 px-2" onclick='grabRelease(${JSON.stringify(mediaType)}, ${JSON.stringify(r.guid)}, ${r.indexer_id}, ${inst}, ${req}, this)'><i class="bi bi-download"></i></button></td></tr>`;
  }).join('');
  return `<div class="table-responsive"><table class="table table-dark table-sm table-hover align-middle mb-0"><thead><tr><th>Release</th><th>Taille</th><th>Seed</th><th>Score</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
async function grabRelease(mediaType, guid, indexerId, instanceId, requestId, btn) {
  btn.disabled = true; btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
  try {
    const r = await fetch('/api/arr/grab', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ media_type:mediaType, guid, indexer_id:indexerId, instance_id:instanceId, request_id:requestId }) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'Erreur');
    showToast('Release envoyee', 'success'); btn.innerHTML = '<i class="bi bi-check-lg"></i>';
  } catch (e) { showToast('Echec : ' + e.message, 'danger'); btn.disabled = false; btn.innerHTML = '<i class="bi bi-download"></i>'; }
}

function getSelectedIds() { return Array.from(document.querySelectorAll('.row-checkbox:checked')).map(cb => parseInt(cb.value)).filter(Boolean); }
function toggleSelectAll(master) { document.querySelectorAll('.row-checkbox').forEach(cb => cb.checked = master.checked); updateBulkBar(); }
function updateBulkBar() {
  const count = getSelectedIds().length;
  document.getElementById('bulk-select-count').textContent = count;
  document.getElementById('bulk-actions-bar').style.setProperty('display', count ? 'flex' : 'none', 'important');
}
async function retryRequest(id, btn) {
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>'; }
  try {
    const r = await fetch(`/api/requests/${id}/retry`, { method:'POST' });
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    showToast('Verification relancee', 'warning');
    setTimeout(() => location.reload(), 1000);
  } catch (e) { showToast('Erreur : ' + e.message, 'danger'); if (btn) { btn.disabled = false; btn.innerHTML = '<i class="bi bi-arrow-clockwise"></i>'; } }
}
async function markProcessed(id, btn, event) {
  const label = event === 'request' ? 'Renvoyer le mail de demande ?' : 'Envoyer le mail de disponibilite et cloturer ?';
  if (!await confirmAction({ title:'Confirmer', body:label, okLabel:'Confirmer' })) return;
  if (btn) btn.disabled = true;
  try {
    const r = await fetch(`/api/requests/${id}/mark-processed?event=${event}`, { method:'POST' });
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    showToast('Action effectuee', 'success');
    setTimeout(() => location.reload(), 800);
  } catch (e) { showToast('Erreur : ' + e.message, 'danger'); if (btn) btn.disabled = false; }
}
function _arrDeleteCheckboxHtml(idPrefix) {
  return `<div class="form-check mt-2 text-start">
    <input type="checkbox" class="form-check-input" id="${idPrefix}-arr">
    <label class="form-check-label small" for="${idPrefix}-arr">Supprimer aussi de Sonarr/Radarr</label>
  </div>
  <div class="form-check text-start">
    <input type="checkbox" class="form-check-input" id="${idPrefix}-files">
    <label class="form-check-label small" for="${idPrefix}-files">... et les fichiers deja telecharges</label>
  </div>`;
}
async function deleteRequest(id, hasArr) {
  const body = 'Supprimer definitivement cette demande ?' + (hasArr ? _arrDeleteCheckboxHtml('del-single') : '');
  if (!await confirmAction({ title:'Supprimer la demande', body, okLabel:'Supprimer', danger:true })) return;
  const deleteFromArr = hasArr && document.getElementById('del-single-arr')?.checked;
  const deleteFiles = hasArr && document.getElementById('del-single-files')?.checked;
  try {
    const params = new URLSearchParams({ delete_from_arr: deleteFromArr ? 'true' : 'false', delete_files: deleteFiles ? 'true' : 'false' });
    const r = await fetch(`/api/requests/${id}?${params.toString()}`, { method:'DELETE' });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'Erreur');
    showToast('Demande supprimee', 'success');
    setTimeout(() => location.reload(), 800);
  } catch (e) { showToast('Erreur : ' + e.message, 'danger'); }
}
// Profil portail : annulation de SA propre demande (jamais de suppression cote *arr/Plex).
async function cancelOwnRequest(id, btn) {
  if (!await confirmAction({ title:'Annuler ma demande', body:'Annuler votre demande pour ce media ?', okLabel:'Annuler la demande', danger:true })) return;
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Annulation...';
  try {
    const r = await fetch(`/api/requests/${id}/cancel`, { method:'POST' });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'Erreur');
    showToast('Demande annulee', 'success');
    setTimeout(() => location.reload(), 800);
  } catch (e) {
    showToast('Erreur : ' + e.message, 'danger');
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}
async function bulkRetry() {
  const ids = getSelectedIds(); if (!ids.length) return;
  const r = await fetch('/api/requests/bulk/retry', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ids}) });
  const d = await r.json(); showToast(`${d.count || 0} demande(s) relancee(s)`, r.ok ? 'warning' : 'danger'); if (r.ok) setTimeout(() => location.reload(), 900);
}
async function bulkMarkProcessed() {
  const ids = getSelectedIds(); if (!ids.length) return;
  if (!await confirmAction({ title:'Marquer traite', body:`Marquer ${ids.length} demande(s) comme disponibles ?`, okLabel:'Marquer' })) return;
  const r = await fetch('/api/requests/bulk/mark-processed', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ids}) });
  const d = await r.json(); showToast(`${d.count || 0} demande(s) traitee(s)`, r.ok ? 'success' : 'danger'); if (r.ok) setTimeout(() => location.reload(), 900);
}
async function bulkDelete() {
  const ids = getSelectedIds(); if (!ids.length) return;
  const body = `Supprimer ${ids.length} demande(s) ?` + _arrDeleteCheckboxHtml('del-bulk');
  if (!await confirmAction({ title:'Supprimer les demandes', body, okLabel:'Supprimer', danger:true })) return;
  const delete_from_arr = !!document.getElementById('del-bulk-arr')?.checked;
  const delete_files = !!document.getElementById('del-bulk-files')?.checked;
  const r = await fetch('/api/requests/bulk/delete', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ids, delete_from_arr, delete_files}) });
  const d = await r.json().catch(() => ({}));
  const skipped = d.skipped && d.skipped.length ? ` (${d.skipped.length} non supprimee(s), *arr injoignable)` : '';
  showToast(`${d.count || 0} demande(s) supprimee(s)${skipped}`, r.ok ? (d.skipped && d.skipped.length ? 'warning' : 'success') : 'danger');
  if (r.ok) setTimeout(() => location.reload(), 900);
}

// Utilisateurs (réutilisés par l'éditeur de demandeurs de la modale détail).
let _addUsers = [];
window._addUsersPromise = (async function _loadUsers() {
  try { const r = await fetch('/api/users'); _addUsers = r.ok ? await r.json() : []; } catch (e) { _addUsers = []; }
})();

// Code couleur par type de sortie (cinéma / digitale / physique / épisode).
function calReleaseMeta(e) {
  if (e.type === 'episode') return { color: '#0dcaf0', icon: 'bi-tv', label: 'Série', dark: true };
  switch (e.release_type) {
    case 'cinema':   return { color: '#e5a00d', icon: 'bi-camera-reels', label: 'Cinéma',   dark: true };
    case 'digital':  return { color: '#0d6efd', icon: 'bi-laptop',       label: 'Digital',  dark: false };
    case 'physical': return { color: '#6f42c1', icon: 'bi-disc',         label: 'Physique', dark: false };
    default:         return { color: '#0d6efd', icon: 'bi-film',         label: 'Film',     dark: false };
  }
}

function renderGlobalCalendar(events) {
  if (!events.length) return '<div class="text-center text-muted py-5"><i class="bi bi-calendar-x fs-1 d-block mb-2 opacity-25"></i>Aucune sortie suivie.</div>';
  const byDay = {};
  events.forEach(e => { const day = e.date.slice(0,10); (byDay[day] = byDay[day] || []).push(e); });
  return Object.keys(byDay).sort().map(day => `<div class="mb-3"><h6 class="text-warning mb-2">${fmtDate(day)}</h6><div class="card p-2">${byDay[day].map(e => {
    const m = calReleaseMeta(e);
    const poster = e.poster_url
      ? `<img src="${escHtml(e.poster_url)}" style="width:38px;height:57px;object-fit:cover;border-radius:4px" alt="">`
      : `<div style="width:38px;height:57px;border-radius:4px;background:var(--pr-surface-2)" class="d-flex align-items-center justify-content-center flex-shrink-0"><i class="bi ${m.icon}" style="color:${m.color}"></i></div>`;
    const badge = `<span class="badge" style="background:${m.color};color:${m.dark ? '#141414' : '#fff'}"><i class="bi ${m.icon} me-1"></i>${m.label}</span>`;
    const time = e.type === 'episode'
      ? `<span class="text-muted small text-nowrap ms-1"><i class="bi bi-clock me-1"></i>${new Date(e.date).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}</span>`
      : '';
    return `<div class="d-flex align-items-center gap-2 py-2 ps-2 pe-1" style="border-bottom:1px solid var(--pr-border);border-left:3px solid ${m.color}">${poster}<div class="flex-grow-1" style="min-width:0"><strong class="text-truncate d-block">${escHtml(e.title)}</strong><div class="text-muted small text-truncate">${escHtml(e.subtitle || '')}${e.instance ? ' · ' + escHtml(e.instance) : ''}</div></div>${badge}${e.has_file ? '<span class="badge badge-available">Disponible</span>' : ''}${time}</div>`;
  }).join('')}</div></div>`).join('');
}
// Le calendrier est calé sur aujourd'hui par défaut (pas de jours passés affichés).
// "Voir le mois précédent" recule le début de la plage d'un mois à chaque clic,
// pour ne remonter dans le passé que sur demande plutôt que de tout charger d'un coup.
let calendarRangeStart = null;

function _todayMidnight() {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d;
}

async function loadGlobalCalendar(prependPreviousMonth = false) {
  const container = document.getElementById('global-calendar-container');
  if (!container) return;
  if (!calendarRangeStart) calendarRangeStart = _todayMidnight();
  if (prependPreviousMonth) {
    calendarRangeStart = new Date(calendarRangeStart);
    calendarRangeStart.setMonth(calendarRangeStart.getMonth() - 1);
  }
  const btn = document.getElementById('cal-prev-month-btn');
  if (btn) { btn.disabled = true; btn.querySelector('i')?.classList.add('spin'); }
  try {
    const params = new URLSearchParams();
    params.set('tracked_only', 'true');
    params.set('start', calendarRangeStart.toISOString());
    Object.entries(LIBRARY_FILTERS).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    const events = await fetch(`/api/calendar?${params.toString()}`).then(r => r.json());
    container.innerHTML = renderGlobalCalendar(events);
  } catch (e) {
    container.innerHTML = `<div class="alert alert-danger">Erreur calendrier : ${escHtml(e.message)}</div>`;
  } finally {
    if (btn) { btn.disabled = false; btn.querySelector('i')?.classList.remove('spin'); }
  }
}
if (ACTIVE_VIEW === 'calendar') loadGlobalCalendar();
