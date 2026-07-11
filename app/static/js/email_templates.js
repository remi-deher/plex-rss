const TMPL_TYPES = ['request', 'available', 'upgrade', 'failure'];

let tmplCurrentTab = 'request';
let tmplCurrentMode = 'editor';
let tmplPreviewTimer = null;

window.tmplSetMode = function(mode) {
  tmplCurrentMode = mode;

  const editorPanel = document.getElementById('tmpl-editor-panel');
  const previewPanel = document.getElementById('tmpl-preview-panel');
  const previewFooter = document.getElementById('tmpl-preview-footer');
  const previewControls = document.getElementById('tmpl-preview-controls');
  const varsCard = document.getElementById('tmpl-vars-card');
  const sharedCard = document.getElementById('tmpl-shared-card');
  const editorBtn = document.getElementById('tmpl-mode-editor-btn');
  const previewBtn = document.getElementById('tmpl-mode-preview-btn');

  const isPreview = mode === 'preview';

  editorPanel.classList.toggle('d-none', isPreview);
  previewPanel.classList.toggle('d-none', !isPreview);
  previewFooter.classList.toggle('d-none', !isPreview);
  previewControls.style.display = isPreview ? 'flex' : 'none';
  varsCard.classList.toggle('d-none', isPreview);
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

function tmplRenderVars() {
  const container = document.getElementById('variables-container');
  if (!container) return;

  const items = variablesList.map(v => {
    // Only show {raison} in failure tab
    if (v.tag === '{raison}' && tmplCurrentTab !== 'failure') return '';
    if (v.tag !== '{raison}' && tmplCurrentTab === 'failure') return '';

    return `<div class="tmpl-var-item" onclick="tmplInsertVar('${v.tag}')" title="${v.desc}">
      <code>${v.tag}</code> - <span class="text-muted" style="font-size:0.8rem">${v.desc}</span>
    </div>`;
  }).join('');

  container.innerHTML = items;
}

window.tmplInsertVar = function(varName) {
  const activeEl = document.activeElement;
  const subjectInput = document.getElementById('tmpl-subject-' + tmplCurrentTab);
  const contentTextarea = document.getElementById('tmpl-editor-' + tmplCurrentTab);
  const target = (activeEl === subjectInput) ? subjectInput : contentTextarea;
  if (!target) return;

  const start = target.selectionStart ?? target.value.length;
  const end = target.selectionEnd ?? target.value.length;
  target.value = target.value.substring(0, start) + varName + target.value.substring(end);
  target.selectionStart = target.selectionEnd = start + varName.length;
  target.focus();
  window.tmplSchedulePreview();
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
  const { show_poster, show_genres, show_requester, requester_label } = tmplGetSharedDraft();
  document.querySelectorAll('.tmpl-mockup-poster-img').forEach(el => el.style.display = show_poster ? '' : 'none');
  document.querySelectorAll('.tmpl-mockup-genres-row').forEach(el => el.style.display = show_genres ? '' : 'none');
  document.querySelectorAll('.tmpl-mockup-requester-row').forEach(el => el.style.display = show_requester ? '' : 'none');
  document.querySelectorAll('.tmpl-mockup-requester-label').forEach(el => el.textContent = requester_label);
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
  const { header_brand, header_subtitle, footer_template } = tmplGetSharedDraft();
  TMPL_TYPES.forEach(t => {
    const brandEl = document.getElementById('tmpl-mockup-brand-' + t);
    if (brandEl) brandEl.textContent = header_brand;
    const subtitleEl = document.getElementById('tmpl-mockup-subtitle-' + t);
    if (subtitleEl) subtitleEl.textContent = header_subtitle;
  });

  const previewBrand = document.getElementById('tmpl-shared-preview-brand');
  if (previewBrand) previewBrand.textContent = header_brand;
  const previewSubtitle = document.getElementById('tmpl-shared-preview-subtitle');
  if (previewSubtitle) previewSubtitle.textContent = header_subtitle;
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

      tmplRenderVars();
      window.tmplSchedulePreview(100);
    });
  });

  tmplRenderVars();
  tmplUpdateSharedHeaderMockup();
  window.tmplSchedulePreview(100);
});
