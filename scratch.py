import re

with open("app/services/email_service.py", "r", encoding="utf-8") as f:
    original = f.read()

new_content = """import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
import markdown
from jinja2 import TemplateError
from jinja2.sandbox import SandboxedEnvironment

from ..models import MediaRequest, Settings

logger = logging.getLogger(__name__)

_jinja_env = SandboxedEnvironment()

_EMAIL_SHELL = \"\"\"<!DOCTYPE html>
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

      <tr><td style="background:{{ _accent_color }};padding:22px 20px;text-align:center">
        <div style="color:#ffffff;font-size:11px;font-weight:bold;letter-spacing:1px;text-transform:uppercase">{{ _badge_text }}</div>
        <div style="color:#ffffff;font-size:21px;font-weight:bold;margin-top:5px;line-height:1.25">{{ _headline_text }}</div>
      </td></tr>

      <tr><td style="padding:22px 20px 4px">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          {% if _poster_url %}<td valign="top" width="116" style="padding-right:16px">
            <img src="{{ _poster_url }}" width="100" alt="" style="width:100px;height:auto;border-radius:8px;display:block;border:1px solid #444444">
          </td>{% endif %}
          <td valign="top">
            <div style="color:#ffffff;font-size:19px;font-weight:bold;line-height:1.3">{{ _title }}{% if _year %} <span style="color:#888888;font-weight:normal">({{ _year }})</span>{% endif %}</div>
            <div style="margin-top:9px">
              <span style="display:inline-block;background:#2a2a2a;color:#bbbbbb;font-size:11px;padding:3px 10px;border-radius:20px;margin:0 4px 5px 0">{{ _media_type_label }}</span>
              {% if _genres %}{% for g in _genres.split(',') %}{% if g.strip() %}<span style="display:inline-block;background:#242424;color:{{ _accent_color }};font-size:11px;padding:3px 10px;border-radius:20px;margin:0 4px 5px 0">{{ g.strip() }}</span>{% endif %}{% endfor %}{% endif %}
            </div>
            <div style="margin-top:10px;color:#999999;font-size:13px"><span style="color:#e5a00d;font-weight:bold">Demandé par</span>&nbsp;&nbsp;{{ _plex_user }}</div>
          </td>
        </tr></table>
      </td></tr>

      {% if _overview and _show_synopsis %}<tr><td style="padding:12px 20px 2px">
        <div style="color:#777777;font-size:10px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:5px">Synopsis</div>
        <div style="color:#cccccc;font-size:13.5px;line-height:1.65">{{ _overview }}</div>
      </td></tr>{% endif %}

      <tr><td style="padding:16px 20px 2px">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td style="background:#1c1c1c;border-left:3px solid {{ _accent_color }};padding:13px 15px;color:#dddddd;font-size:14px;line-height:1.6">
            __CONTENT__
          </td>
        </tr></table>
      </td></tr>
      
      <tr><td style="padding:15px 20px 20px"></td></tr>

      <tr><td style="padding:20px;text-align:center;border-top:1px solid #2a2a2a">
        <div style="color:#888888;font-size:12px">Géré par <span style="color:#e5a00d;font-weight:bold">Plexarr</span></div>
        <div style="color:#555555;font-size:11px;margin-top:5px">Logiciel créé par <a href="https://github.com/remi-deher/plex-rss" style="color:#e5a00d;text-decoration:none">DEHER Rémi</a></div>
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>\"\"\"

DEFAULT_REQUEST_TEMPLATE = \"\"\"Votre demande est bien enregistrée.

*Plexarr vous préviendra automatiquement dès que le contenu sera disponible sur votre serveur Plex.*\"\"\"

DEFAULT_AVAILABLE_TEMPLATE = \"\"\"**{media_type_et_titre}** {details_saison_episode} est disponible {qualite}.

*Vous recevrez une nouvelle notification si une meilleure qualité devient disponible.*\"\"\"

DEFAULT_UPGRADE_TEMPLATE = \"\"\"**{media_type_et_titre}** {details_saison_episode} vient d'être mis à jour !

La version **{qualite}** est maintenant disponible sur Plex.\"\"\"

DEFAULT_FAILURE_TEMPLATE = \"\"\"Une erreur est survenue lors de la transmission à Sonarr/Radarr.

**Détails de l'erreur :**
{raison}

*La demande reste enregistrée. Plexarr réessaiera automatiquement lors de la prochaine vérification si le problème est résolu.*\"\"\"

def _build_tags(request: MediaRequest, display_name: str | None = None, scope: str = "movie", language: str | None = None, is_upgrade: bool = False, season_number: int | None = None, episode_number: int | None = None, reason: str = "") -> dict:
    is_show = request.media_type == "show"
    
    type_media = "Le film"
    if is_show:
        type_media = "La série"

    details_se = ""
    if is_show and season_number is not None:
        if scope == 'episode' and episode_number is not None:
            details_se = f"(Saison {season_number}, Épisode {episode_number})"
        elif scope == 'season_start':
            details_se = f"(Premier épisode de la Saison {season_number})"
        elif scope == 'season_complete':
            details_se = f"(Saison {season_number} complète)"
        elif scope == 'series_complete':
            details_se = f"(Série complète)"

    qualite_str = ""
    if language == 'vo':
        qualite_str = "en VO"
    elif language == 'vf':
        qualite_str = "en VF"

    return {
        "{titre}": request.title or "",
        "{type}": type_media,
        "{annee}": str(request.year) if request.year else "",
        "{affiche}": request.poster_url or "",
        "{details_saison_episode}": details_se,
        "{qualite}": qualite_str,
        "{nom_utilisateur}": display_name or request.plex_user or request.plex_user_id or "",
        "{synopsis}": request.overview or "",
        "{raison}": reason or "Erreur inconnue",
        "{media_type_et_titre}": f"{type_media} {request.title or ''}".strip(),
    }

def _build_jinja_ctx(request: MediaRequest, display_name: str | None = None) -> dict:
    is_show = request.media_type == "show"
    return {
        "_title": request.title or "",
        "_year": request.year,
        "_poster_url": request.poster_url or "",
        "_plex_user": display_name or request.plex_user or request.plex_user_id or "",
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
    request: MediaRequest,
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
        extra_jinja_ctx={
            "_accent_color": "#e5a00d",
            "_badge_text": "Nouvelle demande",
            "_headline_text": "Demande enregistrée",
            "_show_synopsis": True,
        }
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
    
    if is_upgrade:
        default_subject = "[Plexarr] Mise à jour VF : {titre}"
        accent_color = "#1db954"
        badge = "Mise à jour VF"
        headline = f"VF disponible"
    else:
        default_subject = "[Plexarr] Disponible : {titre}"
        accent_color = "#0d6efd" if language == "vo" else "#1db954"
        badge = "Disponible en VO" if language == "vo" else "Disponible"
        headline = f"Média disponible"

    tags = _build_tags(request, display_name, scope=scope, language=language, is_upgrade=is_upgrade, season_number=season_number, episode_number=episode_number)

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
        extra_jinja_ctx={
            "_accent_color": accent_color,
            "_badge_text": badge,
            "_headline_text": headline,
            "_show_synopsis": True,
        },
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
        extra_jinja_ctx={
            "_accent_color": "#dc3545",
            "_badge_text": "Action requise",
            "_headline_text": "Demande non transmise",
            "_show_synopsis": False,
        },
    )

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
"""

with open("app/services/email_service.py", "w", encoding="utf-8") as f:
    f.write(new_content)
