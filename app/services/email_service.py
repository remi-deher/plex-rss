"""
Service d'envoi d'emails transactionnels via SMTP (aiosmtplib).

Trois types d'emails :
- Demande    : envoyé quand un nouveau média est ajouté à Sonarr/Radarr
- Disponible : envoyé quand le fichier est téléchargé et disponible sur Plex
- Echec      : envoyé quand la transmission à Sonarr/Radarr échoue

Les templates HTML sont personnalisables via l'UI (Settings → Templates email).
Si aucun template custom n'est défini, les templates par défaut ci-dessous sont utilisés.
Les templates sont rendus avec Jinja2 (variables : title, year, poster_url, plex_user, etc.).
"""

import logging
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
from jinja2 import TemplateError
from jinja2.sandbox import SandboxedEnvironment

from ..models import MediaRequest, Settings

logger = logging.getLogger(__name__)

# Environnement Jinja restreint : les templates email sont éditables via l'UI admin,
# le sandbox limite l'accès aux attributs/méthodes dangereux (ex: __class__.__mro__).
_jinja_env = SandboxedEnvironment()

# Coquille « newsletter » commune à tous les emails. Structure email-safe (tables +
# styles inline, pas de flexbox/grid), thème sombre Plexarr. Les sections communes
# (barre de marque, carte média + genres en pastilles, synopsis, pied de page) sont
# générées automatiquement à partir du contexte ; chaque template ne fournit que sa
# couleur d'accent, son badge, son titre et son bloc de statut.
#
# Les placeholders Python sont des jetons __XXX__ (remplacés côté Python via .replace),
# ce qui laisse les expressions Jinja ({{ }} / {% %}) intactes dans la chaîne — elles
# sont rendues normalement par render_template() au moment de l'envoi.
_EMAIL_SHELL = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0d0d0d;font-family:Arial,Helvetica,sans-serif;color:#e9e9e9">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#0d0d0d;padding:20px 0">
  <tr><td align="center">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;background:#141414;border:1px solid #333333;border-radius:10px;overflow:hidden">

      <tr><td style="background:#1a1a1a;padding:12px 20px;border-bottom:1px solid #2a2a2a">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td style="color:#e5a00d;font-weight:bold;letter-spacing:1.5px;font-size:15px">PLEXARR</td>
          <td align="right" style="color:#666666;font-size:11px;letter-spacing:.5px;text-transform:uppercase">Notification Plex</td>
        </tr></table>
      </td></tr>

      <tr><td style="background:__ACCENT__;padding:22px 20px;text-align:center">
        <div style="color:#ffffff;font-size:11px;font-weight:bold;letter-spacing:1px;text-transform:uppercase">__BADGE__</div>
        <div style="color:#ffffff;font-size:21px;font-weight:bold;margin-top:5px;line-height:1.25">__HEADLINE__</div>
      </td></tr>

      <tr><td style="padding:22px 20px 4px">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          {% if poster_url %}<td valign="top" width="116" style="padding-right:16px">
            <img src="{{ poster_url }}" width="100" alt="" style="width:100px;height:auto;border-radius:8px;display:block;border:1px solid #444444">
          </td>{% endif %}
          <td valign="top">
            <div style="color:#ffffff;font-size:19px;font-weight:bold;line-height:1.3">{{ title }}{% if year %} <span style="color:#888888;font-weight:normal">({{ year }})</span>{% endif %}</div>
            <div style="margin-top:9px">
              <span style="display:inline-block;background:#2a2a2a;color:#bbbbbb;font-size:11px;padding:3px 10px;border-radius:20px;margin:0 4px 5px 0">{{ media_type_label }}</span>
              {% if genres %}{% for g in genres.split(',') %}{% if g.strip() %}<span style="display:inline-block;background:#242424;color:__ACCENT__;font-size:11px;padding:3px 10px;border-radius:20px;margin:0 4px 5px 0">{{ g.strip() }}</span>{% endif %}{% endfor %}{% endif %}
            </div>
            <div style="margin-top:10px;color:#999999;font-size:13px"><span style="color:#e5a00d;font-weight:bold">Demandé par</span>&nbsp;&nbsp;{{ plex_user }}</div>
          </td>
        </tr></table>
      </td></tr>
__SYNOPSIS__
__STATUS__

      <tr><td style="padding:20px;text-align:center;border-top:1px solid #2a2a2a">
        <div style="color:#888888;font-size:12px">Géré par <span style="color:#e5a00d;font-weight:bold">Plexarr</span> — __FOOTER_NOTE__</div>
        <div style="color:#555555;font-size:11px;margin-top:5px">Logiciel créé par <a href="https://github.com/remi-deher/plex-rss" style="color:#e5a00d;text-decoration:none">DEHER Rémi</a></div>
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>"""

_SYNOPSIS_SECTION = """
      {% if overview %}<tr><td style="padding:12px 20px 2px">
        <div style="color:#777777;font-size:10px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:5px">Synopsis</div>
        <div style="color:#cccccc;font-size:13.5px;line-height:1.65">{{ overview }}</div>
      </td></tr>{% endif %}"""


def _status_box(accent: str, inner: str) -> str:
    """Bloc de statut coloré (encadré à filet gauche) inséré sous la carte média."""
    return (
        '\n      <tr><td style="padding:16px 20px 2px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td style="background:#1c1c1c;border-left:3px solid {accent};padding:13px 15px;'
        f'color:#dddddd;font-size:14px;line-height:1.6">{inner}</td>'
        "</tr></table></td></tr>"
    )


def _note_row(inner: str) -> str:
    """Ligne de complément discrète (sous le bloc de statut)."""
    return (
        f'\n      <tr><td style="padding:9px 20px 2px;color:#999999;font-size:13px;line-height:1.6">{inner}</td></tr>'
    )


def _reason_sub(inner: str) -> str:
    """Sous-ligne « détail du jalon / raison » à l'intérieur d'un bloc de statut."""
    return f'<div style="margin-top:8px;color:#9ca3af;font-size:12px">{inner}</div>'


def _email_layout(
    accent: str,
    badge: str,
    headline: str,
    status_html: str,
    *,
    show_synopsis: bool = True,
    footer_note: str = "suivi automatique de votre bibliothèque",
) -> str:
    """Assemble un email newsletter complet depuis la coquille commune.

    accent/badge/headline/status_html/footer_note peuvent contenir des expressions Jinja
    (rendues à l'envoi). `status_html` est le(s) bloc(s) `<tr>` de statut, typiquement
    construit(s) via _status_box()/_note_row().
    """
    synopsis = _SYNOPSIS_SECTION if show_synopsis else ""
    return (
        _EMAIL_SHELL.replace("__ACCENT__", accent)
        .replace("__BADGE__", badge)
        .replace("__HEADLINE__", headline)
        .replace("__SYNOPSIS__", synopsis)
        .replace("__STATUS__", status_html)
        .replace("__FOOTER_NOTE__", footer_note)
    )


DEFAULT_REQUEST_TEMPLATE = _email_layout(
    "#e5a00d",
    "Nouvelle demande",
    "Nouvelle demande Plex",
    _status_box(
        "#e5a00d",
        "Votre demande est bien enregistrée. Plexarr vous préviendra automatiquement dès que le "
        "contenu sera disponible sur votre serveur Plex.",
    ),
    footer_note="suivi automatique de votre demande",
)

DEFAULT_AVAILABLE_TEMPLATE = _email_layout(
    "#1db954",
    "Disponible",
    "Disponible sur Plex&nbsp;!",
    _status_box(
        "#1db954",
        "<strong>{{ media_type_label_cap }}</strong> est maintenant disponible sur votre serveur Plex. "
        "Bonne séance&nbsp;!",
    ),
)


DEFAULT_FAILURE_TEMPLATE = _email_layout(
    "#dc3545",
    "Action requise",
    "Demande non transmise",
    _status_box("#dc3545", "{{ reason }}")
    + _note_row(
        "La demande reste enregistrée. Plexarr réessaiera automatiquement lors du prochain passage "
        "si le problème est résolu."
    ),
    show_synopsis=False,
    footer_note="transmission Sonarr / Radarr",
)


DEFAULT_VO_ONLY_TEMPLATE = _email_layout(
    "#0d6efd",
    "Disponible en VO",
    "Disponible sur Plex en VO&nbsp;!",
    _status_box(
        "#0d6efd",
        "{{ media_type_label_cap }} est disponible sur Plex, actuellement <strong>en version originale</strong>.",
    )
    + _note_row("Plexarr continue de surveiller l'arrivée de la VF et vous préviendra automatiquement."),
    footer_note="suivi VF",
)


DEFAULT_VF_AVAILABLE_TEMPLATE = _email_layout(
    "#1db954",
    "Mise à jour en VF",
    "Mise à jour en VF&nbsp;!",
    _status_box(
        "#1db954",
        "Bonne nouvelle&nbsp;: {{ media_type_label_cap }} vient d'être mis à jour "
        "<strong>en version française</strong> sur Plex."
        "{% if language_reason %}" + _reason_sub("{{ language_reason }}") + "{% endif %}",
    ),
    footer_note="suivi VF",
)


DEFAULT_AVAILABLE_VF_TEMPLATE = _email_layout(
    "#1db954",
    "Disponible en VF",
    "Disponible sur Plex en VF&nbsp;!",
    _status_box(
        "#1db954",
        "{{ media_type_label_cap }} est disponible sur Plex <strong>avec une piste audio française</strong>.",
    )
    + _note_row("Ce mail regroupe la disponibilité Plex et le statut VF pour éviter les doublons."),
)


DEFAULT_AVAILABLE_VO_TRACKING_TEMPLATE = _email_layout(
    "#0d6efd",
    "Disponible en VO",
    "Disponible sur Plex en VO&nbsp;!",
    _status_box(
        "#0d6efd",
        "{{ media_type_label_cap }} est disponible sur Plex, actuellement <strong>en version originale</strong>.",
    )
    + _note_row(
        "Plexarr continue de surveiller l'arrivée de la VF et vous préviendra uniquement si une vraie mise à jour arrive."
    ),
    footer_note="suivi VF",
)


DEFAULT_LANGUAGE_EPISODE_TEMPLATE = _email_layout(
    "#0d6efd",
    "Nouvel épisode{% if language %} {{ language }}{% endif %}",
    "Nouvel épisode{% if language %} en {{ language }}{% endif %}&nbsp;!",
    _status_box(
        "#0d6efd",
        "Un nouvel épisode est maintenant disponible{% if language %} en <strong>{{ language }}</strong>{% endif %} sur Plex."
        "{% if language_reason %}" + _reason_sub("{{ language_reason }}") + "{% endif %}",
    ),
    footer_note="suivi {% if language %}{{ language }}{% else %}des épisodes{% endif %}",
)


DEFAULT_LANGUAGE_SEASON_START_TEMPLATE = _email_layout(
    "#0d6efd",
    "Saison démarrée{% if language %} en {{ language }}{% endif %}",
    "Saison démarrée{% if language %} en {{ language }}{% endif %}&nbsp;!",
    _status_box(
        "#0d6efd",
        "Le premier épisode suivi de la saison est maintenant disponible{% if language %} en <strong>{{ language }}</strong>{% endif %} sur Plex."
        "{% if language_reason %}" + _reason_sub("{{ language_reason }}") + "{% endif %}",
    ),
    footer_note="suivi {% if language %}{{ language }}{% else %}des épisodes{% endif %}",
)


DEFAULT_LANGUAGE_SEASON_COMPLETE_TEMPLATE = _email_layout(
    "#1db954",
    "Saison complète{% if language %} en {{ language }}{% endif %}",
    "Saison complète{% if language %} en {{ language }}{% endif %}&nbsp;!",
    _status_box(
        "#1db954",
        "Une saison complète est maintenant disponible{% if language %} en <strong>{{ language }}</strong>{% endif %} sur Plex."
        "{% if language_reason %}" + _reason_sub("{{ language_reason }}") + "{% endif %}",
    ),
    footer_note="suivi {% if language %}{{ language }}{% else %}des épisodes{% endif %}",
)


DEFAULT_LANGUAGE_SERIES_COMPLETE_TEMPLATE = _email_layout(
    "#1db954",
    "Série complète{% if language %} en {{ language }}{% endif %}",
    "Série complète{% if language %} en {{ language }}{% endif %}&nbsp;!",
    _status_box(
        "#1db954",
        "La série est maintenant complète{% if language %} en <strong>{{ language }}</strong>{% endif %} sur Plex."
        "{% if language_reason %}" + _reason_sub("{{ language_reason }}") + "{% endif %}",
    ),
    footer_note="suivi {% if language %}{{ language }}{% else %}des épisodes{% endif %}",
)


DEFAULT_PARTIALLY_AVAILABLE_TEMPLATE = _email_layout(
    "#e5a00d",
    "Disponibilité partielle",
    "Partiellement disponible",
    _status_box(
        "#e5a00d",
        "{{ media_type_label_cap }} est en cours de diffusion&nbsp;: "
        "<strong>{{ episodes_available }}/{{ episodes_aired }}</strong> épisode(s) diffusé(s) "
        "déjà disponibles sur votre serveur Plex.",
    )
    + _note_row("Vous serez prévenu à nouveau dès que la série sera intégralement disponible."),
)


def _build_context(request: MediaRequest, display_name: str | None = None) -> dict:
    """Construit le contexte Jinja2 commun à tous les templates email.

    display_name (custom_name du PlexUser) prend le pas sur request.plex_user
    si fourni, pour rester cohérent avec l'aperçu (Settings → Templates email).
    """
    is_show = request.media_type == "show"
    return {
        "title": request.title or "",
        "year": request.year,
        "poster_url": request.poster_url or "",
        "plex_user": display_name or request.plex_user or request.plex_user_id or "",
        "media_type": request.media_type,
        "media_type_label": "Série" if is_show else "Film",
        "media_type_label_cap": "La série" if is_show else "Le film",
        "overview": request.overview or "",
        "genres": getattr(request, "genres", "") or "",
    }


def _language_milestone_type(reason: str) -> str | None:
    reason = (reason or "").strip()
    lower = reason.lower()
    if re.search(r"\b(vo|vf)\s+s\d{2}e\d{2}\b", lower, flags=re.IGNORECASE):
        return "episode"
    if "saison" in lower and ("demarree" in lower or "démarrée" in lower):
        return "season_start"
    if "saison" in lower and "complete" in lower:
        return "season_complete"
    if "serie complete" in lower or "série complète" in lower:
        return "series_complete"
    return None


def _language_from_reason(reason: str, fallback: str = "VF") -> str:
    reason = (reason or "").strip().upper()
    if reason.startswith("VO"):
        return "VO"
    if reason.startswith("VF"):
        return "VF"
    return fallback


def _episode_milestone_type(reason: str) -> str | None:
    """Comme `_language_milestone_type`, mais pour les jalons sans langue (mode "simple",
    voir `_milestone_reason` côté scheduler avec direction="simple") — pas de préfixe VO/VF.
    """
    reason = (reason or "").strip().lower()
    if re.search(r"\bs\d{2}e\d{2}\b", reason):
        return "episode"
    if "saison" in reason and "demarree" in reason:
        return "season_start"
    if "saison" in reason and "complete" in reason:
        return "season_complete"
    if "serie complete" in reason:
        return "series_complete"
    return None


def _language_milestone_defaults(milestone_type: str):
    defaults = {
        "episode": (
            "email_language_episode_template",
            "email_language_episode_subject",
            DEFAULT_LANGUAGE_EPISODE_TEMPLATE,
            "[Plexarr] {{ title }} : nouvel épisode{% if language %} en {{ language }}{% endif %} sur Plex !",
        ),
        "season_start": (
            "email_language_season_start_template",
            "email_language_season_start_subject",
            DEFAULT_LANGUAGE_SEASON_START_TEMPLATE,
            "[Plexarr] {{ title }} : saison démarrée{% if language %} en {{ language }}{% endif %} sur Plex !",
        ),
        "season_complete": (
            "email_language_season_complete_template",
            "email_language_season_complete_subject",
            DEFAULT_LANGUAGE_SEASON_COMPLETE_TEMPLATE,
            "[Plexarr] {{ title }} : saison complète{% if language %} en {{ language }}{% endif %} sur Plex !",
        ),
        "series_complete": (
            "email_language_series_complete_template",
            "email_language_series_complete_subject",
            DEFAULT_LANGUAGE_SERIES_COMPLETE_TEMPLATE,
            "[Plexarr] {{ title }} est entièrement disponible{% if language %} en {{ language }}{% endif %} sur Plex !",
        ),
    }
    return defaults[milestone_type]


def _render_milestone_email(
    settings: Settings,
    request: MediaRequest,
    ctx: dict,
    milestone_type: str,
    language: str,
    reason: str,
) -> tuple[str, str]:
    ctx.update(
        {
            "language": language,
            "language_lower": language.lower() if language else "",
            "language_reason": reason,
            "language_milestone_type": milestone_type,
        }
    )
    template_attr, subject_attr, default_template, default_subject = _language_milestone_defaults(milestone_type)
    template = (
        getattr(settings, template_attr, None) if isinstance(getattr(settings, template_attr, None), str) else None
    )
    subject_tmpl = (
        getattr(settings, subject_attr, None) if isinstance(getattr(settings, subject_attr, None), str) else None
    )
    html = render_template(template or default_template, ctx)
    subject = render_subject(subject_tmpl or default_subject, ctx, fallback=f"[Plexarr] {request.title} : {reason}")
    return subject, html


def _render_language_milestone_email(
    settings: Settings,
    request: MediaRequest,
    ctx: dict,
    reason: str,
    fallback_language: str = "VF",
) -> tuple[str, str] | None:
    milestone_type = _language_milestone_type(reason)
    if not milestone_type:
        return None
    language = _language_from_reason(reason, fallback_language)
    return _render_milestone_email(settings, request, ctx, milestone_type, language, reason)


def render_template(template_str: str, context: dict) -> str:
    """Rend un template Jinja2 et retourne le HTML.

    En cas d'erreur de template, retourne un message d'erreur HTML pour éviter
    de silencieusement envoyer un email vide.
    """
    try:
        return _jinja_env.from_string(template_str).render(**context)
    except TemplateError as e:
        logger.error(f"Template render error: {e}")
        return f"<p>Erreur de template : {e}</p>"


def render_subject(template_str: str, context: dict, fallback: str) -> str:
    """Rend un template Jinja2 destiné à un sujet d'email.

    Contrairement à render_template(), une erreur de rendu ne produit pas de HTML
    d'erreur (qui finirait sinon dans l'objet de l'email) : elle retombe sur `fallback`.
    """
    try:
        return _jinja_env.from_string(template_str).render(**context)
    except TemplateError as e:
        logger.error(f"Subject template render error: {e}")
        return fallback


EMAIL_FOOTER_HTML = """
<div style="max-width:600px;margin:18px auto 0;padding:14px 18px;border-top:1px solid #333;color:#888;font-family:Arial,sans-serif;font-size:12px;text-align:center">
  Plexarr — Logiciel crée par
  <a href="https://github.com/remi-deher/plex-rss" style="color:#e5a00d;text-decoration:none">DEHER Rémi</a>
</div>
"""


def add_email_footer(html: str) -> str:
    """Ajoute le footer Plexarr/crédit à tous les emails, y compris les templates custom."""
    if "DEHER Rémi" in html:
        return html
    footer = EMAIL_FOOTER_HTML
    lower = html.lower()
    body_idx = lower.rfind("</body>")
    if body_idx != -1:
        return html[:body_idx] + footer + html[body_idx:]
    html_idx = lower.rfind("</html>")
    if html_idx != -1:
        return html[:html_idx] + footer + html[html_idx:]
    return html + footer


def _resolve_str_setting(settings, field):
    val = getattr(settings, field, None)
    return val if isinstance(val, str) else None


async def _send_templated(
    settings: Settings,
    request: MediaRequest,
    recipient: str,
    display_name: str | None = None,
    *,
    template_field: str,
    default_template: str,
    subject_field: str,
    default_subject: str,
    subject_fallback: str,
    extra_ctx: dict | None = None,
):
    ctx = _build_context(request, display_name)
    if extra_ctx:
        ctx.update(extra_ctx)
    html = render_template(_resolve_str_setting(settings, template_field) or default_template, ctx)
    subject = render_subject(
        _resolve_str_setting(settings, subject_field) or default_subject, ctx, fallback=subject_fallback
    )
    await _send(settings, recipient, subject, html)


async def send_request_notification(
    settings: Settings, request: MediaRequest, recipient: str, display_name: str | None = None
):
    """Envoie l'email de confirmation de demande."""
    await _send_templated(
        settings,
        request,
        recipient,
        display_name,
        template_field="email_request_template",
        default_template=DEFAULT_REQUEST_TEMPLATE,
        subject_field="email_request_subject",
        default_subject="[Plexarr] Nouvelle demande : {{ title }}",
        subject_fallback=f"[Plexarr] Nouvelle demande : {request.title}",
    )


async def send_available_notification(
    settings: Settings, request: MediaRequest, recipient: str, display_name: str | None = None
):
    """Envoie l'email de notification de disponibilité."""
    await _send_templated(
        settings,
        request,
        recipient,
        display_name,
        template_field="email_available_template",
        default_template=DEFAULT_AVAILABLE_TEMPLATE,
        subject_field="email_available_subject",
        default_subject="[Plexarr] {{ title }} est disponible sur Plex !",
        subject_fallback=f"[Plexarr] {request.title} est disponible sur Plex !",
    )


async def send_vo_only_notification(
    settings: Settings, request: MediaRequest, recipient: str, display_name: str | None = None, reason: str = ""
):
    """Envoie l'email « disponible mais en VO uniquement » (suivi VFF)."""
    ctx = _build_context(request, display_name)
    ctx["language_reason"] = reason or "Suivi VF actif"
    milestone_email = _render_language_milestone_email(settings, request, ctx, reason, fallback_language="VO")
    if milestone_email:
        subject, html = milestone_email
        await _send(settings, recipient, subject, html)
        return
    html = render_template(DEFAULT_VO_ONLY_TEMPLATE, ctx)
    subject = f"[Plexarr] {request.title} est disponible sur Plex en VO !"
    await _send(settings, recipient, subject, html)


async def send_vf_available_notification(
    settings: Settings, request: MediaRequest, recipient: str, display_name: str | None = None, reason: str = ""
):
    """Envoie l'email « la VF est maintenant disponible » (suivi VFF)."""
    ctx = _build_context(request, display_name)
    ctx["language_reason"] = reason
    milestone_email = _render_language_milestone_email(settings, request, ctx, reason, fallback_language="VF")
    if milestone_email:
        subject, html = milestone_email
        await _send(settings, recipient, subject, html)
        return
    template = (
        settings.email_vf_upgrade_template
        if isinstance(getattr(settings, "email_vf_upgrade_template", None), str)
        else None
    )
    html = render_template(template or DEFAULT_VF_AVAILABLE_TEMPLATE, ctx)
    subject_tmpl = (
        settings.email_vf_upgrade_subject
        if isinstance(getattr(settings, "email_vf_upgrade_subject", None), str)
        else None
    )
    subject = render_subject(
        subject_tmpl or "[Plexarr] {{ title }} est désormais disponible sur Plex en VF !",
        ctx,
        fallback=f"[Plexarr] {request.title} est désormais disponible sur Plex en VF !",
    )
    await _send(settings, recipient, subject, html)


async def send_available_vf_notification(
    settings: Settings, request: MediaRequest, recipient: str, display_name: str | None = None
):
    """Envoie un seul email quand la disponibilité initiale est déjà en VF."""
    await _send_templated(
        settings,
        request,
        recipient,
        display_name,
        template_field="email_available_vf_template",
        default_template=DEFAULT_AVAILABLE_VF_TEMPLATE,
        subject_field="email_available_vf_subject",
        default_subject="[Plexarr] {{ title }} est disponible sur Plex en VF !",
        subject_fallback=f"[Plexarr] {request.title} est disponible sur Plex en VF !",
    )


async def send_available_vo_tracking_notification(
    settings: Settings, request: MediaRequest, recipient: str, display_name: str | None = None
):
    """Envoie un seul email quand la disponibilité initiale est VO avec suivi VF."""
    await _send_templated(
        settings,
        request,
        recipient,
        display_name,
        template_field="email_available_vo_tracking_template",
        default_template=DEFAULT_AVAILABLE_VO_TRACKING_TEMPLATE,
        subject_field="email_available_vo_tracking_subject",
        default_subject="[Plexarr] {{ title }} est disponible sur Plex en VO !",
        subject_fallback=f"[Plexarr] {request.title} est disponible sur Plex en VO !",
    )


async def send_episode_track_notification(
    settings: Settings, request: MediaRequest, recipient: str, display_name: str | None = None, reason: str = ""
):
    """Envoie l'email de suivi épisode/saison en mode "simple" (indépendant de la langue).

    Réutilise les mêmes templates que le suivi VF/VO (`email_language_*`) — `language`
    est laissé vide dans le contexte, et ces templates rendent la mention de langue
    conditionnelle pour rester cohérents dans les deux modes.
    """
    ctx = _build_context(request, display_name)
    milestone_type = _episode_milestone_type(reason) or "episode"
    subject, html = _render_milestone_email(settings, request, ctx, milestone_type, "", reason)
    await _send(settings, recipient, subject, html)


async def send_partially_available_notification(
    settings: Settings, request: MediaRequest, recipient: str, reason: str = "", display_name: str | None = None
):
    """Envoie l'email « disponibilité partielle » (série en cours de diffusion)."""
    ctx = _build_context(request, display_name)
    ctx["episodes_available"] = request.episodes_available_count or 0
    ctx["episodes_aired"] = request.episodes_aired_count or 0
    ctx["episodes_total"] = request.episodes_total_count or 0
    html = render_template(DEFAULT_PARTIALLY_AVAILABLE_TEMPLATE, ctx)
    subject = (
        f"[Plexarr] Partiellement disponible : {request.title} ({reason})"
        if reason
        else f"[Plexarr] Partiellement disponible : {request.title}"
    )
    await _send(settings, recipient, subject, html)


async def _send(settings: Settings, recipient: str, subject: str, html: str):
    """Envoie un email via SMTP en TLS ou STARTTLS selon la configuration.

    use_tls=True  → connexion SSL directe (port 465 typiquement)
    start_tls=True → STARTTLS sur connexion plain (port 587 typiquement)
    Les deux sont mutuellement exclusifs ; smtp_tls=True active STARTTLS.
    """
    if not all([settings.smtp_host, settings.smtp_user, settings.smtp_password, settings.smtp_from]):
        logger.warning("SMTP not configured, skipping email")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = recipient
    msg.attach(MIMEText(add_email_footer(html), "html"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            use_tls=not settings.smtp_tls,
            start_tls=settings.smtp_tls,
        )
        logger.info(f"Email sent to {recipient}: {subject}")
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        raise


async def send_failure_notification(
    settings: Settings, request: MediaRequest, recipient: str, reason: str = "", display_name: str | None = None
):
    """Envoie l'email d'échec de transmission."""
    await _send_templated(
        settings,
        request,
        recipient,
        display_name,
        template_field="email_failure_template",
        default_template=DEFAULT_FAILURE_TEMPLATE,
        subject_field="email_failure_subject",
        default_subject="[Plexarr] Échec de transmission : {{ title }}",
        subject_fallback=f"[Plexarr] Échec de transmission : {request.title}",
        extra_ctx={"reason": reason or "Erreur inconnue"},
    )


async def test_smtp(settings: Settings, test_recipient: str) -> tuple[bool, str]:
    """Envoie un email de test pour valider la configuration SMTP.

    Returns:
        (success, message)
    """
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "[Plexarr] Test SMTP"
        msg["From"] = settings.smtp_from
        msg["To"] = test_recipient
        msg.attach(MIMEText("<p>Configuration SMTP opérationnelle.</p>", "html"))
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            use_tls=not settings.smtp_tls,
            start_tls=settings.smtp_tls,
        )
        return True, f"Email envoyé à {test_recipient}"
    except Exception as e:
        return False, str(e)
