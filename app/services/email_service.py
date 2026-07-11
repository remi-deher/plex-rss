import asyncio
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
import markdown
from jinja2 import TemplateError
from jinja2.sandbox import SandboxedEnvironment

from ..models import LibraryItem, MediaRequest, Settings
from . import vff

logger = logging.getLogger(__name__)

_jinja_env = SandboxedEnvironment()

_EMAIL_SHELL = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>a{color:{{ _brand_color }};text-decoration:none}</style>
</head>
<body style="margin:0;padding:0;background:{{ _bg_color }};font-family:{{ _font_family }};color:#e9e9e9">
{% macro title_block() %}
<div style="color:#ffffff;font-size:19px;font-weight:bold;line-height:1.3">{{ _title }}{% if _year %} <span style="color:#888888;font-weight:normal">({{ _year }})</span>{% endif %}</div>
<div style="margin-top:9px">
  <span style="display:inline-block;background:#2a2a2a;color:#bbbbbb;font-size:11px;padding:3px 10px;border-radius:20px;margin:0 4px 5px 0">{{ _media_type_label }}</span>
  {% if _show_genres and _genres %}{% for g in _genres.split(',') %}{% if g.strip() %}<span style="display:inline-block;background:#242424;color:{{ _accent_color }};font-size:11px;padding:3px 10px;border-radius:20px;margin:0 4px 5px 0">{{ g.strip() }}</span>{% endif %}{% endfor %}{% endif %}
</div>
{% if _show_requester %}<div style="margin-top:10px;color:#999999;font-size:13px"><span style="color:{{ _brand_color }};font-weight:bold">{{ _requester_label }}</span>&nbsp;&nbsp;{{ _plex_user }}</div>{% endif %}
{% if _show_tmdb_link and _tmdb_url %}<div style="margin-top:10px"><a href="{{ _tmdb_url }}" style="color:{{ _brand_color }};font-size:12.5px;font-weight:bold;text-decoration:none">Voir sur TMDB &rarr;</a></div>{% endif %}
{% endmacro %}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{{ _bg_color }};padding:20px 0">
  <tr><td align="center">
    <table role="presentation" width="{{ _card_width }}" cellpadding="0" cellspacing="0" style="width:100%;max-width:{{ _card_width }}px;background:{{ _card_bg_color }};border:1px solid #333333;border-radius:{{ _card_border_radius }}px;overflow:hidden">

      <tr><td style="background:#1a1a1a;padding:12px 20px;border-bottom:1px solid #2a2a2a">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td style="color:{{ _brand_color }};font-weight:bold;letter-spacing:1.5px;font-size:15px">{{ _header_brand }}</td>
          {% if _show_header_subtitle %}<td align="right" style="color:#666666;font-size:11px;letter-spacing:.5px;text-transform:uppercase">{{ _header_subtitle }}</td>{% endif %}
        </tr></table>
      </td></tr>

      <tr><td style="background:{{ _accent_color }};padding:22px 20px;text-align:center">
        <div style="color:#ffffff;font-size:11px;font-weight:bold;letter-spacing:1px;text-transform:uppercase">{{ _badge_text }}</div>
        <div style="color:#ffffff;font-size:21px;font-weight:bold;margin-top:5px;line-height:1.25">{{ _headline_text }}</div>
      </td></tr>

      <tr><td style="padding:22px 20px 4px">
        {% if _media_layout == 'stacked' %}
          {% if _show_poster and _poster_url %}<div style="text-align:center;margin-bottom:12px">
            <img src="{{ _poster_url }}" width="{{ _poster_width }}" alt="" style="width:{{ _poster_width }}px;height:auto;border-radius:8px;display:inline-block;border:1px solid #444444">
          </div>{% endif %}
          <div style="text-align:center">{{ title_block() }}</div>
        {% elif _media_layout == 'right' %}
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td valign="top">{{ title_block() }}</td>
          {% if _show_poster and _poster_url %}<td valign="top" width="{{ _poster_width + 16 }}" style="padding-left:16px">
            <img src="{{ _poster_url }}" width="{{ _poster_width }}" alt="" style="width:{{ _poster_width }}px;height:auto;border-radius:8px;display:block;border:1px solid #444444">
          </td>{% endif %}
        </tr></table>
        {% else %}
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          {% if _show_poster and _poster_url %}<td valign="top" width="{{ _poster_width + 16 }}" style="padding-right:16px">
            <img src="{{ _poster_url }}" width="{{ _poster_width }}" alt="" style="width:{{ _poster_width }}px;height:auto;border-radius:8px;display:block;border:1px solid #444444">
          </td>{% endif %}
          <td valign="top">{{ title_block() }}</td>
        </tr></table>
        {% endif %}
      </td></tr>

      {% if _overview and _show_synopsis %}<tr><td style="padding:12px 20px 2px">
        <div style="color:#777777;font-size:10px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:5px">Synopsis</div>
        <div style="color:#cccccc;font-size:{{ _synopsis_font_size }}px;line-height:1.65">{{ _overview }}</div>
      </td></tr>{% endif %}

      <tr><td style="padding:16px 20px 2px">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td style="background:#1c1c1c;border-left:3px solid {{ _accent_color }};padding:13px 15px;color:#dddddd;font-size:14px;line-height:1.6">
            __CONTENT__
          </td>
        </tr></table>
      </td></tr>

      {% if _show_plex_button and _plex_deep_link %}<tr><td style="padding:18px 20px 2px;text-align:center">
        <a href="{{ _plex_deep_link }}" style="display:inline-block;background:{{ _accent_color }};color:#ffffff;font-weight:bold;font-size:14px;padding:10px 24px;border-radius:6px;text-decoration:none">&#9654; Lire sur Plex</a>
      </td></tr>{% endif %}

      <tr><td style="padding:15px 20px 20px"></td></tr>

      <tr><td style="padding:20px;text-align:center;border-top:1px solid #2a2a2a;color:#888888;font-size:12px">
        {{ _footer_html }}
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>"""

DEFAULT_REQUEST_TEMPLATE = """Votre demande est bien enregistrée.

*Plexarr vous préviendra automatiquement dès que le contenu sera disponible sur votre serveur Plex.*"""

DEFAULT_AVAILABLE_TEMPLATE = """**{media_type_et_titre}** {details_saison_episode} est disponible {langue}.

Amusez-vous bien !"""

DEFAULT_UPGRADE_TEMPLATE = """**{media_type_et_titre}** {details_saison_episode} vient d'être mis à jour !
La version **{langue}** est maintenant disponible sur Plex."""

DEFAULT_FAILURE_TEMPLATE = """Une erreur est survenue lors de la transmission à Sonarr/Radarr.

**Détails de l'erreur :**
{raison}

*La demande reste enregistrée. Plexarr réessaiera automatiquement lors de la prochaine vérification si le problème est résolu.*"""

DEFAULT_CORRECTION_TEMPLATE = """Bonjour {nom_utilisateur},

Une correction a été effectuée sur **{media_type_et_titre}** {details_saison_episode}.

Corrections appliquées :
{corrections}

{note_correction}

Vous pouvez relancer la lecture depuis Plex."""

DEFAULT_HEADER_BRAND = "PLEXARR"
DEFAULT_HEADER_SUBTITLE = "Notification Plex"
DEFAULT_FOOTER_TEMPLATE = """Géré par **Plexarr**

[Logiciel créé par DEHER Rémi](https://github.com/remi-deher/plex-rss)"""
DEFAULT_SHOW_POSTER = True
DEFAULT_SHOW_GENRES = True
DEFAULT_SHOW_REQUESTER = True
DEFAULT_REQUESTER_LABEL = "Demandé par"
DEFAULT_BRAND_COLOR = "#e5a00d"
DEFAULT_SHOW_HEADER_SUBTITLE = True
DEFAULT_POSTER_WIDTH = 100
DEFAULT_MEDIA_LAYOUT = "left"
DEFAULT_BG_COLOR = "#0d0d0d"
DEFAULT_CARD_BG_COLOR = "#141414"
DEFAULT_FONT_FAMILY_KEY = "arial"
DEFAULT_CARD_WIDTH = 600
DEFAULT_CARD_BORDER_RADIUS = 10
DEFAULT_SYNOPSIS_FONT_SIZE_KEY = "normal"
DEFAULT_SHOW_TMDB_LINK = True
DEFAULT_SHOW_PLEX_BUTTON = True

# Presets fermés (pas de champ libre) pour garantir un rendu correct dans les clients email.
FONT_FAMILY_PRESETS = {
    "arial": "Arial, Helvetica, sans-serif",
    "georgia": "Georgia, 'Times New Roman', serif",
    "verdana": "Verdana, Geneva, sans-serif",
    "trebuchet": "'Trebuchet MS', Tahoma, sans-serif",
}
SYNOPSIS_FONT_SIZE_PRESETS = {
    "small": 12,
    "normal": 13.5,
    "large": 15,
    "xlarge": 17,
}

# Bandeau (couleur/badge/titre/synopsis) par type d'évènement, éditable via /templates.
# "available" sert aussi de base pour la variante VO, qui applique une exception
# automatique de couleur/badge par-dessus ces valeurs (voir send_available_notification).
_EVENT_VISUAL_DEFAULTS = {
    "request": {
        "accent_color": "#e5a00d",
        "badge_text": "Nouvelle demande",
        "headline_text": "Demande enregistrée",
        "show_synopsis": True,
    },
    "available": {
        "accent_color": "#1db954",
        "badge_text": "Disponible",
        "headline_text": "Média disponible",
        "show_synopsis": True,
    },
    "upgrade": {
        "accent_color": "#1db954",
        "badge_text": "Mise à jour VF",
        "headline_text": "VF disponible",
        "show_synopsis": True,
    },
    "failure": {
        "accent_color": "#dc3545",
        "badge_text": "Action requise",
        "headline_text": "Demande non transmise",
        "show_synopsis": False,
    },
    "correction": {
        "accent_color": "#20c997",
        "badge_text": "Correction",
        "headline_text": "Correction effectuée",
        "show_synopsis": True,
    },
}


def _setting_str(settings, field: str, default: str) -> str:
    val = getattr(settings, field, None) if settings else None
    return val if isinstance(val, str) and val else default


def _setting_bool(settings, field: str, default: bool) -> bool:
    val = getattr(settings, field, None) if settings else None
    return default if val is None else bool(val)


def _setting_int(settings, field: str, default: int) -> int:
    val = getattr(settings, field, None) if settings else None
    return default if val is None else int(val)


def get_shared_email_parts(settings) -> dict:
    """Partie commune à tous les emails (header, pied de page, bloc affiche/tags), éditable une seule fois."""
    footer_md = _setting_str(settings, "email_footer_template", DEFAULT_FOOTER_TEMPLATE)
    return {
        "_header_brand": _setting_str(settings, "email_header_brand", DEFAULT_HEADER_BRAND),
        "_header_subtitle": _setting_str(settings, "email_header_subtitle", DEFAULT_HEADER_SUBTITLE),
        "_footer_html": markdown.markdown(footer_md),
        "_show_poster": _setting_bool(settings, "email_show_poster", DEFAULT_SHOW_POSTER),
        "_show_genres": _setting_bool(settings, "email_show_genres", DEFAULT_SHOW_GENRES),
        "_show_requester": _setting_bool(settings, "email_show_requester", DEFAULT_SHOW_REQUESTER),
        "_requester_label": _setting_str(settings, "email_requester_label", DEFAULT_REQUESTER_LABEL),
        "_brand_color": _setting_str(settings, "email_brand_color", DEFAULT_BRAND_COLOR),
        "_show_header_subtitle": _setting_bool(settings, "email_show_header_subtitle", DEFAULT_SHOW_HEADER_SUBTITLE),
        "_poster_width": _setting_int(settings, "email_poster_width", DEFAULT_POSTER_WIDTH),
        "_media_layout": _setting_str(settings, "email_media_layout", DEFAULT_MEDIA_LAYOUT),
        "_bg_color": _setting_str(settings, "email_bg_color", DEFAULT_BG_COLOR),
        "_card_bg_color": _setting_str(settings, "email_card_bg_color", DEFAULT_CARD_BG_COLOR),
        "_font_family": FONT_FAMILY_PRESETS.get(
            _setting_str(settings, "email_font_family", DEFAULT_FONT_FAMILY_KEY), FONT_FAMILY_PRESETS["arial"]
        ),
        "_card_width": _setting_int(settings, "email_card_width", DEFAULT_CARD_WIDTH),
        "_card_border_radius": _setting_int(settings, "email_card_border_radius", DEFAULT_CARD_BORDER_RADIUS),
        "_synopsis_font_size": SYNOPSIS_FONT_SIZE_PRESETS.get(
            _setting_str(settings, "email_synopsis_font_size", DEFAULT_SYNOPSIS_FONT_SIZE_KEY),
            SYNOPSIS_FONT_SIZE_PRESETS["normal"],
        ),
        "_show_tmdb_link": _setting_bool(settings, "email_show_tmdb_link", DEFAULT_SHOW_TMDB_LINK),
        "_show_plex_button": _setting_bool(settings, "email_show_plex_button", DEFAULT_SHOW_PLEX_BUTTON),
    }


def get_event_visuals(settings, event_type: str) -> dict:
    """Bandeau (couleur/badge/titre/synopsis) pour un type d'évènement donné."""
    defaults = _EVENT_VISUAL_DEFAULTS[event_type]
    return {
        "_accent_color": _setting_str(settings, f"email_{event_type}_accent_color", str(defaults["accent_color"])),
        "_badge_text": _setting_str(settings, f"email_{event_type}_badge_text", str(defaults["badge_text"])),
        "_headline_text": _setting_str(settings, f"email_{event_type}_headline_text", str(defaults["headline_text"])),
        "_show_synopsis": _setting_bool(settings, f"email_{event_type}_show_synopsis", bool(defaults["show_synopsis"])),
    }


def build_tmdb_url(request: MediaRequest | LibraryItem) -> str | None:
    if not request.tmdb_id:
        return None
    kind = "tv" if request.media_type == "show" else "movie"
    return f"https://www.themoviedb.org/{kind}/{request.tmdb_id}"


def _resolve_plex_deep_link_sync(settings: Settings, request: MediaRequest | LibraryItem) -> str | None:
    """Bloquant (plexapi) : à appeler uniquement via asyncio.to_thread."""
    plex = vff.connect(settings.plex_url, settings.plex_token)
    section_type = "show" if request.media_type == "show" else "movie"
    library_names = [s.title for s in plex.library.sections() if s.type == section_type]
    item = vff.find_item_in_libraries(
        plex,
        library_names,
        request.title,
        request.year,
        tmdb_id=request.tmdb_id,
        tvdb_id=request.tvdb_id,
        imdb_id=request.imdb_id,
        plex_guid=request.plex_guid,
    )
    if item is None:
        return None
    return (
        f"https://app.plex.tv/desktop/#!/server/{plex.machineIdentifier}/details?key=/library/metadata/{item.ratingKey}"
    )


async def resolve_plex_deep_link(
    settings: Settings, request: MediaRequest | LibraryItem, timeout: float = 6.0
) -> str | None:
    """Résout un lien profond vers l'item exact dans Plex, pour le bouton "Lire sur Plex".

    Best-effort : ne doit jamais faire échouer l'envoi de l'email. Toute erreur (serveur
    injoignable, item introuvable, timeout) renvoie simplement None — le bouton est alors
    omis par le template (voir _EMAIL_SHELL, `{% if _show_plex_button and _plex_deep_link %}`).
    À n'appeler que pour un envoi réel, jamais depuis l'aperçu de /templates.
    """
    if not settings or not settings.plex_url or not settings.plex_token:
        return None
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_resolve_plex_deep_link_sync, settings, request), timeout=timeout
        )
    except Exception as exc:
        logger.debug(f"resolve_plex_deep_link: échec pour {request.title!r}: {exc}")
        return None


def _format_corrections(corrections: list[str] | tuple[str, ...] | None) -> str:
    cleaned = [str(c).strip() for c in (corrections or []) if str(c).strip()]
    return "\n".join(f"- {c}" for c in cleaned)


def _build_tags(
    request: MediaRequest | LibraryItem,
    display_name: str | None = None,
    scope: str = "movie",
    language: str | None = None,
    is_upgrade: bool = False,
    season_number: int | None = None,
    episode_number: int | None = None,
    reason: str = "",
    corrections: list[str] | tuple[str, ...] | None = None,
    correction_note: str = "",
) -> dict:
    is_show = request.media_type == "show"

    type_media = "Le film"
    if is_show:
        type_media = "La série"

    details_se = ""
    if is_show and season_number is not None:
        if scope == "episode" and episode_number is not None:
            details_se = f"(Saison {season_number}, Épisode {episode_number})"
        elif scope == "season":
            details_se = f"(Saison {season_number})"
        elif scope == "season_start":
            details_se = f"(Premier épisode de la Saison {season_number})"
        elif scope == "season_complete":
            details_se = f"(Saison {season_number} complète)"
        elif scope == "series_complete":
            details_se = "(Série complète)"

    langue_str = ""
    if language == "vo":
        langue_str = "en VO"
    elif language == "vf":
        langue_str = "en VF"

    return {
        "{titre}": request.title or "",
        "{type}": type_media,
        "{annee}": str(request.year) if request.year else "",
        "{affiche}": request.poster_url or "",
        "{details_saison_episode}": details_se,
        "{langue}": langue_str,
        "{nom_utilisateur}": display_name
        or getattr(request, "plex_user", None)
        or getattr(request, "plex_user_id", None)
        or "",
        "{synopsis}": request.overview or "",
        "{raison}": reason or "Erreur inconnue",
        "{corrections}": _format_corrections(corrections) or "- Correction effectuée",
        "{note_correction}": correction_note.strip() if correction_note else "",
        "{media_type_et_titre}": f"{type_media} {request.title or ''}".strip(),
    }


def _build_jinja_ctx(request: MediaRequest | LibraryItem, display_name: str | None = None) -> dict:
    is_show = request.media_type == "show"
    return {
        "_title": request.title or "",
        "_year": request.year,
        "_poster_url": request.poster_url or "",
        "_plex_user": display_name
        or getattr(request, "plex_user", None)
        or getattr(request, "plex_user_id", None)
        or "",
        "_media_type": request.media_type,
        "_media_type_label": "Série" if is_show else "Film",
        "_overview": request.overview or "",
        "_genres": getattr(request, "genres", "") or "",
    }


def _resolve_str_setting(settings, field):
    val = getattr(settings, field, None)
    return val if isinstance(val, str) else None


def render_template(template_str: str, tags: dict, jinja_ctx: dict) -> str:
    # 1. Remplacement des tags intelligents
    rendered_md = template_str
    for tag, value in tags.items():
        rendered_md = rendered_md.replace(tag, str(value))

    # Nettoyage des espaces inutiles
    rendered_md = rendered_md.replace("  ", " ")

    # 2. Conversion Markdown -> HTML
    html_content = markdown.markdown(rendered_md)

    # 3. Injection dans la coquille Jinja2 globale
    try:
        html = _EMAIL_SHELL.replace("__CONTENT__", html_content)
        return _jinja_env.from_string(html).render(**jinja_ctx)
    except TemplateError as e:
        logger.error(f"Template render error: {e}")
        return f"<p>Erreur de template shell : {e}</p>"


def render_subject(template_str: str, tags: dict, fallback: str) -> str:
    rendered = template_str
    for tag, value in tags.items():
        rendered = rendered.replace(tag, str(value))
    rendered = rendered.replace("  ", " ")
    return rendered.strip() or fallback


async def _send_templated(
    settings: Settings,
    request: MediaRequest | LibraryItem,
    recipient: str,
    display_name: str | None = None,
    *,
    template_field: str,
    default_template: str,
    subject_field: str,
    default_subject: str,
    subject_fallback: str,
    tags: dict,
    extra_jinja_ctx: dict | None = None,
):
    jinja_ctx = _build_jinja_ctx(request, display_name)
    if extra_jinja_ctx:
        jinja_ctx.update(extra_jinja_ctx)

    template_str = _resolve_str_setting(settings, template_field) or default_template
    html = render_template(template_str, tags, jinja_ctx)

    subject_str = _resolve_str_setting(settings, subject_field) or default_subject
    subject = render_subject(subject_str, tags, fallback=subject_fallback)

    await _send(settings, recipient, subject, html)


async def send_request_notification(
    settings: Settings, request: MediaRequest, recipient: str, display_name: str | None = None
):
    tags = _build_tags(request, display_name)
    extra_ctx = get_shared_email_parts(settings)
    extra_ctx.update(get_event_visuals(settings, "request"))
    extra_ctx["_tmdb_url"] = build_tmdb_url(request)
    await _send_templated(
        settings,
        request,
        recipient,
        display_name,
        template_field="email_request_template",
        default_template=DEFAULT_REQUEST_TEMPLATE,
        subject_field="email_request_subject",
        default_subject="[Plexarr] Nouvelle demande : {titre}",
        subject_fallback=f"[Plexarr] Nouvelle demande : {request.title}",
        tags=tags,
        extra_jinja_ctx=extra_ctx,
    )


async def send_available_notification(
    settings: Settings,
    request: MediaRequest,
    recipient: str,
    display_name: str | None = None,
    *,
    scope: str = "movie",
    language: str | None = None,
    is_upgrade: bool = False,
    season_number: int | None = None,
    episode_number: int | None = None,
):
    template_field = "email_upgrade_template" if is_upgrade else "email_available_template"
    subject_field = "email_upgrade_subject" if is_upgrade else "email_available_subject"
    default_template = DEFAULT_UPGRADE_TEMPLATE if is_upgrade else DEFAULT_AVAILABLE_TEMPLATE
    event_type = "upgrade" if is_upgrade else "available"

    if is_upgrade:
        default_subject = "[Plexarr] Mise à jour VF : {titre}"
    else:
        default_subject = "[Plexarr] Disponible : {titre}"

    tags = _build_tags(
        request,
        display_name,
        scope=scope,
        language=language,
        is_upgrade=is_upgrade,
        season_number=season_number,
        episode_number=episode_number,
    )

    extra_ctx = get_shared_email_parts(settings)
    extra_ctx.update(get_event_visuals(settings, event_type))
    # Exception VO : distinction visuelle bleue automatique par-dessus les valeurs éditables.
    if not is_upgrade and language == "vo":
        extra_ctx["_accent_color"] = "#0d6efd"
        extra_ctx["_badge_text"] = "Disponible en VO"

    extra_ctx["_tmdb_url"] = build_tmdb_url(request)
    extra_ctx["_plex_deep_link"] = await resolve_plex_deep_link(settings, request)

    await _send_templated(
        settings,
        request,
        recipient,
        display_name,
        template_field=template_field,
        default_template=default_template,
        subject_field=subject_field,
        default_subject=default_subject,
        subject_fallback=f"[Plexarr] Disponible : {request.title}",
        tags=tags,
        extra_jinja_ctx=extra_ctx,
    )


async def _send(settings: Settings, recipient: str, subject: str, html: str):
    if not all([settings.smtp_host, settings.smtp_user, settings.smtp_password, settings.smtp_from]):
        logger.warning("SMTP not configured, skipping email")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = recipient
    msg.attach(MIMEText(html, "html"))

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
    tags = _build_tags(request, display_name, reason=reason)
    extra_ctx = get_shared_email_parts(settings)
    extra_ctx.update(get_event_visuals(settings, "failure"))
    extra_ctx["_tmdb_url"] = build_tmdb_url(request)
    await _send_templated(
        settings,
        request,
        recipient,
        display_name,
        template_field="email_failure_template",
        default_template=DEFAULT_FAILURE_TEMPLATE,
        subject_field="email_failure_subject",
        default_subject="[Plexarr] Échec de transmission : {titre}",
        subject_fallback=f"[Plexarr] Échec de transmission : {request.title}",
        tags=tags,
        extra_jinja_ctx=extra_ctx,
    )


def build_correction_email(
    settings: Settings,
    media: MediaRequest | LibraryItem,
    display_name: str,
    corrections: list[str],
    correction_note: str = "",
    *,
    plex_deep_link: str | None = None,
    scope: str = "movie",
    season_number: int | None = None,
    episode_number: int | None = None,
) -> tuple[str, str]:
    tags = _build_tags(
        media,
        display_name=display_name,
        scope=scope,
        season_number=season_number,
        episode_number=episode_number,
        corrections=corrections,
        correction_note=correction_note,
    )
    extra_ctx = get_shared_email_parts(settings)
    extra_ctx.update(get_event_visuals(settings, "correction"))
    extra_ctx["_requester_label"] = "Destinataire"
    extra_ctx["_tmdb_url"] = build_tmdb_url(media)
    extra_ctx["_plex_deep_link"] = plex_deep_link

    jinja_ctx = _build_jinja_ctx(media, display_name)
    jinja_ctx.update(extra_ctx)

    template_str = _resolve_str_setting(settings, "email_correction_template") or DEFAULT_CORRECTION_TEMPLATE
    subject_str = (
        _resolve_str_setting(settings, "email_correction_subject")
        or "[Plexarr] Correction : {titre} {details_saison_episode}"
    )
    subject = render_subject(subject_str, tags, fallback=f"[Plexarr] Correction : {media.title}")
    html = render_template(template_str, tags, jinja_ctx)
    return subject, html


async def send_correction_notification(
    settings: Settings,
    media: MediaRequest | LibraryItem,
    recipient: str,
    display_name: str,
    corrections: list[str],
    correction_note: str = "",
    *,
    scope: str = "movie",
    season_number: int | None = None,
    episode_number: int | None = None,
):
    plex_link = await resolve_plex_deep_link(settings, media)
    subject, html = build_correction_email(
        settings,
        media,
        display_name,
        corrections,
        correction_note,
        plex_deep_link=plex_link,
        scope=scope,
        season_number=season_number,
        episode_number=episode_number,
    )
    await _send(settings, recipient, subject, html)


async def test_smtp(settings: Settings, test_recipient: str) -> tuple[bool, str]:
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
