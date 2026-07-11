const TMPL_TYPES = ['request', 'available', 'upgrade', 'failure'];

// Miroirs des presets serveur (email_service.py FONT_FAMILY_PRESETS/SYNOPSIS_FONT_SIZE_PRESETS),
// utilisés uniquement pour l'aperçu client-side du mockup (le rendu email réel reste calculé côté serveur).
const TMPL_FONT_FAMILY_CSS = {
  arial: 'Arial, Helvetica, sans-serif',
  georgia: "Georgia, 'Times New Roman', serif",
  verdana: 'Verdana, Geneva, sans-serif',
  trebuchet: "'Trebuchet MS', Tahoma, sans-serif",
};
const TMPL_SYNOPSIS_SIZE_PX = { small: 12, normal: 13.5, large: 15, xlarge: 17 };

function tmplNumOrUndefined(id) {
  const el = document.getElementById(id);
  if (!el || el.value === '') return undefined;
  return Number(el.value);
}

let tmplCurrentTab = 'request';
let tmplCurrentMode = 'editor';
let tmplPreviewTimer = null;

window.tmplSetMode = function(mode) {
  tmplCurrentMode = mode;

  const editorPanel = document.getElementById('tmpl-editor-panel');
  const previewPanel = document.getElementById('tmpl-preview-panel');
  const previewFooter = document.getElementById('tmpl-preview-footer');
  const previewControls = document.getElementById('tmpl-preview-controls');
  const sharedCard = document.getElementById('tmpl-shared-card');
  const editorBtn = document.getElementById('tmpl-mode-editor-btn');
  const previewBtn = document.getElementById('tmpl-mode-preview-btn');

  const isPreview = mode === 'preview';

  editorPanel.classList.toggle('d-none', isPreview);
  previewPanel.classList.toggle('d-none', !isPreview);
  previewFooter.classList.toggle('d-none', !isPreview);
  previewControls.style.display = isPreview ? 'flex' : 'none';
  sharedCard.classList.toggle('d-none', isPreview);

  editorBtn.classList.toggle('active', !isPreview);
  previewBtn.classList.toggle('active', isPreview);

  if (isPreview) window.tmplSchedulePreview(0);
}

const variablesList = [
  { tag: '{titre}', desc: 'Titre de l\'œuvre (ex: Inception)' },
  { tag: '{type}', desc: '"Le film" ou "La série"' },
  { tag: '{media_type_et_titre}', desc: 'Combinaison (ex: Le film Inception)' },
  { tag: '{annee}', desc: 'Année de sortie (ex: 2010)' },
  { tag: '{affiche}', desc: 'URL de l\'affiche' },
  { tag: '{details_saison_episode}', desc: 'Informations saison/épisode (vide pour un film)' },
  { tag: '{langue}', desc: 'en VF, en VO, etc. (seulement si applicable)' },
  { tag: '{nom_utilisateur}', desc: 'Nom du demandeur' },
  { tag: '{synopsis}', desc: 'Résumé du média' },
  { tag: '{raison}', desc: 'Raison de l\'échec (uniquement onglet Échec)' },
];

// Suivi du dernier champ pertinent ayant eu le focus (sujet/contenu/pied de page). Les boutons
// de la barre d'outils et de la modale volent le focus au clic : sans ce suivi, on perdrait la
// cible et la position du curseur au moment d'appliquer une transformation ou d'insérer du texte.
let tmplLastActiveField = null;

function tmplTrackActiveField(el) {
  if (!el || !el.id) return;
  if (el.id.startsWith('tmpl-subject-') || el.id.startsWith('tmpl-editor-') || el.id === 'tmpl-footer') {
    tmplLastActiveField = el;
  }
}

document.addEventListener('focusin', e => tmplTrackActiveField(e.target));

function tmplResolveInsertTarget() {
  return tmplLastActiveField || document.getElementById('tmpl-editor-' + tmplCurrentTab);
}

function tmplInsertTextAtTarget(text) {
  const target = tmplResolveInsertTarget();
  if (!target) return;
  const start = target.selectionStart ?? target.value.length;
  const end = target.selectionEnd ?? target.value.length;
  target.value = target.value.substring(0, start) + text + target.value.substring(end);
  target.selectionStart = target.selectionEnd = start + text.length;
  target.focus();
  window.tmplSchedulePreview();
}

// --- Barre d'outils Markdown (gras/italique/titres/listes/citation/lien) ---

window.tmplWrapSelection = function(prefix, suffix, placeholder) {
  const target = tmplResolveInsertTarget();
  if (!target) return;
  const start = target.selectionStart;
  const end = target.selectionEnd;
  const selected = target.value.substring(start, end) || placeholder;
  target.value = target.value.substring(0, start) + prefix + selected + suffix + target.value.substring(end);
  target.focus();
  target.selectionStart = start + prefix.length;
  target.selectionEnd = target.selectionStart + selected.length;
  window.tmplSchedulePreview();
}

window.tmplPrefixLines = function(prefix) {
  const target = tmplResolveInsertTarget();
  if (!target) return;
  const value = target.value;
  const start = target.selectionStart;
  const end = target.selectionEnd;
  const lineStart = value.lastIndexOf('\n', start - 1) + 1;
  const lineEnd = value.indexOf('\n', end) === -1 ? value.length : value.indexOf('\n', end);
  const block = value.substring(lineStart, lineEnd);
  const transformed = block.split('\n').map(l => prefix + l).join('\n');
  target.value = value.substring(0, lineStart) + transformed + value.substring(lineEnd);
  target.focus();
  target.selectionStart = lineStart;
  target.selectionEnd = lineStart + transformed.length;
  window.tmplSchedulePreview();
}

window.tmplSetHeading = function(level) {
  level = Number(level);
  const target = tmplResolveInsertTarget();
  if (!target) return;
  const value = target.value;
  const pos = target.selectionStart;
  const lineStart = value.lastIndexOf('\n', pos - 1) + 1;
  const lineEnd = value.indexOf('\n', pos) === -1 ? value.length : value.indexOf('\n', pos);
  const line = value.substring(lineStart, lineEnd).replace(/^#{1,6}\s*/, '');
  const newLine = (level > 0 ? '#'.repeat(level) + ' ' : '') + line;
  target.value = value.substring(0, lineStart) + newLine + value.substring(lineEnd);
  target.focus();
  target.selectionStart = target.selectionEnd = lineStart + newLine.length;
  window.tmplSchedulePreview();
}

window.tmplInsertLink = function() {
  const target = tmplResolveInsertTarget();
  if (!target) return;
  // Capture la sélection AVANT window.prompt() : la boîte de dialogue native fait perdre
  // le focus (et potentiellement la position du curseur) au champ le temps qu'elle est ouverte.
  const start = target.selectionStart;
  const end = target.selectionEnd;
  const selected = target.value.substring(start, end) || 'texte du lien';
  const url = window.prompt('URL du lien :', 'https://');
  if (!url) return;
  const insertion = `[${selected}](${url})`;
  target.value = target.value.substring(0, start) + insertion + target.value.substring(end);
  target.focus();
  target.selectionStart = target.selectionEnd = start + insertion.length;
  window.tmplSchedulePreview();
}

// --- Modale de sélection des variables (recherche, tout cocher, double-clic) ---

function tmplRenderVariablesModalList(filterText) {
  const list = document.getElementById('tmpl-variables-modal-list');
  if (!list) return;
  const ft = (filterText || '').trim().toLowerCase();

  const filtered = variablesList
    .filter(v => (v.tag === '{raison}') === (tmplCurrentTab === 'failure'))
    .filter(v => !ft || v.tag.toLowerCase().includes(ft) || v.desc.toLowerCase().includes(ft));

  if (!filtered.length) {
    list.innerHTML = '<div class="text-muted small text-center py-3">Aucune variable ne correspond.</div>';
  } else {
    list.innerHTML = filtered.map((v, i) => `
      <div class="form-check tmpl-var-check-item" ondblclick="tmplInsertSingleVariable('${v.tag}')" title="Double-clic pour insérer directement">
        <input class="form-check-input tmpl-var-checkbox" type="checkbox" value="${v.tag}" id="tmpl-var-check-${i}" onchange="tmplUpdateVariablesPreview()">
        <label class="form-check-label" for="tmpl-var-check-${i}">
          <code>${v.tag}</code> - <span class="text-muted small">${v.desc}</span>
        </label>
      </div>`).join('');
  }
  tmplUpdateVariablesPreview();
}

window.tmplFilterVariablesModal = function() {
  tmplRenderVariablesModalList(document.getElementById('tmpl-variables-search')?.value);
}

window.tmplToggleAllVariables = function(checked) {
  document.querySelectorAll('.tmpl-var-checkbox').forEach(el => el.checked = checked);
  tmplUpdateVariablesPreview();
}

window.tmplUpdateVariablesPreview = function() {
  const preview = document.getElementById('tmpl-variables-preview');
  if (!preview) return;
  const checked = Array.from(document.querySelectorAll('.tmpl-var-checkbox:checked')).map(el => el.value);
  preview.textContent = checked.length ? 'À insérer : ' + checked.join(' ') : '';
}

window.tmplOpenVariablesModal = function() {
  // Fige la cible AVANT que la modale ne prenne le focus (le tracker focusin l'aurait sinon perdue).
  tmplLastActiveField = tmplResolveInsertTarget();

  const search = document.getElementById('tmpl-variables-search');
  if (search) search.value = '';
  tmplRenderVariablesModalList('');

  bootstrap.Modal.getOrCreateInstance(document.getElementById('tmplVariablesModal')).show();
}

window.tmplInsertSingleVariable = function(tag) {
  tmplInsertTextAtTarget(tag);
  bootstrap.Modal.getInstance(document.getElementById('tmplVariablesModal'))?.hide();
}

window.tmplInsertSelectedVariables = function() {
  const checked = Array.from(document.querySelectorAll('.tmpl-var-checkbox:checked')).map(el => el.value);
  if (checked.length) tmplInsertTextAtTarget(checked.join(' '));
  bootstrap.Modal.getInstance(document.getElementById('tmplVariablesModal'))?.hide();
}

function tmplGetValue(tab) {
  const el = document.getElementById('tmpl-editor-' + tab);
  return el ? el.value : '';
}

function tmplGetDraftVisuals(tab) {
  return {
    accent_color: document.getElementById('tmpl-accent-' + tab)?.value,
    badge_text: document.getElementById('tmpl-badge-' + tab)?.value,
    headline_text: document.getElementById('tmpl-headline-' + tab)?.value,
    show_synopsis: document.getElementById('tmpl-synopsis-' + tab)?.checked,
  };
}

// Les réglages "communs" (header, affiche/tags) sont dupliqués dans chaque onglet
// (juste sous le sujet) pour rester visibles en contexte, mais représentent une seule
// valeur : tmplSyncMirrors les garde synchronisés entre les 4 onglets à chaque frappe.
function tmplGetSharedDraft() {
  return {
    header_brand: document.getElementById('tmpl-header-brand-' + tmplCurrentTab)?.value,
    header_subtitle: document.getElementById('tmpl-header-subtitle-' + tmplCurrentTab)?.value,
    footer_template: document.getElementById('tmpl-footer')?.value,
    show_poster: document.getElementById('tmpl-show-poster-' + tmplCurrentTab)?.checked,
    show_genres: document.getElementById('tmpl-show-genres-' + tmplCurrentTab)?.checked,
    show_requester: document.getElementById('tmpl-show-requester-' + tmplCurrentTab)?.checked,
    requester_label: document.getElementById('tmpl-requester-label-' + tmplCurrentTab)?.value,
    brand_color: document.getElementById('tmpl-brand-color-' + tmplCurrentTab)?.value,
    show_header_subtitle: document.getElementById('tmpl-show-header-subtitle-' + tmplCurrentTab)?.checked,
    poster_width: tmplNumOrUndefined('tmpl-poster-width-' + tmplCurrentTab),
    media_layout: document.getElementById('tmpl-media-layout-' + tmplCurrentTab)?.value,
    bg_color: document.getElementById('tmpl-bg-color-' + tmplCurrentTab)?.value,
    card_bg_color: document.getElementById('tmpl-card-bg-color-' + tmplCurrentTab)?.value,
    font_family: document.getElementById('tmpl-font-family-' + tmplCurrentTab)?.value,
    card_width: tmplNumOrUndefined('tmpl-card-width-' + tmplCurrentTab),
    card_border_radius: tmplNumOrUndefined('tmpl-card-border-radius-' + tmplCurrentTab),
    synopsis_font_size: document.getElementById('tmpl-synopsis-font-size-' + tmplCurrentTab)?.value,
    show_tmdb_link: document.getElementById('tmpl-show-tmdb-link-' + tmplCurrentTab)?.checked,
    show_plex_button: document.getElementById('tmpl-show-plex-button-' + tmplCurrentTab)?.checked,
  };
}

function tmplSyncMirrors(baseId, sourceTab) {
  const source = document.getElementById(baseId + '-' + sourceTab);
  if (!source) return;
  const isCheckbox = source.type === 'checkbox';
  const value = isCheckbox ? source.checked : source.value;
  TMPL_TYPES.forEach(t => {
    if (t === sourceTab) return;
    const el = document.getElementById(baseId + '-' + t);
    if (!el) return;
    if (isCheckbox) el.checked = value; else el.value = value;
  });
}

// Rendu Markdown minimal (gras/italique/lien) pour l'aperçu live du pied de page.
// L'aperçu fidèle et complet reste le mode "Aperçu" (rendu serveur via /api/email-preview).
function tmplRenderMiniMarkdown(text) {
  const esc = (text || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return esc
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" style="color:#e5a00d;text-decoration:none">$1</a>')
    .replace(/\n\n+/g, '<br><br>')
    .replace(/\n/g, ' ');
}

function tmplUpdateMediaBlockMockup() {
  const {
    show_poster, show_genres, show_requester, requester_label, brand_color, poster_width, media_layout,
    show_tmdb_link, show_plex_button,
  } = tmplGetSharedDraft();
  document.querySelectorAll('.tmpl-mockup-poster-img').forEach(el => {
    el.style.display = show_poster ? '' : 'none';
    if (poster_width) el.style.width = poster_width + 'px';
  });
  document.querySelectorAll('.tmpl-mockup-genres-row').forEach(el => el.style.display = show_genres ? '' : 'none');
  document.querySelectorAll('.tmpl-mockup-requester-row').forEach(el => el.style.display = show_requester ? '' : 'none');
  document.querySelectorAll('.tmpl-mockup-requester-label').forEach(el => {
    el.textContent = requester_label;
    if (brand_color) el.style.color = brand_color;
  });
  document.querySelectorAll('.tmpl-mockup-media-row').forEach(el => {
    el.classList.remove('tmpl-layout-left', 'tmpl-layout-right', 'tmpl-layout-stacked');
    el.classList.add('tmpl-layout-' + (media_layout || 'left'));
  });
  document.querySelectorAll('.tmpl-mockup-tmdb-row').forEach(el => el.style.display = show_tmdb_link ? '' : 'none');
  document.querySelectorAll('.tmpl-mockup-tmdb-link').forEach(el => {
    if (brand_color) el.style.color = brand_color;
  });
  document.querySelectorAll('.tmpl-mockup-plex-row').forEach(el => el.style.display = show_plex_button ? '' : 'none');
}

function tmplUpdateCardStyleMockup() {
  const { bg_color, card_bg_color, font_family, card_width, card_border_radius, synopsis_font_size } = tmplGetSharedDraft();
  const fontCss = TMPL_FONT_FAMILY_CSS[font_family] || TMPL_FONT_FAMILY_CSS.arial;
  const synopsisPx = TMPL_SYNOPSIS_SIZE_PX[synopsis_font_size] || TMPL_SYNOPSIS_SIZE_PX.normal;

  TMPL_TYPES.forEach(t => {
    const frame = document.getElementById('tmpl-mockup-page-frame-' + t);
    if (frame && bg_color) frame.style.background = bg_color;

    const card = document.getElementById('tmpl-mockup-card-' + t);
    if (card) {
      if (card_bg_color) card.style.background = card_bg_color;
      if (card_width) card.style.maxWidth = card_width + 'px';
      if (card_border_radius !== undefined) card.style.borderRadius = card_border_radius + 'px';
      card.style.fontFamily = fontCss;
    }
  });

  document.querySelectorAll('.tmpl-mockup-synopsis-text').forEach(el => el.style.fontSize = synopsisPx + 'px');
}

function tmplUpdateBannerMockup(tab) {
  const { accent_color, badge_text, headline_text, show_synopsis } = tmplGetDraftVisuals(tab);

  const banner = document.getElementById('tmpl-banner-' + tab);
  if (banner && accent_color) banner.style.background = accent_color;

  const badgeEl = document.getElementById('tmpl-banner-badge-' + tab);
  if (badgeEl) badgeEl.textContent = badge_text;

  const headlineEl = document.getElementById('tmpl-banner-headline-' + tab);
  if (headlineEl) headlineEl.textContent = headline_text;

  const contentBox = document.getElementById('tmpl-content-box-' + tab);
  if (contentBox && accent_color) contentBox.style.borderLeftColor = accent_color;

  const genreTag = document.getElementById('tmpl-mockup-genre-' + tab);
  if (genreTag && accent_color) genreTag.style.color = accent_color;

  const synopsis = document.getElementById('tmpl-mockup-synopsis-' + tab);
  if (synopsis) synopsis.style.display = show_synopsis ? '' : 'none';
}

function tmplUpdateSharedHeaderMockup() {
  const { header_brand, header_subtitle, footer_template, brand_color, show_header_subtitle } = tmplGetSharedDraft();
  TMPL_TYPES.forEach(t => {
    const brandEl = document.getElementById('tmpl-mockup-brand-' + t);
    if (brandEl) {
      brandEl.textContent = header_brand;
      if (brand_color) brandEl.style.color = brand_color;
    }
    const subtitleEl = document.getElementById('tmpl-mockup-subtitle-' + t);
    if (subtitleEl) {
      subtitleEl.textContent = header_subtitle;
      subtitleEl.style.display = show_header_subtitle ? '' : 'none';
    }
  });

  const previewBrand = document.getElementById('tmpl-shared-preview-brand');
  if (previewBrand) {
    previewBrand.textContent = header_brand;
    if (brand_color) previewBrand.style.color = brand_color;
  }
  const previewSubtitle = document.getElementById('tmpl-shared-preview-subtitle');
  if (previewSubtitle) {
    previewSubtitle.textContent = header_subtitle;
    previewSubtitle.style.display = show_header_subtitle ? '' : 'none';
  }
  const previewFooter = document.getElementById('tmpl-shared-preview-footer');
  if (previewFooter) previewFooter.innerHTML = tmplRenderMiniMarkdown(footer_template);
}

window.tmplSchedulePreview = function(ms = 800) {
  clearTimeout(tmplPreviewTimer);
  tmplPreviewTimer = setTimeout(tmplLivePreview, ms);
}

async function tmplLivePreview() {
  const badge = document.getElementById('tmpl-preview-status');
  if(badge) {
      badge.className = 'badge bg-warning text-dark';
      badge.textContent = 'Actualisation...';
  }

  const payload = {
    template: tmplGetValue(tmplCurrentTab),
    subject: document.getElementById('tmpl-subject-' + tmplCurrentTab)?.value || '',
    type: tmplCurrentTab,
    user_id: document.getElementById('tmpl-preview-user')?.value || null,
    preview_variant: document.getElementById('tmpl-preview-variant')?.value || null,
    ...tmplGetSharedDraft(),
    ...tmplGetDraftVisuals(tmplCurrentTab),
  };

  try {
    const r = await fetch('/api/email-preview', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    if (!r.ok) throw new Error('Erreur de prévisualisation');
    const html = await r.text();

    const iframe = document.getElementById('tmpl-preview-frame');
    if(iframe) iframe.srcdoc = html;

    if(badge) {
        badge.className = 'badge bg-success';
        badge.textContent = 'À jour';
    }
  } catch(e) {
    if(badge) {
        badge.className = 'badge bg-danger';
        badge.textContent = 'Erreur';
    }
    const iframe = document.getElementById('tmpl-preview-frame');
    if(iframe) iframe.srcdoc = `<div style="padding:20px;color:red;font-family:sans-serif">Erreur: ${e.message}</div>`;
  }
}

window.tmplSave = async function() {
  const btn = document.querySelector('button[onclick="tmplSave()"]');
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

  const shared = tmplGetSharedDraft();
  const payload = {
    email_request_template: tmplGetValue('request'),
    email_available_template: tmplGetValue('available'),
    email_upgrade_template: tmplGetValue('upgrade'),
    email_failure_template: tmplGetValue('failure'),
    email_request_subject: document.getElementById('tmpl-subject-request').value,
    email_available_subject: document.getElementById('tmpl-subject-available').value,
    email_upgrade_subject: document.getElementById('tmpl-subject-upgrade').value,
    email_failure_subject: document.getElementById('tmpl-subject-failure').value,
    email_header_brand: shared.header_brand,
    email_header_subtitle: shared.header_subtitle,
    email_footer_template: shared.footer_template,
    email_show_poster: shared.show_poster,
    email_show_genres: shared.show_genres,
    email_show_requester: shared.show_requester,
    email_requester_label: shared.requester_label,
    email_brand_color: shared.brand_color,
    email_show_header_subtitle: shared.show_header_subtitle,
    email_poster_width: shared.poster_width,
    email_media_layout: shared.media_layout,
    email_bg_color: shared.bg_color,
    email_card_bg_color: shared.card_bg_color,
    email_font_family: shared.font_family,
    email_card_width: shared.card_width,
    email_card_border_radius: shared.card_border_radius,
    email_synopsis_font_size: shared.synopsis_font_size,
    email_show_tmdb_link: shared.show_tmdb_link,
    email_show_plex_button: shared.show_plex_button,
  };

  TMPL_TYPES.forEach(t => {
    const v = tmplGetDraftVisuals(t);
    payload['email_' + t + '_accent_color'] = v.accent_color;
    payload['email_' + t + '_badge_text'] = v.badge_text;
    payload['email_' + t + '_headline_text'] = v.headline_text;
    payload['email_' + t + '_show_synopsis'] = v.show_synopsis;
  });

  try {
    const r = await fetch('/api/email-templates', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    if (!r.ok) throw new Error('Erreur');
    if (typeof showToast !== 'undefined') showToast('Templates enregistrés !', 'success');
  } catch(e) {
    if (typeof showToast !== 'undefined') showToast(e.message, 'danger');
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

window.tmplTestSend = async function() {
  const btn = document.querySelector('button[onclick="tmplTestSend()"]');
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

  const payload = {
    template: tmplGetValue(tmplCurrentTab),
    subject: document.getElementById('tmpl-subject-' + tmplCurrentTab)?.value || '',
    type: tmplCurrentTab,
    user_id: document.getElementById('tmpl-preview-user')?.value || null,
    preview_variant: document.getElementById('tmpl-preview-variant')?.value || null,
    ...tmplGetSharedDraft(),
    ...tmplGetDraftVisuals(tmplCurrentTab),
  };

  try {
    const r = await fetch('/api/email-templates/test-send', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'Erreur');
    if (typeof showToast !== 'undefined') showToast(d.message || 'Email envoyé !', 'success');
  } catch(e) {
    if (typeof showToast !== 'undefined') showToast(e.message, 'danger');
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

window.tmplReset = async function() {
  if(!confirm("Réinitialiser tous les templates (Demande, Dispo, etc) à leur valeur par défaut ?")) return;
  try {
    const r = await fetch('/api/email-templates/reset', { method:'POST' });
    if(r.ok) window.location.reload();
    else if (typeof showToast !== 'undefined') showToast('Erreur', 'danger');
  } catch(e) {
    if (typeof showToast !== 'undefined') showToast(e.message, 'danger');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('tmpl-footer')?.addEventListener('input', () => {
    tmplUpdateSharedHeaderMockup();
    window.tmplSchedulePreview(400);
  });

  for (const t of TMPL_TYPES) {
    document.getElementById('tmpl-editor-' + t)?.addEventListener('input', () => window.tmplSchedulePreview(800));
    document.getElementById('tmpl-subject-' + t)?.addEventListener('input', () => window.tmplSchedulePreview(800));

    ['tmpl-accent-', 'tmpl-badge-', 'tmpl-headline-'].forEach(prefix => {
      document.getElementById(prefix + t)?.addEventListener('input', () => {
        tmplUpdateBannerMockup(t);
        window.tmplSchedulePreview(400);
      });
    });
    document.getElementById('tmpl-synopsis-' + t)?.addEventListener('change', () => {
      tmplUpdateBannerMockup(t);
      window.tmplSchedulePreview(400);
    });

    document.getElementById('tmpl-header-brand-' + t)?.addEventListener('input', () => {
      tmplSyncMirrors('tmpl-header-brand', t);
      tmplUpdateSharedHeaderMockup();
      window.tmplSchedulePreview(400);
    });
    document.getElementById('tmpl-header-subtitle-' + t)?.addEventListener('input', () => {
      tmplSyncMirrors('tmpl-header-subtitle', t);
      tmplUpdateSharedHeaderMockup();
      window.tmplSchedulePreview(400);
    });
    ['tmpl-show-poster', 'tmpl-show-genres', 'tmpl-show-requester'].forEach(baseId => {
      document.getElementById(baseId + '-' + t)?.addEventListener('change', () => {
        tmplSyncMirrors(baseId, t);
        tmplUpdateMediaBlockMockup();
        window.tmplSchedulePreview(400);
      });
    });
    document.getElementById('tmpl-requester-label-' + t)?.addEventListener('input', () => {
      tmplSyncMirrors('tmpl-requester-label', t);
      tmplUpdateMediaBlockMockup();
      window.tmplSchedulePreview(400);
    });

    document.getElementById('tmpl-brand-color-' + t)?.addEventListener('input', () => {
      tmplSyncMirrors('tmpl-brand-color', t);
      tmplUpdateSharedHeaderMockup();
      tmplUpdateMediaBlockMockup();
      window.tmplSchedulePreview(400);
    });
    document.getElementById('tmpl-show-header-subtitle-' + t)?.addEventListener('change', () => {
      tmplSyncMirrors('tmpl-show-header-subtitle', t);
      tmplUpdateSharedHeaderMockup();
      window.tmplSchedulePreview(400);
    });
    document.getElementById('tmpl-poster-width-' + t)?.addEventListener('input', () => {
      tmplSyncMirrors('tmpl-poster-width', t);
      const value = document.getElementById('tmpl-poster-width-' + t).value;
      TMPL_TYPES.forEach(tt => {
        const label = document.getElementById('tmpl-poster-width-value-' + tt);
        if (label) label.textContent = value;
      });
      tmplUpdateMediaBlockMockup();
      window.tmplSchedulePreview(400);
    });
    document.getElementById('tmpl-media-layout-' + t)?.addEventListener('change', () => {
      tmplSyncMirrors('tmpl-media-layout', t);
      tmplUpdateMediaBlockMockup();
      window.tmplSchedulePreview(400);
    });

    ['tmpl-bg-color', 'tmpl-card-bg-color'].forEach(baseId => {
      document.getElementById(baseId + '-' + t)?.addEventListener('input', () => {
        tmplSyncMirrors(baseId, t);
        tmplUpdateCardStyleMockup();
        window.tmplSchedulePreview(400);
      });
    });
    ['tmpl-font-family', 'tmpl-synopsis-font-size'].forEach(baseId => {
      document.getElementById(baseId + '-' + t)?.addEventListener('change', () => {
        tmplSyncMirrors(baseId, t);
        tmplUpdateCardStyleMockup();
        window.tmplSchedulePreview(400);
      });
    });
    document.getElementById('tmpl-card-width-' + t)?.addEventListener('input', () => {
      tmplSyncMirrors('tmpl-card-width', t);
      const value = document.getElementById('tmpl-card-width-' + t).value;
      TMPL_TYPES.forEach(tt => {
        const label = document.getElementById('tmpl-card-width-value-' + tt);
        if (label) label.textContent = value;
      });
      tmplUpdateCardStyleMockup();
      window.tmplSchedulePreview(400);
    });
    document.getElementById('tmpl-card-border-radius-' + t)?.addEventListener('input', () => {
      tmplSyncMirrors('tmpl-card-border-radius', t);
      const value = document.getElementById('tmpl-card-border-radius-' + t).value;
      TMPL_TYPES.forEach(tt => {
        const label = document.getElementById('tmpl-card-radius-value-' + tt);
        if (label) label.textContent = value;
      });
      tmplUpdateCardStyleMockup();
      window.tmplSchedulePreview(400);
    });
    ['tmpl-show-tmdb-link', 'tmpl-show-plex-button'].forEach(baseId => {
      document.getElementById(baseId + '-' + t)?.addEventListener('change', () => {
        tmplSyncMirrors(baseId, t);
        tmplUpdateMediaBlockMockup();
        window.tmplSchedulePreview(400);
      });
    });
  }

  const tabEls = document.querySelectorAll('button[data-bs-toggle="pill"]');
  tabEls.forEach(el => {
    el.addEventListener('shown.bs.tab', event => {
      const targetId = event.target.getAttribute('data-bs-target');
      tmplCurrentTab = targetId.replace('#tab-', '');

      const pv = document.getElementById('tmpl-preview-variant');
      if (tmplCurrentTab === 'available' || tmplCurrentTab === 'upgrade') {
        pv.style.display = 'inline-block';
        if (tmplCurrentTab === 'upgrade') {
            pv.value = 'movie_vf';
        }
      } else {
        pv.style.display = 'none';
      }

      window.tmplSchedulePreview(100);
    });
  });

  tmplUpdateSharedHeaderMockup();
  tmplUpdateCardStyleMockup();
  window.tmplSchedulePreview(100);
});
