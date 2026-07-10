
// ── Dirty tracking ────────────────────────────────────────────────────────────
let _dirty = false;
function markDirty() {
  if (_dirty) return;
  _dirty = true;
  document.getElementById('dirty-indicator').classList.remove('d-none');
}
function clearDirty() {
  _dirty = false;
  document.getElementById('dirty-indicator').classList.add('d-none');
}
document.getElementById('settings-form').addEventListener('change', markDirty);
document.getElementById('settings-form').addEventListener('input', markDirty);

// ── Connection badges (sessionStorage) ───────────────────────────────────────
function setConnBadge(service, success, label) {
  const el = document.getElementById(`conn-badge-${service}`);
  if (!el) return;
  el.className = 'conn-badge badge ' + (success ? 'bg-success' : 'bg-danger');
  el.innerHTML = `<i class="bi bi-circle-fill me-1" style="font-size:8px"></i>${label}`;
  try { sessionStorage.setItem(`conn_${service}`, JSON.stringify({success, label})); } catch(e) {}
}
function restoreConnBadges() {
  ['plex-api','plex-rss','sonarr','radarr','tmdb','seer','discord','telegram','smtp','ntfy','gotify'].forEach(s => {
    try {
      const stored = sessionStorage.getItem(`conn_${s}`);
      if (stored) { const d = JSON.parse(stored); setConnBadge(s, d.success, d.label); }
    } catch(e) {}
  });
}

// ── Connexions : hub de cartes de statut ─────────────────────────────────────
// prepArrAdd mémorise le type de la carte cliquée pour pré-remplir « Ajouter une instance ».
let _arrPreferredType = null;
function prepArrAdd(type) { _arrPreferredType = type; }

function _setHub(name, state, text, ok) {
  const el = document.getElementById('hub-st-' + name);
  if (!el) return;
  el.className = 'hub-pill ' + state;
  el.innerHTML = (ok ? '<i class="bi bi-check-circle-fill"></i> ' : '') + text;
}
// Recalcule les pastilles d'état depuis le formulaire + les listes chargées.
// Appelée après les chargements / sur saisie — jamais avant que _arrInstances soit déclaré (TDZ).
function refreshConnHub() {
  const val = n => (document.querySelector(`[name="${n}"]`)?.value || '').trim();
  const plexOk = !!(val('plex_url') && val('plex_token'));
  _setHub('plex', plexOk ? 'ok' : 'off', plexOk ? 'Configuré' : 'Non configuré', plexOk);
  const seerOk = !!(val('seer_url') && val('seer_api_key'));
  _setHub('seer', seerOk ? 'ok' : 'opt', seerOk ? 'Configuré' : 'Optionnel · non configuré', seerOk);
  const insts = _arrInstances || [];
  ['sonarr', 'radarr', 'prowlarr'].forEach(t => {
    const n = insts.filter(i => i.arr_type === t).length;
    const optional = t === 'prowlarr';
    const label = n ? `${n} instance${n > 1 ? 's' : ''}` : (optional ? 'Optionnel · non configuré' : 'Non configuré');
    _setHub(t, n ? 'ok' : (optional ? 'opt' : 'off'), label, n > 0);
  });
  const nc = (_downloadClients || []).length;
  _setHub('torrent', nc ? 'ok' : 'off', nc ? `${nc} client${nc > 1 ? 's' : ''}` : 'Non configuré', nc > 0);
  const tmdbOk = !!val('tmdb_api_key');
  _setHub('tmdb', tmdbOk ? 'ok' : 'opt', tmdbOk ? 'Configuré' : 'Optionnel · non configuré', tmdbOk);
}
// Met à jour les pastilles « valeur » (Plex/Seer/TMDB) en direct à la saisie.
document.getElementById('settings-form').addEventListener('input', () => { try { refreshConnHub(); } catch (e) {} });

// ── Seer → dim Sonarr/Radarr ────────────────────────────────────────────
function updateSeerMode() {
  const sendReq = document.getElementById('seer_send_requests')?.checked;
  const fallback = document.getElementById('seer_fallback_arr')?.checked;
  const wrap = document.getElementById('card-wrap-arr-instances');
  if (wrap) {
    const dimmed = sendReq && !fallback;
    wrap.style.opacity = dimmed ? '0.4' : '1';
    wrap.style.pointerEvents = dimmed ? 'none' : '';
    wrap.title = dimmed ? 'Géré exclusivement par Seer (fallback désactivé)' : '';
  }
}
document.getElementById('seer_send_requests')?.addEventListener('change', updateSeerMode);
document.getElementById('seer_fallback_arr')?.addEventListener('change', updateSeerMode);

async function _seerAction(btnId, url, label) {
  const btn = document.getElementById(btnId);
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>' + label + '…';
  try {
    const r = await fetch(url, { method: 'POST' });
    const d = await r.json();
    showToast(d.message || label + ' terminé', r.ok ? 'success' : 'danger');
  } catch (e) {
    showToast('Erreur : ' + e.message, 'danger');
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

function seerSyncUsers()   { _seerAction('btn-seer-sync-users',   '/api/seer/sync/users',    'Synchronisation'); }
function seerSyncStatuts() { _seerAction('btn-seer-sync-statuts', '/api/seer/sync/users',    'Mise à jour'); }

// ── Historique notifications ──────────────────────────────────────────────────
const EVENT_LABELS = { request: 'Demande', available: 'Disponible', failed: 'Échec' };
const EVENT_COLORS = { request: 'bg-primary', available: 'bg-success', failed: 'bg-danger' };
const MEDIA_ICONS  = { show: 'bi-tv', movie: 'bi-camera-video' };
const NOTIF_PAGE_SIZE = 50;
let _notifOffset = 0;
let _notifTotal = 0;

async function loadNotifLog(offset = 0) {
  _notifOffset = offset;
  const wrap = document.getElementById('notif-log-wrap');
  wrap.innerHTML = '<div class="text-center text-muted py-3"><span class="spinner-border spinner-border-sm me-2"></span>Chargement…</div>';
  try {
    const r = await fetch(`/api/notifications/log?limit=${NOTIF_PAGE_SIZE}&offset=${offset}`);
    const data = await r.json();
    _notifTotal = data.total;
    const logs = data.items;
    if (!logs.length && offset === 0) {
      wrap.innerHTML = '<p class="text-muted mb-0">Aucun email envoyé pour l\'instant.</p>';
      return;
    }
    const rows = logs.map(l => {
      const date = l.sent_at ? new Date(l.sent_at.endsWith('Z') || l.sent_at.includes('+') ? l.sent_at : l.sent_at + 'Z').toLocaleString('fr-FR', {day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'}) : '—';
      const eventLabel = l.event_label || (EVENT_LABELS[l.event] || l.event);
      const eventTitle = [l.event_group, l.event_description].filter(Boolean).join(' - ').replace(/"/g, '&quot;');
      const evBadge = `<span class="badge ${l.event_badge_class || EVENT_COLORS[l.event] || 'bg-secondary'} me-1" title="${eventTitle}">${eventLabel}</span>`;
      const adminBadge = l.is_admin ? '<span class="badge bg-warning text-dark ms-1" title="Copie admin"><i class="bi bi-shield-fill"></i></span>' : '';
      const mediaIcon = `<i class="bi ${MEDIA_ICONS[l.media_type] || 'bi-question'} me-1 text-muted"></i>`;
      const statusIcon = l.success
        ? '<i class="bi bi-check-circle-fill text-success"></i>'
        : `<i class="bi bi-x-circle-fill text-danger" title="${(l.error_msg || '').replace(/"/g,'&quot;')}"></i>`;
      const resendBtn = l.req_id
        ? `<button class="btn btn-sm btn-outline-secondary py-0 px-1 ms-1" onclick="resendNotif(${l.id}, this)" title="Renvoyer"><i class="bi bi-send"></i></button>`
        : '';
      return `<tr class="${l.success ? '' : 'table-danger bg-opacity-25'}">
        <td class="text-muted small text-nowrap">${date}</td>
        <td>${evBadge}${adminBadge}<div class="text-muted small">${l.event_group || ''}</div></td>
        <td>${mediaIcon}<span class="small">${l.media_title || '—'}</span></td>
        <td class="small text-break">${l.recipient}</td>
        <td class="text-center" title="${l.status_label || ''}">${statusIcon}${resendBtn}</td>
      </tr>`;
    }).join('');

    const totalPages = Math.ceil(_notifTotal / NOTIF_PAGE_SIZE);
    const currentPage = Math.floor(offset / NOTIF_PAGE_SIZE) + 1;
    const pagination = totalPages > 1 ? `
      <div class="d-flex justify-content-between align-items-center mt-2">
        <span class="text-muted small">${_notifTotal} entrées — page ${currentPage}/${totalPages}</span>
        <div class="btn-group btn-group-sm">
          <button class="btn btn-outline-secondary" onclick="loadNotifLog(${offset - NOTIF_PAGE_SIZE})" ${offset === 0 ? 'disabled' : ''}>
            <i class="bi bi-chevron-left"></i> Précédent
          </button>
          <button class="btn btn-outline-secondary" onclick="loadNotifLog(${offset + NOTIF_PAGE_SIZE})" ${offset + NOTIF_PAGE_SIZE >= _notifTotal ? 'disabled' : ''}>
            Suivant <i class="bi bi-chevron-right"></i>
          </button>
        </div>
      </div>` : `<div class="text-muted small mt-1">${_notifTotal} entrée${_notifTotal > 1 ? 's' : ''}</div>`;

    wrap.innerHTML = `<div class="table-responsive"><table class="table table-sm table-hover mb-0" style="font-size:13px">
      <thead><tr>
        <th class="text-muted fw-normal">Date</th>
        <th class="text-muted fw-normal">Type</th>
        <th class="text-muted fw-normal">Média</th>
        <th class="text-muted fw-normal">Destinataire</th>
        <th class="text-muted fw-normal text-center">Statut</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table></div>${pagination}`;
  } catch(e) {
    wrap.innerHTML = `<p class="text-danger mb-0">Erreur : ${e.message}</p>`;
  }
}

async function resendNotif(logId, btn) {
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
  try {
    const r = await fetch(`/api/notifications/${logId}/resend`, { method: 'POST' });
    const d = await r.json();
    if (r.ok) showToast(`Renvoi en cours vers ${d.recipient}`, 'success');
    else showToast(d.detail || 'Erreur', 'danger');
  } catch(e) {
    showToast('Erreur : ' + e.message, 'danger');
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
    setTimeout(() => loadNotifLog(_notifOffset), 1500);
  }
}

// Chargement automatique à l'ouverture de l'onglet Notifications
document.querySelector('[data-bs-target="#tab-notifications"]').addEventListener('shown.bs.tab', () => loadNotifLog(0));

// ── Section incomplete warnings ───────────────────────────────────────────────
function checkSectionWarnings() {
  const emailOn = document.getElementById('email_req').checked || document.getElementById('email_av').checked;
  const smtpHost = document.getElementById('smtp_host').value.trim();
  showSectionWarn('smtp', emailOn && !smtpHost);

  const hasConnWarn = !!document.querySelector('#tab-connexions .section-warn:not(.d-none)');
  document.getElementById('warn-connexions').classList.toggle('d-none', !hasConnWarn);
  const hasNotifWarn = !!document.querySelector('#tab-notifications .section-warn:not(.d-none)');
  document.getElementById('warn-notifications').classList.toggle('d-none', !hasNotifWarn);
}
function showSectionWarn(section, show) {
  document.querySelectorAll(`.section-warn[data-section="${section}"]`).forEach(el => {
    el.classList.toggle('d-none', !show);
  });
}
document.getElementById('settings-form').addEventListener('change', checkSectionWarnings);
document.getElementById('settings-form').addEventListener('input', checkSectionWarnings);

// ── Webhook chevron rotation ──────────────────────────────────────────────────
document.getElementById('webhooks-body').addEventListener('show.bs.collapse', () => {
  document.getElementById('webhooks-chevron').className = 'bi bi-chevron-up text-muted';
});
document.getElementById('webhooks-body').addEventListener('hide.bs.collapse', () => {
  document.getElementById('webhooks-chevron').className = 'bi bi-chevron-down text-muted';
});

function toggleTrackingMode() {
  const simple = document.getElementById('tracking-mode-simple').checked;
  document.getElementById('tracking-mode-language-fields').style.display = simple ? 'none' : '';
  document.getElementById('tracking-mode-simple-fields').style.display = simple ? '' : 'none';
}
toggleTrackingMode();

// ── Core functions ────────────────────────────────────────────────────────────
function togglePass(id) {
  const el = document.getElementById(id);
  el.type = el.type === 'password' ? 'text' : 'password';
}

function getFormData() {
  const data = {};
  document.querySelectorAll('#settings-form input, #settings-form select, #settings-form textarea').forEach(el => {
    if (!el.name) return;
    if (el.type === 'checkbox') data[el.name] = el.checked;
    else if (el.value !== '') data[el.name] = el.value;
    else data[el.name] = null; // textarea vide = effacer le template custom
  });
  return data;
}

// ── VFF : sélecteur de bibliothèques Plex ─────────────────────────────────────
let _vffInitDone = false;
function initVffTab() {
  if (_vffInitDone) return;
  _vffInitDone = true;
  loadVffSections();
  checkVffScanStatus();
  checkVffSyncStatus();
}

function _vffCurrentConfig() {
  // Config existante : {nom_lowercase: kind}
  const map = {};
  try {
    const raw = document.getElementById('vff_libraries').value;
    if (raw) JSON.parse(raw).forEach(e => { if (e.name) map[e.name.toLowerCase()] = e.kind; });
  } catch(e) {}
  return map;
}

function _vffRebuildJson() {
  const libs = [];
  document.querySelectorAll('#vff-sections-list select').forEach(sel => {
    const kind = sel.value;
    if (kind) libs.push({ name: sel.dataset.name, kind });
  });
  document.getElementById('vff_libraries').value = libs.length ? JSON.stringify(libs) : '';
  markDirty();
}

async function loadVffSections() {
  const container = document.getElementById('vff-sections-list');
  container.innerHTML = '<div class="text-muted small">Chargement des bibliothèques…</div>';
  const saved = _vffCurrentConfig();
  let sections = [];
  try {
    sections = await fetch('/api/plex/sections').then(r => r.json());
  } catch(e) {}
  if (!sections || !sections.length) {
    container.innerHTML = '<div class="text-warning small"><i class="bi bi-exclamation-triangle me-1"></i>'
      + 'Aucune bibliothèque récupérée. Vérifiez la connexion Plex (onglet Connexions).</div>';
    return;
  }
  container.innerHTML = '';
  sections.forEach(sec => {
    const isMovie = sec.type === 'movie';
    const current = saved[sec.name.toLowerCase()] || '';
    const opts = isMovie
      ? `<option value="">Ignorer</option><option value="movie">Film</option>`
      : `<option value="">Ignorer</option><option value="series">Série</option><option value="anime">Anime</option>`;
    const row = document.createElement('div');
    row.className = 'd-flex align-items-center gap-3';
    row.innerHTML = `
      <span class="flex-grow-1"><i class="bi ${isMovie ? 'bi-film' : 'bi-tv'} me-2 text-muted"></i>${sec.name}
        <span class="text-muted small">(${sec.type})</span></span>
      <select class="form-select form-select-sm" style="width:auto" data-name="${sec.name}" onchange="_vffRebuildJson()">${opts}</select>`;
    const sel = row.querySelector('select');
    sel.value = current;
    container.appendChild(row);
  });
}

let vffPollInterval = null;
async function checkVffScanStatus() {
  try {
    const d = await fetch('/api/vff/scan-status').then(r => r.json());
    const card = document.getElementById('vff-progress-card');
    const btn = document.getElementById('vff-scan-btn');
    if (!card || !btn) return;
    if (d.status === 'running') {
      card.classList.remove('d-none');
      btn.disabled = true;
      btn.querySelector('i')?.classList.add('spin');
      document.getElementById('vff-progress-text').textContent = `${d.items_scanned} / ${d.total_items || '?'}`;
      document.getElementById('vff-progress-bar').style.width = (d.total_items ? (d.items_scanned / d.total_items) * 100 : 0) + '%';
      if (!vffPollInterval) vffPollInterval = setInterval(checkVffScanStatus, 1500);
    } else {
      if (vffPollInterval) {
        clearInterval(vffPollInterval);
        vffPollInterval = null;
        showToast('Scan VF termine', 'success');
      }
      card.classList.add('d-none');
      btn.disabled = false;
      btn.querySelector('i')?.classList.remove('spin');
    }
  } catch (e) {}
}

let plexSyncPollInterval = null;
async function checkVffSyncStatus() {
  try {
    const d = await fetch('/api/vff/sync-status').then(r => r.json());
    const card = document.getElementById('plex-sync-progress-card');
    const btn = document.getElementById('vff-sync-btn');
    if (!card || !btn) return;
    if (d.status === 'running') {
      card.classList.remove('d-none');
      btn.disabled = true;
      btn.querySelector('i')?.classList.add('spin');
      document.getElementById('plex-sync-progress-text').textContent = `${d.items_synced} / ${d.total_items || '?'}`;
      document.getElementById('plex-sync-progress-bar').style.width = (d.total_items ? (d.items_synced / d.total_items) * 100 : 0) + '%';
      if (!plexSyncPollInterval) plexSyncPollInterval = setInterval(checkVffSyncStatus, 1500);
    } else {
      if (plexSyncPollInterval) {
        clearInterval(plexSyncPollInterval);
        plexSyncPollInterval = null;
        showToast('Actualisation Plex terminee', 'success');
      }
      card.classList.add('d-none');
      btn.disabled = false;
      btn.querySelector('i')?.classList.remove('spin');
    }
  } catch (e) {}
}

async function vffScanNow(btn) {
  const force = document.getElementById('vff-force-check')?.checked;
  if (force && !await confirmAction({ title:'Forcer le scan VF', body:'Purger le cache VF et re-verifier tous les medias ?', okLabel:'Forcer' })) return;
  btn.disabled = true;
  btn.querySelector('i')?.classList.add('spin');
  try {
    const res = await fetch(`/api/vff/scan${force ? '?force=true' : ''}`, { method:'POST' }).then(r => r.json());
    if (res.status === 'started' || res.status === 'already_running') {
      showToast('Scan VF lance', 'info');
      checkVffScanStatus();
    } else {
      throw new Error('Echec');
    }
  } catch (e) {
    showToast('Erreur reseau', 'danger');
    btn.disabled = false;
    btn.querySelector('i')?.classList.remove('spin');
  }
}

async function vffSyncNow(btn) {
  btn.disabled = true;
  btn.querySelector('i')?.classList.add('spin');
  try {
    const res = await fetch('/api/vff/sync-plex', { method:'POST' }).then(r => r.json());
    if (res.status === 'started' || res.status === 'already_running') {
      showToast('Actualisation Plex lancee', 'info');
      checkVffSyncStatus();
    } else {
      throw new Error('Echec');
    }
  } catch (e) {
    showToast('Erreur reseau', 'danger');
    btn.disabled = false;
    btn.querySelector('i')?.classList.remove('spin');
  }
}

async function saveSettings() {
  try {
    const r = await fetch('/api/settings', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(getFormData())
    });
    if (!r.ok) throw new Error(await r.text());
    clearDirty();
    showToast('Paramètres enregistrés !', 'success');
  } catch(e) {
    showToast('Erreur : ' + e.message, 'danger');
  }
}

// ── Maintenance ──────────────────────────────────────────────────────────────

const MAINTENANCE_ACTIONS = {
  'discover-users':     { url: '/api/users/discover',            method: 'POST', label: 'Sync RSS',                        btn: 'btn-m-discover'    },
  'seer-sync-users':    { url: '/api/seer/sync/users',           method: 'POST', label: 'Sync utilisateurs Seer',          btn: 'btn-m-seer-users'  },
  'seer-sync-requests': { url: '/api/seer/sync/requests',        method: 'POST', label: 'Sync demandes Seer',              btn: 'btn-m-seer-req'    },
  'retry-failed':       { url: '/api/requests/retry-failed',     method: 'POST', label: 'Relancer les échouées',           btn: 'btn-m-retry'       },
  'recalculate-dates':  { url: '/api/requests/recalculate-dates',method: 'POST', label: 'Recalculer les dates',            btn: 'btn-m-dates'       },
  'merge-duplicates':   { url: '/api/requests/merge-duplicates', method: 'POST', label: 'Fusionner les doublons',          btn: 'btn-m-merge'       },
};

async function maintenance(action) {
  const cfg = MAINTENANCE_ACTIONS[action];
  if (!cfg) return;
  const btn = document.getElementById(cfg.btn);
  const origHtml = btn?.innerHTML;
  if (btn) { btn.disabled = true; btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${cfg.label}…`; }
  try {
    const r = await fetch(cfg.url, { method: cfg.method });
    if (!r.ok) throw new Error((await r.json()).detail || await r.text());
    const data = await r.json();
    let msg = cfg.label + ' terminé';
    if (data.retried != null) msg += ` — ${data.retried} relancée(s)`;
    showToast(msg, 'success');
  } catch(e) {
    showToast('Erreur : ' + e.message, 'danger');
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = origHtml; }
  }
}

async function testConn(service) {
  showToast(`Test ${service} en cours...`, 'secondary');
  await saveSettings();
  const r = await fetch(`/api/test/${service}`, {method:'POST'});
  const d = await r.json();
  setConnBadge(service, d.success, d.success ? 'Connecté' : 'Échec');
  showToast(d.message, d.success ? 'success' : 'danger');
}

async function testSmtp() {
  const email = document.getElementById('test_email').value;
  if (!email) return showToast('Entrez un email de test', 'warning');
  await saveSettings();
  const r = await fetch('/api/test/smtp', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({recipient: email})
  });
  const d = await r.json();
  setConnBadge('smtp', d.success, d.success ? 'Email envoyé' : 'Échec');
  showToast(d.message, d.success ? 'success' : 'danger');
}

async function loadProfiles(service) {
  try {
    const r = await fetch(`/api/${service}/profiles`);
    if (!r.ok) return;
    const profiles = await r.json();
    const sel = document.getElementById(`${service}_profile`);
    const current = sel.value;
    sel.innerHTML = profiles.map(p =>
      `<option value="${p.id}" ${String(p.id) === String(current) ? 'selected' : ''}>${p.name}</option>`
    ).join('');
  } catch(e) {
    showToast(`Impossible de charger les profils ${service} — vérifiez l'URL et la clé API`, 'danger');
  }
}

function arrFolderPath(folder) {
  return typeof folder === 'string' ? folder : (folder?.path || '');
}

function fmtBytes(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n < 0) return null;
  const units = ['o', 'Ko', 'Mo', 'Go', 'To', 'Po'];
  let value = n;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  const digits = value >= 100 || i === 0 ? 0 : (value >= 10 ? 1 : 2);
  return `${value.toFixed(digits)} ${units[i]}`;
}

function arrFolderLabel(folder, defaultPath = null) {
  const path = arrFolderPath(folder);
  const parts = [path];
  const free = fmtBytes(folder?.free_bytes ?? folder?.freeSpace);
  const total = fmtBytes(folder?.total_bytes ?? folder?.totalSpace);
  if (free) parts.push(total ? `${free} libres / ${total}` : `${free} libres`);
  if (folder?.is_default || (defaultPath && path === defaultPath)) parts.push('Défaut');
  return parts.join(' · ');
}

async function loadFolders(service) {
  try {
    const r = await fetch(`/api/${service}/folders`);
    if (!r.ok) return;
    const folders = await r.json();
    const sel = document.getElementById(`${service}_folder`);
    const current = sel.value;
    sel.innerHTML = folders.map(f => {
      const path = arrFolderPath(f);
      return `<option value="${_esc(path)}" ${path === current ? 'selected' : ''}>${_esc(arrFolderLabel(f))}</option>`;
    }
    ).join('');
  } catch(e) {
    showToast(`Impossible de charger les dossiers ${service}`, 'danger');
  }
}

async function importData() {
  const file = document.getElementById('importFile').files[0];
  if (!file) return showToast('Sélectionnez un fichier JSON', 'warning');
  const form = new FormData();
  form.append('file', file);
  const res = document.getElementById('importResult');
  res.innerHTML = '<span class="text-muted">Import en cours...</span>';
  try {
    const r = await fetch('/api/import', {method: 'POST', body: form});
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'Erreur');
    res.innerHTML = `<span class="text-success">Import réussi — ${d.stats.users_upserted} utilisateur(s), ${d.stats.requests_upserted} demande(s)</span>`;
    showToast('Import terminé ! Rechargement...', 'success');
    setTimeout(() => location.reload(), 1500);
  } catch(e) {
    res.innerHTML = `<span class="text-danger">${e.message}</span>`;
    showToast('Erreur import : ' + e.message, 'danger');
  }
}

async function startPlexSSO() {
  const btn = document.getElementById('btn-plex-sso');
  const status = document.getElementById('sso-status');
  btn.disabled = true;
  status.textContent = 'Initialisation...';
  try {
    const r = await fetch('/api/plex/sso/pin', { method: 'POST' });
    if (!r.ok) throw new Error(await r.text());
    const d = await r.json();
    const width = 600, height = 700;
    const left = window.screenX + (window.outerWidth - width) / 2;
    const top = window.screenY + (window.outerHeight - height) / 2;
    const popup = window.open(d.auth_url, 'PlexSSO', `width=${width},height=${height},left=${left},top=${top},scrollbars=yes`);
    if (!popup) {
      btn.disabled = false;
      status.textContent = '';
      return showToast('Bloqueur de popup détecté. Veuillez autoriser les popups.', 'warning');
    }
    status.textContent = 'En attente de connexion sur Plex...';
    let attempts = 0;
    const interval = setInterval(async () => {
      attempts++;
      if (attempts > 60 || popup.closed) {
        clearInterval(interval);
        btn.disabled = false;
        status.textContent = attempts > 60 ? 'Temps écoulé.' : 'Connexion annulée.';
        return;
      }
      try {
        const checkRes = await fetch(`/api/plex/sso/check/${d.id}`);
        const checkData = await checkRes.json();
        if (checkData.authenticated && checkData.token) {
          clearInterval(interval);
          popup.close();
          document.getElementById('plex_token').value = checkData.token;
          btn.disabled = false;
          status.textContent = 'Sauvegarde...';
          await saveSettings();
          status.textContent = 'Connecté !';
          showToast('Connexion Plex réussie — token sauvegardé.', 'success');
        }
      } catch(e) { console.error('Check error', e); }
    }, 2000);
  } catch(e) {
    btn.disabled = false;
    status.textContent = 'Erreur.';
    showToast('Erreur Plex SSO : ' + e.message, 'danger');
  }
}

function copyEl(id) {
  navigator.clipboard.writeText(document.getElementById(id).value);
  showToast('URL copiée !', 'success');
}

// ── Init ──────────────────────────────────────────────────────────────────────
restoreConnBadges();
updateSeerMode();
checkSectionWarnings();
loadArrInstances();
loadDownloadClients();

// ── Maintenance tab ───────────────────────────────────────────────────────────

const MAINT_COLORS = {
  info:      { border:'#0dcaf055', label:'text-info'    },
  success:   { border:'#19875455', label:'text-success'  },
  warning:   { border:'#ffc10755', label:'text-warning'  },
  secondary: { border:'#6c757d55', label:'text-secondary'},
};

// ── Conflicts tab ─────────────────────────────────────────────────────────────

let _conflictsInited = false;

async function initConflictsTab() {
  if (_conflictsInited) return;
  await loadConflicts();
}

function _showSection(id, show) {
  document.getElementById(id).classList.toggle('d-none', !show);
}

function _statusBadge(s) {
  const map = {available:'success',sent_to_arr:'primary',pending:'warning text-dark',failed:'danger'};
  const labels = {available:'Dispo',sent_to_arr:'Transmis',pending:'Reçue',failed:'Échec'};
  return `<span class="badge bg-${map[s]||'secondary'}">${labels[s]||s}</span>`;
}

function _typeBadge(t) {
  return t === 'show'
    ? `<span class="badge bg-info text-dark">Série</span>`
    : `<span class="badge bg-primary">Film</span>`;
}

function _srcBadge(s) {
  return s === 'seer'
    ? `<span class="badge bg-info text-dark"><i class="bi bi-stars me-1"></i>Seer</span>`
    : `<span class="badge bg-secondary"><i class="bi bi-rss me-1"></i>${s}</span>`;
}

function _fmtDate(iso) {
  return iso ? new Date(iso).toLocaleDateString('fr-FR') : '—';
}

function _ignoreBtn(key) {
  return `<button class="btn btn-xs btn-outline-secondary py-0 px-1 ms-1" title="Ignorer ce conflit"
    onclick="ignoreConflict('${_esc(key)}', this)"><i class="bi bi-eye-slash"></i></button>`;
}

// ── Tmdb conflict card (B : comparaison visuelle côte à côte) ─────────────────
function _tmdbConflictCard(c) {
  const poster = c.entries.find(e => e.poster_url)?.poster_url;
  const posterHtml = poster
    ? `<img src="${_esc(poster)}" style="width:64px;border-radius:4px;object-fit:cover" class="me-3 flex-shrink-0">`
    : `<div class="me-3 flex-shrink-0 bg-secondary rounded" style="width:64px;height:90px"></div>`;

  const fields = [
    ['Titre',   e => _esc(e.title)],
    ['tmdb_id', e => e.tmdb_id ? `<code>${e.tmdb_id}</code>` : '<span class="text-muted">—</span>'],
    ['Source',  e => _srcBadge(e.source)],
    ['Statut',  e => _statusBadge(e.status)],
    ['Utilisateur', e => _esc(e.plex_user || '—')],
    ['Date',    e => `<span class="text-muted small">${_fmtDate(e.requested_at)}</span>`],
  ];

  const entryCards = c.entries.map(e => {
    const isRec = e.id === c.recommended_id;
    const rows = fields.map(([label, fn]) => `
      <tr>
        <td class="text-muted small pe-2" style="white-space:nowrap">${label}</td>
        <td>${fn(e)}</td>
      </tr>`).join('');
    return `
      <div class="col">
        <div class="card h-100 ${isRec ? 'border-success' : 'border-secondary bg-dark'}" style="background:var(--pr-surface)">
          ${isRec ? '<div class="card-header py-1 px-2 bg-success bg-opacity-25 small text-success"><i class="bi bi-stars me-1"></i>Recommandé (Seer)</div>' : ''}
          <div class="card-body p-2">
            <table class="table table-sm table-dark mb-2" style="font-size:.85rem">${rows}</table>
            <button class="btn btn-sm w-100 ${isRec ? 'btn-success' : 'btn-outline-secondary'}"
              onclick="resolveConflict(${e.id}, [${c.entries.filter(x=>x.id!==e.id).map(x=>x.id).join(',')}], this)">
              <i class="bi bi-check-lg me-1"></i>Garder celle-ci
            </button>
          </div>
        </div>
      </div>`;
  }).join('');

  return `
    <div class="card bg-dark border-warning mb-3">
      <div class="card-header d-flex align-items-center gap-2 py-2">
        ${posterHtml}
        <div class="flex-grow-1">
          <span class="fw-semibold">${_esc(c.entries[0]?.title || '?')}</span>
          <span class="ms-2">${_typeBadge(c.media_type)}</span>
          <span class="text-muted small ms-2">tvdb=${c.tvdb_id}</span>
        </div>
        ${_ignoreBtn(c.key)}
      </div>
      <div class="card-body">
        <div class="row row-cols-1 row-cols-md-${Math.min(c.entries.length, 3)} g-2">${entryCards}</div>
      </div>
    </div>`;
}

// ── Table row helpers ─────────────────────────────────────────────────────────
function _simpleRow(e, actionHtml) {
  return `<tr>
    <td>${_esc(e.title)}</td>
    <td>${_typeBadge(e.media_type)}</td>
    <td>${_esc(e.plex_user || e.plex_user_id || '—')}</td>
    <td>${_srcBadge(e.source)}</td>
    <td>${_statusBadge(e.status)}</td>
    <td class="text-muted small">${_fmtDate(e.requested_at)}</td>
    <td class="text-end">${actionHtml}</td>
  </tr>`;
}

async function loadConflicts() {
  _conflictsInited = true;
  _showSection('conflicts-loading', true);
  ['section-tmdb-conflicts','section-orphaned','section-long-pending','conflicts-empty']
    .forEach(id => _showSection(id, false));

  let data;
  try {
    const r = await fetch('/api/conflicts');
    data = await r.json();
  } catch(e) {
    showToast('Erreur lors du chargement des conflits', 'danger');
    _showSection('conflicts-loading', false);
    return;
  }
  _showSection('conflicts-loading', false);

  const total = (data.tmdb_conflicts?.length||0) + (data.orphaned?.length||0) + (data.long_pending?.length||0);
  const badge = document.getElementById('conflicts-badge');
  badge.textContent = total;
  badge.classList.toggle('d-none', total === 0);

  const btnAuto = document.getElementById('btn-auto-resolve');
  if (btnAuto) btnAuto.classList.toggle('d-none', (data.tmdb_conflicts?.length||0) === 0);

  if (total === 0) { _showSection('conflicts-empty', true); return; }

  // 1. tmdb conflicts
  if (data.tmdb_conflicts?.length) {
    _showSection('section-tmdb-conflicts', true);
    document.getElementById('tmdb-conflicts-list').innerHTML =
      data.tmdb_conflicts.map(_tmdbConflictCard).join('');
  }

  // 2. orphaned
  if (data.orphaned?.length) {
    _showSection('section-orphaned', true);
    document.getElementById('orphaned-body').innerHTML = data.orphaned.map(e => `<tr>
      <td>${_esc(e.title)}</td>
      <td>${_typeBadge(e.media_type)}</td>
      <td><code class="small">${_esc(e.plex_user_id)}</code></td>
      <td>${_statusBadge(e.status)}</td>
      <td class="text-muted small">${_fmtDate(e.requested_at)}</td>
      <td class="text-end">
        <button class="btn btn-xs btn-outline-danger py-0 px-1" onclick="deleteConflictEntry('orphan',${e.id},this)">
          <i class="bi bi-trash"></i>
        </button>
        ${_ignoreBtn(e.key)}
      </td>
    </tr>`).join('');
  }

  // 3. long_pending
  if (data.long_pending?.length) {
    _showSection('section-long-pending', true);
    document.getElementById('long-pending-body').innerHTML = data.long_pending.map(e => `<tr>
      <td>${_esc(e.title)}</td>
      <td>${_typeBadge(e.media_type)}</td>
      <td>${_esc(e.plex_user || '—')}</td>
      <td>${_srcBadge(e.source)}</td>
      <td><span class="badge bg-warning text-dark">${e.age_days}j</span></td>
      <td class="text-end">${_ignoreBtn(e.key)}</td>
    </tr>`).join('');
  }

}

async function resolveConflict(keepId, deleteIds, btn) {
  if (!await confirmAction({
    title: 'Fusionner les doublons',
    body: `Garder l'entrée <strong>#${keepId}</strong> et fusionner <strong>${deleteIds.length}</strong> doublon(s) ?`,
    okLabel: 'Fusionner',
  })) return;
  btn.disabled = true;
  const r = await fetch('/api/conflicts/resolve', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({keep_id: keepId, delete_ids: deleteIds})
  });
  if (r.ok) {
    showToast('Conflit résolu', 'success');
    _conflictsInited = false;
    await loadConflicts();
  } else {
    showToast('Erreur lors de la résolution', 'danger');
    btn.disabled = false;
  }
}

async function autoResolveAll(btn) {
  if (!await confirmAction({
    title: 'Résolution automatique',
    body: 'Résoudre automatiquement tous les conflits tmdb ?<br><span class="text-muted small">L\'entrée Seer est conservée dans chaque cas.</span>',
    okLabel: 'Tout résoudre',
  })) return;
  btn.disabled = true;
  const r = await fetch('/api/conflicts/auto-resolve', {method:'POST'});
  if (r.ok) {
    const d = await r.json();
    showToast(`${d.resolved} conflit(s) résolu(s)`, 'success');
    _conflictsInited = false;
    await loadConflicts();
  } else {
    showToast('Erreur lors de la résolution automatique', 'danger');
  }
  btn.disabled = false;
}

async function deleteConflictEntry(type, id, btn) {
  const labels = {'no-tmdb': 'sans tmdb_id', 'orphan': 'orpheline'};
  if (!await confirmAction({
    title: 'Supprimer l\'entrée',
    body: `Supprimer cette demande ${labels[type]||''} ?`,
    okLabel: 'Supprimer', danger: true,
  })) return;
  btn.disabled = true;
  const url = type === 'no-tmdb' ? `/api/conflicts/no-tmdb/${id}` : `/api/conflicts/orphan/${id}`;
  const r = await fetch(url, {method:'DELETE'});
  if (r.ok) {
    showToast('Entrée supprimée', 'success');
    _conflictsInited = false;
    await loadConflicts();
  } else {
    showToast('Erreur lors de la suppression', 'danger');
    btn.disabled = false;
  }
}

async function ignoreConflict(key, btn) {
  btn.disabled = true;
  const r = await fetch('/api/conflicts/ignore', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({key})
  });
  if (r.ok) {
    showToast('Conflit ignoré', 'secondary');
    _conflictsInited = false;
    await loadConflicts();
  } else {
    btn.disabled = false;
  }
}

// Précharge le badge au chargement de la page
(async () => {
  try {
    const r = await fetch('/api/conflicts');
    const d = await r.json();
    const n = (d.tmdb_conflicts?.length||0) + (d.orphaned?.length||0) + (d.long_pending?.length||0);
    if (n > 0) {
      const b = document.getElementById('conflicts-badge');
      b.textContent = n;
      b.classList.remove('d-none');
    }
  } catch {}
})();

// ── Maintenance tab ────────────────────────────────────────────────────────────

const MAINT_GROUPS = [
  { title:'Utilisateurs', icon:'bi-people',
    actions:['discover-users','seer-sync-users'] },
  { title:'Demandes',     icon:'bi-film',
    actions:['seer-sync-requests','retry-failed','recalculate-dates','merge-duplicates','enrich-and-merge'] },
  { title:'Système',      icon:'bi-heart-pulse',
    actions:['check-arr-statuses','health-check'] },
];

let _maintMeta   = {};      // action → méta
let _activeRuns  = {};      // action → { run_id, interval }
let _tabInited   = false;

async function initMaintenanceTab() {
  if (_tabInited) return;
  _tabInited = true;
  try {
    const r = await fetch('/api/maintenance/actions');
    _maintMeta = await r.json();
  } catch(e) { console.error('maintenance meta:', e); return; }
  _renderGrid();
}

function _renderGrid() {
  const grid = document.getElementById('maint-grid');
  grid.innerHTML = '';

  for (const group of MAINT_GROUPS) {
    const actions = group.actions.filter(a => _maintMeta[a]);
    if (!actions.length) continue;

    const header = document.createElement('div');
    header.className = 'col-12 mt-2';
    header.innerHTML = `<h6 class="text-muted text-uppercase mb-2" style="font-size:11px;letter-spacing:.08em">
      <i class="bi ${group.icon} me-1"></i>${group.title}</h6>`;
    grid.appendChild(header);

    for (const action of actions) {
      const meta  = _maintMeta[action];
      const col   = document.createElement('div');
      col.className = 'col-md-6 col-xl-4';
      col.innerHTML = _cardHtml(action, meta);
      grid.appendChild(col);
    }
  }
}

function _cardHtml(action, meta) {
  const c = MAINT_COLORS[meta.color] || MAINT_COLORS.secondary;
  const lr = meta.last_run;
  let lastRunHtml = '';
  if (lr) {
    const dt = lr.finished_at ? new Date(lr.finished_at).toLocaleString('fr-FR') : '—';
    const icon = lr.status === 'done' ? 'bi-check-circle-fill text-success'
               : lr.status === 'error' ? 'bi-x-circle-fill text-danger'
               : 'bi-hourglass-split text-warning';
    lastRunHtml = `<div class="text-muted d-flex align-items-center gap-1" style="font-size:10px">
      <i class="bi ${icon}"></i><span>Dernier : ${dt}</span>
    </div>`;
  }
  return `
<div class="maint-card p-3 h-100 d-flex flex-column gap-2" id="mcard-${action}"
     style="border-color:${c.border}">
  <div class="d-flex align-items-start justify-content-between gap-2">
    <div>
      <div class="fw-semibold d-flex align-items-center gap-2">
        <i class="bi ${meta.icon} ${c.label}"></i>${meta.label}
      </div>
      <div class="text-muted mt-1" style="font-size:12px">${meta.description}</div>
      ${lastRunHtml}
    </div>
    <span class="badge rounded-pill bg-secondary" id="mstatus-${action}" style="white-space:nowrap;font-size:10px">—</span>
  </div>

  <div class="progress" style="height:4px;background:var(--pr-surface-2);border-radius:2px">
    <div class="progress-bar" id="mprog-${action}" role="progressbar"
         style="width:0%;transition:width .4s;background:${c.border.replace('55','cc')}"></div>
  </div>

  <div id="mlogs-wrap-${action}" style="display:none">
    <div class="maint-log" id="mlogs-${action}"></div>
  </div>

  <div class="d-flex justify-content-between align-items-center mt-auto pt-1">
    <button class="btn btn-sm btn-outline-secondary" style="font-size:11px"
            onclick="toggleLogs('${action}')">
      <i class="bi bi-terminal me-1"></i><span id="mlogtoggle-${action}">Logs</span>
    </button>
    <button class="btn btn-sm btn-outline-${meta.color === 'secondary' ? 'light' : meta.color}"
            id="mbtn-${action}" onclick="launchMaint('${action}')">
      <i class="bi bi-play-fill me-1"></i>Lancer
    </button>
  </div>
</div>`;
}

function toggleLogs(action) {
  const wrap   = document.getElementById(`mlogs-wrap-${action}`);
  const toggle = document.getElementById(`mlogtoggle-${action}`);
  const open   = wrap.style.display === 'none';
  wrap.style.display = open ? '' : 'none';
  toggle.textContent = open ? 'Masquer' : 'Logs';
  if (open) _scrollLogs(action);
}

function _scrollLogs(action) {
  const el = document.getElementById(`mlogs-${action}`);
  if (el) el.scrollTop = el.scrollHeight;
}

function _renderLogs(action, logs) {
  const el = document.getElementById(`mlogs-${action}`);
  if (!el) return;
  el.innerHTML = logs.map(line => {
    if (line.startsWith('[OK]'))   return `<div class="log-ok">${_esc(line)}</div>`;
    if (line.startsWith('[WARN]')) return `<div class="log-warn">${_esc(line)}</div>`;
    if (line.startsWith('[ERR]'))  return `<div class="log-err">${_esc(line)}</div>`;
    return `<div class="log-info">${_esc(line)}</div>`;
  }).join('');
  _scrollLogs(action);
}

function _esc(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

async function launchMaint(action) {
  if (_activeRuns[action]) return;

  const btn    = document.getElementById(`mbtn-${action}`);
  const card   = document.getElementById(`mcard-${action}`);
  const status = document.getElementById(`mstatus-${action}`);
  const prog   = document.getElementById(`mprog-${action}`);
  const wrap   = document.getElementById(`mlogs-wrap-${action}`);
  const toggle = document.getElementById(`mlogtoggle-${action}`);

  // Ouvrir les logs automatiquement au lancement
  wrap.style.display = '';
  toggle.textContent = 'Masquer';
  document.getElementById(`mlogs-${action}`).innerHTML = '';

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
  card.classList.add('running');
  status.className = 'badge rounded-pill bg-primary';
  status.textContent = 'En cours…';
  prog.style.width = '2%';

  try {
    const r = await fetch(`/api/maintenance/run/${action}`, { method: 'POST' });
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    const { run_id } = await r.json();

    _activeRuns[action] = setInterval(async () => {
      try {
        const rs = await fetch(`/api/maintenance/run/${run_id}`);
        const data = await rs.json();

        prog.style.width = data.progress + '%';
        _renderLogs(action, data.logs);

        if (data.status !== 'running') {
          clearInterval(_activeRuns[action]);
          delete _activeRuns[action];

          const ok = data.status === 'done';
          card.classList.remove('running');
          card.classList.add(ok ? 'done' : 'error');
          status.className = `badge rounded-pill ${ok ? 'bg-success' : 'bg-danger'}`;
          const dur = data.finished_at
            ? Math.round((new Date(data.finished_at) - new Date(data.started_at)) / 1000)
            : '?';
          status.textContent = ok ? `OK · ${dur}s` : `Erreur · ${dur}s`;
          prog.style.width = '100%';

          btn.disabled = false;
          const meta = _maintMeta[action];
          btn.innerHTML = `<i class="bi bi-play-fill me-1"></i>Relancer`;
        }
      } catch(e) {
        clearInterval(_activeRuns[action]);
        delete _activeRuns[action];
        status.className = 'badge rounded-pill bg-danger';
        status.textContent = 'Erreur réseau';
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Relancer';
      }
    }, 500);

  } catch(e) {
    card.classList.remove('running');
    status.className = 'badge rounded-pill bg-danger';
    status.textContent = 'Erreur';
    prog.style.width = '0%';
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Lancer';
    showToast('Erreur : ' + e.message, 'danger');
  }
}

// ── Instances Arr Management ──────────────────────────────────────────────────
let _arrInstances = [];

async function loadArrInstances() {
  const tbody = document.getElementById('arr-instances-body');
  try {
    const r = await fetch('/api/arr-instances');
    _arrInstances = await r.json();
    if (!_arrInstances.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-3">Aucune instance configurée. Cliquez sur "Ajouter une instance".</td></tr>';
      return;
    }
    tbody.innerHTML = _arrInstances.map(inst => {
      const typeBadge = inst.arr_type === 'sonarr' 
        ? '<span class="badge bg-info text-dark"><i class="bi bi-tv me-1"></i>Sonarr</span>'
        : inst.arr_type === 'radarr'
        ? '<span class="badge bg-primary"><i class="bi bi-camera-video me-1"></i>Radarr</span>'
        : '<span class="badge text-white" style="background:#6f42c1"><i class="bi bi-search me-1"></i>Prowlarr</span>';
      
      const defaultBadge = inst.is_default
        ? '<span class="badge bg-success"><i class="bi bi-check-circle-fill me-1"></i>Défaut</span>'
        : '<span class="text-muted">—</span>';
        
      const statusBadge = inst.enabled
        ? '<span class="badge bg-success">Actif</span>'
        : '<span class="badge bg-secondary">Désactivé</span>';
      const rootFolder = (inst.arr_type === 'sonarr' || inst.arr_type === 'radarr') && inst.root_folder
        ? `<code class="small text-muted">${_esc(inst.root_folder)}</code>${inst.is_default ? ' <span class="badge bg-secondary ms-1">Dossier par défaut</span>' : ''}`
        : '<span class="text-muted">—</span>';

      return `<tr>
        <td><strong>${_esc(inst.name)}</strong></td>
        <td>${typeBadge}</td>
        <td><code class="small text-muted">${_esc(inst.url)}</code></td>
        <td>${rootFolder}</td>
        <td>${defaultBadge}</td>
        <td>${statusBadge}</td>
        <td class="text-end">
          <button type="button" class="btn btn-xs btn-outline-warning py-0 px-2" onclick="testExistingInstConn(${inst.id}, this)"><i class="bi bi-plug"></i> Tester</button>
          <button type="button" class="btn btn-xs btn-outline-secondary py-0 px-2" onclick="editArrInstance(${inst.id})"><i class="bi bi-pencil"></i></button>
          <button type="button" class="btn btn-xs btn-outline-danger py-0 px-2" onclick="deleteArrInstance(${inst.id})"><i class="bi bi-trash"></i></button>
        </td>
      </tr>`;
    }).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-danger py-3">Erreur lors du chargement : ${e.message}</td></tr>`;
  }
  try { refreshConnHub(); } catch (e) {}
}

function openArrInstanceModal() {
  document.getElementById('instId').value = '';
  document.getElementById('arrInstanceModalTitle').textContent = 'Ajouter une instance';
  document.getElementById('instName').value = '';
  document.getElementById('instType').value = _arrPreferredType || 'sonarr';
  _arrPreferredType = null;
  document.getElementById('instUrl').value = '';
  document.getElementById('instApiKey').value = '';
  document.getElementById('instQualityProfile').innerHTML = '<option value="">Sélectionnez un profil (chargez d\'abord)</option>';
  document.getElementById('instRootFolder').innerHTML = '<option value="">Sélectionnez un dossier (chargez d\'abord)</option>';
  document.getElementById('instMinAvailability').value = 'released';
  document.getElementById('instIndexers').innerHTML = '';
  document.getElementById('instEnabled').checked = true;
  document.getElementById('instIsDefault').checked = false;

  // Divulgation progressive : on masque l'étape 2 tant que la connexion n'est pas validée.
  document.getElementById('instStep2').style.display = 'none';
  document.getElementById('instTestStatus').innerHTML = '';

  onInstTypeChange();

  new bootstrap.Modal(document.getElementById('arrInstanceModal')).show();
}

function onInstTypeChange() {
  const type = document.getElementById('instType').value;
  
  // Show/Hide specific fields
  document.querySelectorAll('.arr-only').forEach(el => el.style.display = (type === 'sonarr' || type === 'radarr') ? '' : 'none');
  document.querySelectorAll('.radarr-only').forEach(el => el.style.display = (type === 'radarr') ? '' : 'none');
  document.querySelectorAll('.prowlarr-only').forEach(el => el.style.display = (type === 'prowlarr') ? '' : 'none');
}

async function fetchInstProfiles(selectedId = null) {
  const type = document.getElementById('instType').value;
  const url = document.getElementById('instUrl').value.trim();
  const apiKey = document.getElementById('instApiKey').value.trim();
  if (!url || !apiKey) {
    return showToast("Veuillez renseigner l'URL et la clé API d'abord.", "warning");
  }
  
  const sel = document.getElementById('instQualityProfile');
  sel.innerHTML = '<option value="">Chargement...</option>';
  
  try {
    const r = await fetch(`/api/${type}/profiles?url=${encodeURIComponent(url)}&api_key=${encodeURIComponent(apiKey)}`);
    if (!r.ok) throw new Error("Erreur serveur");
    const profiles = await r.json();
    sel.innerHTML = profiles.map(p => 
      `<option value="${p.id}" ${String(p.id) === String(selectedId) ? 'selected' : ''}>${p.name}</option>`
    ).join('');
    showToast("Profils chargés !", "success");
  } catch (e) {
    sel.innerHTML = '<option value="">Erreur de chargement</option>';
    showToast("Impossible de charger les profils : " + e.message, "danger");
  }
}

async function fetchInstFolders(selectedValue = null) {
  const type = document.getElementById('instType').value;
  const url = document.getElementById('instUrl').value.trim();
  const apiKey = document.getElementById('instApiKey').value.trim();
  if (!url || !apiKey) {
    return showToast("Veuillez renseigner l'URL et la clé API d'abord.", "warning");
  }
  
  const sel = document.getElementById('instRootFolder');
  sel.innerHTML = '<option value="">Chargement...</option>';
  
  try {
    const r = await fetch(`/api/${type}/folders?url=${encodeURIComponent(url)}&api_key=${encodeURIComponent(apiKey)}`);
    if (!r.ok) throw new Error("Erreur serveur");
    const folders = await r.json();
    sel.innerHTML = folders.map(f => {
      const path = arrFolderPath(f);
      return `<option value="${_esc(path)}" ${path === selectedValue ? 'selected' : ''}>${_esc(arrFolderLabel(f, selectedValue))}</option>`;
    }).join('');
    showToast("Dossiers chargés !", "success");
  } catch (e) {
    sel.innerHTML = '<option value="">Erreur de chargement</option>';
    showToast("Impossible de charger les dossiers : " + e.message, "danger");
  }
}

async function fetchProwlarrIndexers(selectedIds = []) {
  const url = document.getElementById('instUrl').value.trim();
  const apiKey = document.getElementById('instApiKey').value.trim();
  if (!url || !apiKey) {
    return showToast("Veuillez renseigner l'URL et la clé API d'abord.", "warning");
  }
  
  const sel = document.getElementById('instIndexers');
  sel.innerHTML = '<option value="">Chargement...</option>';
  
  try {
    const r = await fetch(`/api/prowlarr/indexers?url=${encodeURIComponent(url)}&api_key=${encodeURIComponent(apiKey)}`);
    if (!r.ok) throw new Error("Erreur serveur");
    const indexers = await r.json();
    sel.innerHTML = indexers.map(idx => {
      const isSel = selectedIds.includes(parseInt(idx.id)) || selectedIds.includes(String(idx.id));
      return `<option value="${idx.id}" ${isSel ? 'selected' : ''}>${_esc(idx.name)}</option>`;
    }).join('');
    showToast("Indexeurs chargés !", "success");
  } catch (e) {
    sel.innerHTML = '<option value="">Erreur de chargement</option>';
    showToast("Impossible de charger les indexeurs : " + e.message, "danger");
  }
}

// Révèle l'étape 2 du modal et charge les options adaptées au type d'instance.
function revealInstStep2(type) {
  document.getElementById('instStep2').style.display = '';
  onInstTypeChange();
  if (type === 'sonarr' || type === 'radarr') {
    fetchInstProfiles(document.getElementById('instQualityProfile').value || null);
    fetchInstFolders(document.getElementById('instRootFolder').value || null);
  } else if (type === 'prowlarr') {
    fetchProwlarrIndexers();
  }
}

async function testInstConn() {
  const type = document.getElementById('instType').value;
  const url = document.getElementById('instUrl').value.trim();
  const apiKey = document.getElementById('instApiKey').value.trim();
  const status = document.getElementById('instTestStatus');
  if (!url || !apiKey) {
    status.innerHTML = '<span class="text-warning"><i class="bi bi-exclamation-triangle me-1"></i>URL et clé API requises.</span>';
    return;
  }
  const btn = document.getElementById('instTestBtn');
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Test…';
  try {
    const r = await fetch('/api/test/arr-instance', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url, api_key: apiKey, arr_type: type})
    });
    const d = await r.json();
    if (d.success) {
      status.innerHTML = `<span class="text-success"><i class="bi bi-check-circle-fill me-1"></i>${_esc(d.message || 'Connecté')}</span>`;
      revealInstStep2(type);
    } else {
      status.innerHTML = `<span class="text-danger"><i class="bi bi-x-circle me-1"></i>${_esc(d.message || 'Échec de connexion')}</span>`;
    }
  } catch (e) {
    status.innerHTML = `<span class="text-danger"><i class="bi bi-x-circle me-1"></i>Erreur : ${_esc(e.message)}</span>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

async function testExistingInstConn(id, btn) {
  const inst = _arrInstances.find(x => x.id === id);
  if (!inst) return;
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
  const start = performance.now();
  try {
    const r = await fetch('/api/test/arr-instance', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: inst.url, api_key: inst.api_key, arr_type: inst.arr_type})
    });
    const duration = Math.round(performance.now() - start);
    const d = await r.json();
    if (d.success) {
      showToast(`${d.message || "Connexion réussie"} (${duration} ms)`, "success");
    } else {
      showToast(d.message || "Échec de connexion", "danger");
    }
  } catch (e) {
    showToast("Erreur : " + e.message, "danger");
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

function editArrInstance(id) {
  const inst = _arrInstances.find(x => x.id === id);
  if (!inst) return;
  
  document.getElementById('instId').value = inst.id;
  document.getElementById('arrInstanceModalTitle').textContent = 'Modifier l\'instance';
  document.getElementById('instName').value = inst.name;
  document.getElementById('instType').value = inst.arr_type;
  document.getElementById('instUrl').value = inst.url;
  document.getElementById('instApiKey').value = inst.api_key;
  
  onInstTypeChange();
  
  if (inst.arr_type === 'sonarr' || inst.arr_type === 'radarr') {
    document.getElementById('instQualityProfile').innerHTML = inst.quality_profile_id 
      ? `<option value="${inst.quality_profile_id}" selected>ID ${inst.quality_profile_id}</option>`
      : '<option value="">Sélectionnez un profil</option>';
    document.getElementById('instRootFolder').innerHTML = inst.root_folder
      ? `<option value="${inst.root_folder}" selected>${inst.root_folder}</option>`
      : '<option value="">Sélectionnez un dossier</option>';
      
    fetchInstProfiles(inst.quality_profile_id);
    fetchInstFolders(inst.root_folder);
  }
  
  if (inst.arr_type === 'radarr') {
    document.getElementById('instMinAvailability').value = inst.minimum_availability || 'released';
  }
  
  if (inst.arr_type === 'prowlarr') {
    let indexerIds = [];
    try {
      if (inst.indexer_ids) {
        indexerIds = JSON.parse(inst.indexer_ids);
      }
    } catch(e) {}
    fetchProwlarrIndexers(indexerIds);
  }
  
  document.getElementById('instEnabled').checked = inst.enabled;
  document.getElementById('instIsDefault').checked = inst.is_default;

  // Édition : les valeurs existent déjà, on affiche directement l'étape 2.
  document.getElementById('instStep2').style.display = '';
  document.getElementById('instTestStatus').innerHTML =
    '<span class="text-muted"><i class="bi bi-info-circle me-1"></i>Instance existante — testez à nouveau si vous changez l\'URL ou la clé.</span>';

  new bootstrap.Modal(document.getElementById('arrInstanceModal')).show();
}

async function deleteArrInstance(id) {
  if (!confirm("Supprimer définitivement cette instance ?")) return;
  try {
    const r = await fetch(`/api/arr-instances/${id}`, {method: 'DELETE'});
    if (!r.ok) throw new Error("Erreur de suppression");
    showToast("Instance supprimée", "success");
    loadArrInstances();
  } catch (e) {
    showToast("Erreur : " + e.message, "danger");
  }
}

async function saveArrInstance() {
  const id = document.getElementById('instId').value;
  const name = document.getElementById('instName').value.trim();
  const type = document.getElementById('instType').value;
  const url = document.getElementById('instUrl').value.trim();
  const apiKey = document.getElementById('instApiKey').value.trim();
  const enabled = document.getElementById('instEnabled').checked;
  const isDefault = document.getElementById('instIsDefault').checked;
  
  if (!name || !url || !apiKey) {
    return showToast("Veuillez remplir tous les champs obligatoires (Nom, URL, Clé API)", "danger");
  }
  
  const payload = {
    name,
    arr_type: type,
    url,
    api_key: apiKey,
    enabled,
    is_default: isDefault,
    quality_profile_id: null,
    root_folder: null,
    minimum_availability: "released",
    indexer_ids: null
  };
  
  if (type === 'sonarr' || type === 'radarr') {
    payload.quality_profile_id = parseInt(document.getElementById('instQualityProfile').value) || null;
    payload.root_folder = document.getElementById('instRootFolder').value || null;
  }
  if (type === 'radarr') {
    payload.minimum_availability = document.getElementById('instMinAvailability').value;
  }
  if (type === 'prowlarr') {
    const select = document.getElementById('instIndexers');
    const selected = [...select.selectedOptions].map(o => parseInt(o.value));
    payload.indexer_ids = selected.length ? JSON.stringify(selected) : null;
  }
  
  const apiPath = id ? `/api/arr-instances/${id}` : '/api/arr-instances';
  const method = id ? 'PUT' : 'POST';
  
  try {
    const r = await fetch(apiPath, {
      method,
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    if (!r.ok) throw new Error(await r.text());
    showToast("Instance enregistrée !", "success");
    bootstrap.Modal.getInstance(document.getElementById('arrInstanceModal')).hide();
    loadArrInstances();
  } catch (e) {
    showToast("Erreur lors de la sauvegarde : " + e.message, "danger");
  }
}

// ── Download Clients Management ──────────────────────────────────────────────
let _downloadClients = [];

async function loadDownloadClients() {
  const tbody = document.getElementById('dl-clients-body');
  try {
    const r = await fetch('/api/download-clients');
    _downloadClients = await r.json();
    if (!_downloadClients.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-3">Aucun client configuré. Cliquez sur "Ajouter".</td></tr>';
      return;
    }
    tbody.innerHTML = _downloadClients.map(client => {
      const typeBadge = client.client_type === 'qbittorrent'
        ? '<span class="badge bg-info text-dark"><i class="bi bi-download me-1"></i>qBittorrent</span>'
        : client.client_type === 'transmission'
        ? '<span class="badge bg-primary"><i class="bi bi-download me-1"></i>Transmission</span>'
        : '<span class="badge bg-secondary"><i class="bi bi-folder me-1"></i>Watch Folder</span>';

      const defaultBadge = client.is_default
        ? `<span class="badge ${client.enabled ? 'bg-success' : 'bg-secondary'}"><i class="bi bi-check-circle-fill me-1"></i>Défaut</span>`
        : '<span class="text-muted">—</span>';

      const toggle = `<div class="form-check form-switch mb-0">
        <input class="form-check-input" type="checkbox" ${client.enabled ? 'checked' : ''} onchange="toggleDownloadClient(${client.id}, this)" title="${client.enabled ? 'Désactiver' : 'Activer'}">
      </div>`;

      return `<tr class="${client.enabled ? '' : 'opacity-50'}">
        <td><strong>${_esc(client.name)}</strong></td>
        <td>${typeBadge}</td>
        <td><code class="small text-muted">${_esc(client.url)}</code></td>
        <td class="text-muted small">${_esc(client.category || '—')}</td>
        <td>${defaultBadge}</td>
        <td>${toggle}</td>
        <td class="text-end">
          <button type="button" class="btn btn-xs btn-outline-warning py-0 px-2" onclick="testExistingDlClientConn(${client.id}, this)" ${client.enabled ? '' : 'disabled'}><i class="bi bi-plug"></i> Tester</button>
          <button type="button" class="btn btn-xs btn-outline-secondary py-0 px-2" onclick="editDownloadClient(${client.id})"><i class="bi bi-pencil"></i></button>
          <button type="button" class="btn btn-xs btn-outline-danger py-0 px-2" onclick="deleteDownloadClient(${client.id})"><i class="bi bi-trash"></i></button>
        </td>
      </tr>`;
    }).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-danger py-3">Erreur lors du chargement : ${e.message}</td></tr>`;
  }
  try { refreshConnHub(); } catch (e) {}
}

function openDlClientModal() {
  document.getElementById('dlClientId').value = '';
  document.getElementById('dlClientModalTitle').textContent = 'Ajouter un client de téléchargement';
  document.getElementById('dlClientName').value = '';
  document.getElementById('dlClientType').value = 'qbittorrent';
  document.getElementById('dlClientUrl').value = '';
  document.getElementById('dlClientUser').value = '';
  document.getElementById('dlClientPass').value = '';
  document.getElementById('dlClientCategory').value = '';
  document.getElementById('dlClientTags').value = '';
  document.getElementById('dlClientEnabled').checked = true;
  document.getElementById('dlClientIsDefault').checked = false;

  onDlClientTypeChange();

  new bootstrap.Modal(document.getElementById('dlClientModal')).show();
}

function onDlClientTypeChange() {
  const type = document.getElementById('dlClientType').value;
  document.querySelectorAll('.qbit-only').forEach(el => el.style.display = (type === 'qbittorrent') ? '' : 'none');
  
  const urlLabel = document.getElementById('dlClientUrlLabel');
  const urlInput = document.getElementById('dlClientUrl');
  
  if (type === 'watch_folder') {
    if (urlLabel) urlLabel.textContent = "Chemin absolu du dossier local (Watch Folder)";
    urlInput.placeholder = "ex: C:\\Plex\\WatchFolder ou /mnt/watchfolder";
    urlInput.type = "text";
    document.querySelectorAll('.credentials-only').forEach(el => el.style.display = 'none');
  } else {
    if (urlLabel) urlLabel.textContent = "URL de l'interface Web / API";
    urlInput.placeholder = "http://192.168.1.10:8080";
    urlInput.type = "url";
    document.querySelectorAll('.credentials-only').forEach(el => el.style.display = '');
  }
}

async function testDlClientConn() {
  const type = document.getElementById('dlClientType').value;
  const url = document.getElementById('dlClientUrl').value.trim();
  const username = document.getElementById('dlClientUser').value.trim();
  const password = document.getElementById('dlClientPass').value.trim();

  if (!url) {
    return showToast(type === 'watch_folder' ? "Le chemin est requis" : "L'URL est requise", "warning");
  }

  showToast("Test de connexion...", "secondary");
  try {
    const r = await fetch('/api/test/download-client', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({client_type: type, url, username, password})
    });
    const d = await r.json();
    if (d.success) {
      showToast(d.message || "Connexion réussie !", "success");
    } else {
      showToast(d.message || "Échec de connexion", "danger");
    }
  } catch (e) {
    showToast("Erreur : " + e.message, "danger");
  }
}

async function testExistingDlClientConn(id, btn) {
  const client = _downloadClients.find(x => x.id === id);
  if (!client) return;
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
  const start = performance.now();
  try {
    const r = await fetch('/api/test/download-client', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({client_type: client.client_type, url: client.url, username: client.username, password: client.password})
    });
    const duration = Math.round(performance.now() - start);
    const d = await r.json();
    if (d.success) {
      showToast(`${d.message || "Connexion réussie"} (${duration} ms)`, "success");
    } else {
      showToast(d.message || "Échec de connexion", "danger");
    }
  } catch (e) {
    showToast("Erreur : " + e.message, "danger");
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

function editDownloadClient(id) {
  const client = _downloadClients.find(x => x.id === id);
  if (!client) return;

  document.getElementById('dlClientId').value = client.id;
  document.getElementById('dlClientModalTitle').textContent = 'Modifier le client';
  document.getElementById('dlClientName').value = client.name;
  document.getElementById('dlClientType').value = client.client_type;
  document.getElementById('dlClientUrl').value = client.url;
  document.getElementById('dlClientUser').value = client.username || '';
  document.getElementById('dlClientPass').value = client.password || '';
  document.getElementById('dlClientCategory').value = client.category || '';
  document.getElementById('dlClientTags').value = client.tags || '';
  document.getElementById('dlClientEnabled').checked = client.enabled;
  document.getElementById('dlClientIsDefault').checked = client.is_default;

  onDlClientTypeChange();

  new bootstrap.Modal(document.getElementById('dlClientModal')).show();
}

async function toggleDownloadClient(id, checkbox) {
  try {
    const r = await fetch(`/api/download-clients/${id}/toggle`, {method: 'PATCH'});
    if (!r.ok) throw new Error();
    const d = await r.json();
    showToast(d.enabled ? 'Client activé' : 'Client désactivé', 'success');
    loadDownloadClients();
  } catch {
    showToast('Erreur lors du changement de statut', 'danger');
    checkbox.checked = !checkbox.checked;
  }
}

async function deleteDownloadClient(id) {
  if (!confirm("Supprimer définitivement ce client de téléchargement ?")) return;
  try {
    const r = await fetch(`/api/download-clients/${id}`, {method: 'DELETE'});
    if (!r.ok) throw new Error("Erreur de suppression");
    showToast("Client supprimé", "success");
    loadDownloadClients();
  } catch (e) {
    showToast("Erreur : " + e.message, "danger");
  }
}

async function saveDownloadClient() {
  const id = document.getElementById('dlClientId').value;
  const name = document.getElementById('dlClientName').value.trim();
  const type = document.getElementById('dlClientType').value;
  const url = document.getElementById('dlClientUrl').value.trim();
  const username = document.getElementById('dlClientUser').value.trim();
  const password = document.getElementById('dlClientPass').value.trim();
  const category = document.getElementById('dlClientCategory').value.trim();
  const tags = document.getElementById('dlClientTags').value.trim();
  const enabled = document.getElementById('dlClientEnabled').checked;
  const isDefault = document.getElementById('dlClientIsDefault').checked;

  if (!name || !url) {
    return showToast("Veuillez remplir les champs obligatoires (Nom, URL)", "danger");
  }

  const payload = {
    name,
    client_type: type,
    url,
    username: username || null,
    password: password || null,
    category: category || null,
    tags: tags || null,
    enabled,
    is_default: isDefault
  };

  const apiPath = id ? `/api/download-clients/${id}` : '/api/download-clients';
  const method = id ? 'PUT' : 'POST';

  try {
    const r = await fetch(apiPath, {
      method,
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    if (!r.ok) throw new Error(await r.text());
    showToast("Client de téléchargement enregistré !", "success");
    bootstrap.Modal.getInstance(document.getElementById('dlClientModal')).hide();
    loadDownloadClients();
  } catch (e) {
    showToast("Erreur lors de la sauvegarde : " + e.message, "danger");
  }
}

// ── Sticky save bar : masquer sur l'onglet Templates ─────────────────────────
document.querySelectorAll('#settingsTabs button[data-bs-toggle="tab"]').forEach(btn => {
  btn.addEventListener('shown.bs.tab', () => {
    const isTemplates = btn.getAttribute('data-bs-target') === '#tab-templates';
    document.getElementById('sticky-save-bar').style.display = isTemplates ? 'none' : '';
  });
});



// ── Templates tab ─────────────────────────────────────────────────────────────
let tmplCurrentTab = 'request';
let tmplPreviewTimer = null;
const tmplEditors = {};
let tmplEditorsReady = false;
const tmplTypes = [
  'request',
  'available',
  'available_vf',
  'available_vo_tracking',
  'vf_available',
  'language_episode',
  'language_season_start',
  'language_season_complete',
  'language_series_complete',
  'failed'
];


// ── Variables contextuelles ─────────────────────────────────────────────────
const TMPL_CORE_VARS = ['title', 'year', 'poster_url', 'plex_user'];
const tmplVarGroups = [
  { label: 'Contenu', vars: [
    { n: 'title', d: 'Titre du film ou de la série' },
    { n: 'year', d: 'Année de sortie' },
    { n: 'poster_url', d: "URL de l'affiche" },
    { n: 'overview', d: 'Synopsis' },
    { n: 'genres', d: 'Genres (ex : Action, Drame)' },
    { n: 'media_type_label', d: 'Film ou Série' },
    { n: 'media_type_label_cap', d: 'Le film / La série' }
  ]},
  { label: 'Utilisateur', vars: [
    { n: 'plex_user', d: "Nom de l'utilisateur" }
  ]},
  { label: 'Suivi VF / VO', vars: [
    { n: 'language', d: 'Langue du jalon (VF ou VO)' },
    { n: 'language_reason', d: 'Détail du jalon (ex : VF saison 1 complète)' }
  ]},
  { label: 'Échec', vars: [
    { n: 'reason', d: "Raison de l'échec" }
  ]}
];
const tmplVarRelevance = {
  request:               TMPL_CORE_VARS.concat(['media_type_label', 'media_type_label_cap', 'overview', 'genres']),
  available:             TMPL_CORE_VARS.concat(['media_type_label_cap', 'genres']),
  available_vf:          TMPL_CORE_VARS.concat(['media_type_label_cap']),
  available_vo_tracking: TMPL_CORE_VARS.concat(['media_type_label_cap']),
  vf_available:          TMPL_CORE_VARS.concat(['media_type_label_cap', 'language_reason']),
  language_episode:         TMPL_CORE_VARS.concat(['language', 'language_reason', 'overview']),
  language_season_start:    TMPL_CORE_VARS.concat(['language', 'language_reason', 'overview']),
  language_season_complete: TMPL_CORE_VARS.concat(['language', 'language_reason', 'overview']),
  language_series_complete: TMPL_CORE_VARS.concat(['language', 'language_reason', 'overview']),
  failed:                TMPL_CORE_VARS.concat(['media_type_label', 'reason'])
};

function tmplToggleVars() {
  const body = document.getElementById('tmpl-vars-body');
  const chev = document.getElementById('tmpl-vars-chevron');
  const hidden = body.style.display === 'none';
  body.style.display = hidden ? '' : 'none';
  chev.className = hidden ? 'bi bi-chevron-up' : 'bi bi-chevron-down';
}

function tmplRenderVars() {
  const wrap = document.getElementById('tmpl-vars-groups');
  if (!wrap) return;
  const relevant = tmplVarRelevance[tmplCurrentTab] || TMPL_CORE_VARS;
  const subjEl = document.getElementById('tmpl-subject-' + tmplCurrentTab);
  const haystack = tmplGetValue(tmplCurrentTab) + ' ' + (subjEl ? subjEl.value : '');
  let html = '';
  tmplVarGroups.forEach(function (g) {
    const chips = g.vars.map(function (v) {
      const used = new RegExp('\\b' + v.n + '\\b').test(haystack);
      const na = relevant.indexOf(v.n) === -1;
      const cls = 'tmpl-var' + (used ? ' used' : '') + (na ? ' na' : '');
      const title = (na ? v.d + " — non utilisée pour ce type d'email" : v.d).replace(/"/g, '&quot;');
      const token = '{{ ' + v.n + ' }}';
      return '<span class="' + cls + '" title="' + title + '" onclick="tmplInsertVar(event, \'' + token + '\')">' + token + '<i class="bi bi-check2 tmpl-var-check"></i></span>';
    }).join('');
    html += '<div class="tmpl-var-group"><div class="tmpl-var-group-label">' + g.label + '</div><div class="d-flex flex-wrap gap-2">' + chips + '</div></div>';
  });
  wrap.innerHTML = html;
}

function tmplOnEdit() {
  tmplRenderVars();
  tmplSchedulePreview();
}


function onTemplatesTabShow() {
  if (tmplEditorsReady) {
    Object.values(tmplEditors).forEach(cm => cm.refresh());
    tmplRenderVars();
    tmplLivePreview();
    return;
  }
  tmplEditorsReady = true;
  tmplTypes.forEach(type => {
    const el = document.getElementById('tmpl-editor-' + type);
    tmplEditors[type] = CodeMirror.fromTextArea(el, {
      mode: 'htmlmixed', theme: 'monokai', lineNumbers: true, lineWrapping: true, tabSize: 2,
    });
    tmplEditors[type].on('change', () => tmplOnEdit());
  });
  tmplRenderVars();
  setTimeout(tmplLivePreview, 200);
}

function tmplGetValue(type) {
  return tmplEditors[type] ? tmplEditors[type].getValue() : '';
}

function tmplSwitchTab(tab) {
  tmplCurrentTab = tab;
  tmplTypes.forEach(t => {
    document.getElementById('tmpl-container-' + t).style.display = t === tab ? '' : 'none';
    document.getElementById('tmpl-subject-group-' + t).style.display = t === tab ? '' : 'none';
    document.getElementById('tmpl-tab-' + t).classList.toggle('active', t === tab);
  });
  if (tmplEditors[tab]) tmplEditors[tab].refresh();
  tmplRenderVars();
  tmplLivePreview();
}

function tmplSchedulePreview() {
  clearTimeout(tmplPreviewTimer);
  tmplPreviewTimer = setTimeout(tmplLivePreview, 600);
}

async function tmplLivePreview() {
  document.getElementById('tmpl-preview-status').textContent = 'Chargement...';
  document.getElementById('tmpl-preview-status').className = 'badge bg-secondary';
  try {
    const userId = document.getElementById('tmpl-preview-user').value || null;
    const r = await fetch('/api/email-preview', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        template: tmplGetValue(tmplCurrentTab),
        subject: document.getElementById('tmpl-subject-' + tmplCurrentTab).value,
        type: tmplCurrentTab,
        user_id: userId ? parseInt(userId, 10) : null,
      }),
    });
    document.getElementById('tmpl-preview-frame').srcdoc = await r.text();
    document.getElementById('tmpl-preview-status').textContent = 'OK';
    document.getElementById('tmpl-preview-status').className = 'badge bg-success';
  } catch {
    document.getElementById('tmpl-preview-status').textContent = 'Erreur';
    document.getElementById('tmpl-preview-status').className = 'badge bg-danger';
  }
}

async function tmplSave() {
  try {
    const r = await fetch('/api/email-templates', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        email_request_template: tmplGetValue('request'),
        email_available_template: tmplGetValue('available'),
        email_available_vf_template: tmplGetValue('available_vf'),
        email_available_vo_tracking_template: tmplGetValue('available_vo_tracking'),
        email_vf_upgrade_template: tmplGetValue('vf_available'),
        email_language_episode_template: tmplGetValue('language_episode'),
        email_language_season_start_template: tmplGetValue('language_season_start'),
        email_language_season_complete_template: tmplGetValue('language_season_complete'),
        email_language_series_complete_template: tmplGetValue('language_series_complete'),
        email_failure_template: tmplGetValue('failed'),
        email_request_subject: document.getElementById('tmpl-subject-request').value,
        email_available_subject: document.getElementById('tmpl-subject-available').value,
        email_available_vf_subject: document.getElementById('tmpl-subject-available_vf').value,
        email_available_vo_tracking_subject: document.getElementById('tmpl-subject-available_vo_tracking').value,
        email_vf_upgrade_subject: document.getElementById('tmpl-subject-vf_available').value,
        email_language_episode_subject: document.getElementById('tmpl-subject-language_episode').value,
        email_language_season_start_subject: document.getElementById('tmpl-subject-language_season_start').value,
        email_language_season_complete_subject: document.getElementById('tmpl-subject-language_season_complete').value,
        email_language_series_complete_subject: document.getElementById('tmpl-subject-language_series_complete').value,
        email_failure_subject: document.getElementById('tmpl-subject-failed').value,
      }),
    });
    if (!r.ok) throw new Error();
    showToast('Templates enregistrés !', 'success');
  } catch {
    showToast('Erreur lors de l\'enregistrement', 'danger');
  }
}

async function tmplReset() {
  if (!await confirmAction({
    title: 'Réinitialiser les templates',
    body: 'Réinitialiser les trois templates et objets par défaut ?',
    okLabel: 'Réinitialiser', danger: true,
  })) return;
  await fetch('/api/email-templates/reset', {method: 'POST'});
  showToast('Réinitialisé — rechargement...', 'success');
  setTimeout(() => location.reload(), 1000);
}

async function tmplRestorePrevious() {
  if (!await confirmAction({
    title: 'Annuler la dernière modification',
    body: 'Restaurer les templates et objets tels qu\'ils étaient avant le dernier enregistrement ou la dernière réinitialisation ?',
    okLabel: 'Restaurer', danger: true,
  })) return;
  const r = await fetch('/api/email-templates/restore-previous', {method: 'POST'});
  if (!r.ok) {
    const res = await r.json().catch(() => ({}));
    showToast(res.detail || 'Aucune sauvegarde disponible', 'danger');
    return;
  }
  showToast('Restauré — rechargement...', 'success');
  setTimeout(() => location.reload(), 1000);
}

async function tmplTestSend() {
  showToast('Envoi du mail de test en cours...', 'info');
  try {
    const userId = document.getElementById('tmpl-preview-user').value || null;
    const r = await fetch('/api/email-templates/test-send', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        template: tmplGetValue(tmplCurrentTab),
        subject: document.getElementById('tmpl-subject-' + tmplCurrentTab).value,
        type: tmplCurrentTab,
        user_id: userId ? parseInt(userId, 10) : null,
      }),
    });
    const res = await r.json();
    if (!r.ok) throw new Error(res.detail || 'Erreur SMTP');
    showToast(res.message, 'success');
  } catch (err) {
    showToast(err.message, 'danger');
  }
}

function tmplInsertVar(e, varName) {
  const subjectInput = document.getElementById('tmpl-subject-' + tmplCurrentTab);
  if (document.activeElement === subjectInput) {
    const start = subjectInput.selectionStart;
    subjectInput.value = subjectInput.value.substring(0, start) + varName + subjectInput.value.substring(subjectInput.selectionEnd);
    subjectInput.selectionStart = subjectInput.selectionEnd = start + varName.length;
    subjectInput.focus();
    tmplSchedulePreview();
  } else if (tmplEditors[tmplCurrentTab]) {
    const cm = tmplEditors[tmplCurrentTab];
    cm.replaceRange(varName, cm.getDoc().getCursor());
    cm.focus();
  }
  tmplRenderVars();
}

// ── Media Issues Management ──────────────────────────────────────────────────
let _mediaIssues = [];
let _editingIssueId = null;

function _issueEscHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;');
}

function _issueFmtDateTime(iso) {
  if (!iso) return '-';
  const s = String(iso).endsWith('Z') || String(iso).includes('+') ? iso : iso + 'Z';
  const d = new Date(s);
  return isNaN(d) ? '-' : d.toLocaleString('fr-FR');
}

async function initIssuesTab() {
  await loadIssues();
}

async function loadIssues() {
  const statusFilter = document.querySelector('input[name="issueStatusFilter"]:checked')?.value || 'open';
  const tbody = document.getElementById('issues-list');
  const badge = document.getElementById('issues-badge');

  try {
    const r = await fetch(`/api/media/issues?status=${encodeURIComponent(statusFilter)}`);
    _mediaIssues = await r.json();

    // Dynamically update open issues badge count (always count "open" & "investigating")
    const openCountResp = await fetch('/api/media/issues?status=open');
    const openCountData = await openCountResp.json();
    const invCountResp = await fetch('/api/media/issues?status=investigating');
    const invCountData = await invCountResp.json();
    const totalOpen = (openCountData.length || 0) + (invCountData.length || 0);

    if (badge) {
      if (totalOpen > 0) {
        badge.textContent = totalOpen;
        badge.classList.remove('d-none');
      } else {
        badge.classList.add('d-none');
      }
    }

    if (!_mediaIssues.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-3">Aucun signalement trouvé.</td></tr>';
      return;
    }

    tbody.innerHTML = _mediaIssues.map(issue => {
      const typeLabel = issue.media_type === 'show' ? 'Série' : 'Film';
      const createdStr = _issueFmtDateTime(issue.created_at);
      
      let statusBadge = '';
      if (issue.status === 'open') statusBadge = '<span class="badge bg-danger">Ouvert</span>';
      else if (issue.status === 'investigating') statusBadge = '<span class="badge bg-warning text-dark">En cours</span>';
      else if (issue.status === 'resolved') statusBadge = '<span class="badge bg-success">Résolu</span>';
      else if (issue.status === 'closed') statusBadge = '<span class="badge bg-secondary">Fermé</span>';

      return `
        <tr>
          <td class="text-muted small">${_issueEscHtml(createdStr)}</td>
          <td>
            <div class="fw-semibold">${_issueEscHtml(issue.title)}</div>
            <span class="badge bg-secondary" style="font-size:10px">${typeLabel}</span>
          </td>
          <td><span class="badge bg-info text-dark">${_issueEscHtml(issue.issue_type)}</span></td>
          <td>${_issueEscHtml(issue.reporter_name || 'Inconnu')}</td>
          <td>
            <div class="small" style="max-width:300px; white-space:pre-wrap;">${_issueEscHtml(issue.message || '—')}</div>
          </td>
          <td>
            <div class="small text-muted" style="max-width:250px; white-space:pre-wrap;">${_issueEscHtml(issue.admin_note || '—')}</div>
          </td>
          <td class="text-end">
            <div class="d-inline-flex gap-1">
              <button class="btn btn-sm btn-outline-warning" onclick="editIssue(${issue.id})" title="Gérer/Note">
                <i class="bi bi-pencil-square"></i>
              </button>
              <button class="btn btn-sm btn-outline-info" onclick="retryIssueSearch(${issue.id}, this)" title="Relancer la recherche dans *arr">
                <i class="bi bi-search"></i>
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join('');
  } catch (e) {
    showToast("Erreur lors du chargement des signalements : " + e.message, "danger");
  }
}

function editIssue(id) {
  const issue = _mediaIssues.find(x => x.id === id);
  if (!issue) return;

  _editingIssueId = id;
  document.getElementById('edit-issue-id').value = id;
  document.getElementById('edit-issue-status').value = issue.status;
  document.getElementById('edit-issue-note').value = issue.admin_note || '';

  const modal = new bootstrap.Modal(document.getElementById('issueEditModal'));
  modal.show();
}

async function saveIssueChanges() {
  const id = _editingIssueId;
  const status = document.getElementById('edit-issue-status').value;
  const admin_note = document.getElementById('edit-issue-note').value.trim();

  try {
    const r = await fetch(`/api/media/issues/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status, admin_note })
    });
    if (!r.ok) throw new Error("Erreur de sauvegarde");

    showToast("Signalement mis à jour !", "success");
    bootstrap.Modal.getInstance(document.getElementById('issueEditModal')).hide();
    await loadIssues();
  } catch (e) {
    showToast("Erreur : " + e.message, "danger");
  }
}

async function retryIssueSearch(id, btn) {
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
  try {
    const r = await fetch(`/api/media/issues/${id}/retry`, { method: 'POST' });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || "Erreur de connexion aux serveurs Radarr/Sonarr");
    showToast("Recherche relancée avec succès !", "success");
  } catch (e) {
    showToast("Erreur : " + e.message, "danger");
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

// Check open issues on load to display badge
document.addEventListener('DOMContentLoaded', async () => {
  try { refreshConnHub(); } catch (e) {}
  const badge = document.getElementById('issues-badge');
  if (badge) {
    try {
      const openCountResp = await fetch('/api/media/issues?status=open');
      const openCountData = await openCountResp.json();
      const invCountResp = await fetch('/api/media/issues?status=investigating');
      const invCountData = await invCountResp.json();
      const totalOpen = (openCountData.length || 0) + (invCountData.length || 0);
      if (totalOpen > 0) {
        badge.textContent = totalOpen;
        badge.classList.remove('d-none');
      }
    } catch(e) {}
  }
});
