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

DEFAULT_REQUEST_TEMPLATE = """<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#141414;font-family:Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:auto">
  <tr><td style="background:#e5a00d;padding:24px;text-align:center">
    <h1 style="color:#fff;margin:0;font-size:22px">Nouvelle demande Plex</h1>
  </td></tr>
  <tr><td style="background:#1f1f1f;padding:28px;color:#fff">
    {% if poster_url %}
    <img src="{{ poster_url }}" style="width:110px;float:right;border-radius:8px;margin:0 0 12px 20px" alt="poster">
    {% endif %}
    <h2 style="margin:0 0 8px">{{ title }}{% if year %} <span style="color:#aaa;font-weight:normal">({{ year }})</span>{% endif %}</h2>
    <p style="margin:4px 0;color:#aaa">
      <strong style="color:#e5a00d">Type :</strong> {{ media_type_label }}&nbsp;&nbsp;
      <strong style="color:#e5a00d">Demandé par :</strong> {{ plex_user }}
    </p>
    {% if genres %}<p style="margin:4px 0;color:#888;font-size:13px">{{ genres }}</p>{% endif %}
    {% if overview %}
    <p style="margin:16px 0 0;color:#ccc;font-size:14px;line-height:1.6;clear:both">{{ overview }}</p>
    {% endif %}
    <hr style="border:none;border-top:1px solid #333;margin:20px 0">
    <p style="color:#888;font-size:12px;margin:0">
      Vous recevrez un autre email dès que le contenu sera disponible sur votre serveur Plex.
    </p>
  </td></tr>
</table>
</body></html>"""

DEFAULT_AVAILABLE_TEMPLATE = """<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#141414;font-family:Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:auto">
  <tr><td style="background:#1db954;padding:24px;text-align:center">
    <h1 style="color:#fff;margin:0;font-size:22px">Disponible sur Plex !</h1>
  </td></tr>
  <tr><td style="background:#1f1f1f;padding:28px;color:#fff">
    {% if poster_url %}
    <img src="{{ poster_url }}" style="width:110px;float:right;border-radius:8px;margin:0 0 12px 20px" alt="poster">
    {% endif %}
    <h2 style="margin:0 0 8px">{{ title }}{% if year %} <span style="color:#aaa;font-weight:normal">({{ year }})</span>{% endif %}</h2>
    <p style="margin:4px 0;color:#aaa">
      <strong style="color:#1db954">Demandé par :</strong> {{ plex_user }}
    </p>
    {% if genres %}<p style="margin:4px 0;color:#888;font-size:13px">{{ genres }}</p>{% endif %}
    <p style="margin:20px 0 0;font-size:16px">
      {{ media_type_label_cap }} est maintenant disponible sur votre serveur Plex. Bonne séance !
    </p>
    <hr style="border:none;border-top:1px solid #333;margin:20px 0;clear:both">
    <p style="color:#888;font-size:12px;margin:0">Géré par Plex RSS Monitor</p>
  </td></tr>
</table>
</body></html>"""


DEFAULT_FAILURE_TEMPLATE = """<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#141414;font-family:Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:auto">
  <tr><td style="background:#dc3545;padding:24px;text-align:center">
    <h1 style="color:#fff;margin:0;font-size:22px">Demande non transmise</h1>
  </td></tr>
  <tr><td style="background:#1f1f1f;padding:28px;color:#fff">
    {% if poster_url %}
    <img src="{{ poster_url }}" style="width:110px;float:right;border-radius:8px;margin:0 0 12px 20px" alt="poster">
    {% endif %}
    <h2 style="margin:0 0 8px">{{ title }}{% if year %} <span style="color:#aaa;font-weight:normal">({{ year }})</span>{% endif %}</h2>
    <p style="margin:4px 0;color:#aaa">
      <strong style="color:#dc3545">Type :</strong> {{ media_type_label }}&nbsp;&nbsp;
      <strong style="color:#dc3545">Demandé par :</strong> {{ plex_user }}
    </p>
    <p style="margin:16px 0;padding:12px;background:#2a2a2a;border-left:4px solid #dc3545;color:#f8d7da;font-size:13px">
      {{ reason }}
    </p>
    <p style="color:#aaa;font-size:13px">
      La demande a bien été enregistrée. Elle sera retransmise lors du prochain polling si le problème est résolu.
    </p>
  </td></tr>
</table>
</body></html>"""


DEFAULT_VO_ONLY_TEMPLATE = """<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#141414;font-family:Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:auto">
  <tr><td style="background:#0d6efd;padding:24px;text-align:center">
    <h1 style="color:#fff;margin:0;font-size:22px">Disponible en VO</h1>
  </td></tr>
  <tr><td style="background:#1f1f1f;padding:28px;color:#fff">
    {% if poster_url %}
    <img src="{{ poster_url }}" style="width:110px;float:right;border-radius:8px;margin:0 0 12px 20px" alt="poster">
    {% endif %}
    <h2 style="margin:0 0 8px">{{ title }}{% if year %} <span style="color:#aaa;font-weight:normal">({{ year }})</span>{% endif %}</h2>
    <p style="margin:4px 0;color:#aaa">
      <strong style="color:#0d6efd">Demandé par :</strong> {{ plex_user }}
    </p>
    <p style="margin:20px 0 0;font-size:16px">
      {{ media_type_label_cap }} est disponible sur Plex, mais <strong>uniquement en version originale</strong> pour le moment.
    </p>
    <p style="margin:16px 0 0;color:#ccc;font-size:14px;line-height:1.6">
      Vous serez automatiquement prévenu dès qu'une piste audio française (VF) sera disponible.
    </p>
    <hr style="border:none;border-top:1px solid #333;margin:20px 0;clear:both">
    <p style="color:#888;font-size:12px;margin:0">Géré par Plex RSS Monitor — suivi VFF</p>
  </td></tr>
</table>
</body></html>"""


DEFAULT_VF_AVAILABLE_TEMPLATE = """<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#141414;font-family:Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:auto">
  <tr><td style="background:#1db954;padding:24px;text-align:center">
    <h1 style="color:#fff;margin:0;font-size:22px">La VF est disponible !</h1>
  </td></tr>
  <tr><td style="background:#1f1f1f;padding:28px;color:#fff">
    {% if poster_url %}
    <img src="{{ poster_url }}" style="width:110px;float:right;border-radius:8px;margin:0 0 12px 20px" alt="poster">
    {% endif %}
    <h2 style="margin:0 0 8px">{{ title }}{% if year %} <span style="color:#aaa;font-weight:normal">({{ year }})</span>{% endif %}</h2>
    <p style="margin:4px 0;color:#aaa">
      <strong style="color:#1db954">Demandé par :</strong> {{ plex_user }}
    </p>
    <p style="margin:20px 0 0;font-size:16px">
      Bonne nouvelle ! {{ media_type_label_cap }} est maintenant disponible <strong>en version française</strong> sur votre serveur Plex.
    </p>
    <hr style="border:none;border-top:1px solid #333;margin:20px 0;clear:both">
    <p style="color:#888;font-size:12px;margin:0">Géré par Plex RSS Monitor — suivi VFF</p>
  </td></tr>
</table>
</body></html>"""


DEFAULT_PARTIALLY_AVAILABLE_TEMPLATE = """<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#141414;font-family:Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:auto">
  <tr><td style="background:#e5a00d;padding:24px;text-align:center">
    <h1 style="color:#fff;margin:0;font-size:22px">Partiellement disponible</h1>
  </td></tr>
  <tr><td style="background:#1f1f1f;padding:28px;color:#fff">
    {% if poster_url %}
    <img src="{{ poster_url }}" style="width:110px;float:right;border-radius:8px;margin:0 0 12px 20px" alt="poster">
    {% endif %}
    <h2 style="margin:0 0 8px">{{ title }}{% if year %} <span style="color:#aaa;font-weight:normal">({{ year }})</span>{% endif %}</h2>
    <p style="margin:4px 0;color:#aaa">
      <strong style="color:#e5a00d">Demandé par :</strong> {{ plex_user }}
    </p>
    <p style="margin:20px 0 0;font-size:16px">
      {{ media_type_label_cap }} est en cours de diffusion : <strong>{{ episodes_available }}/{{ episodes_aired }}</strong>
      épisode(s) diffusé(s) sont déjà disponibles sur votre serveur Plex.
    </p>
    <p style="margin:16px 0 0;color:#ccc;font-size:14px;line-height:1.6">
      Vous serez prévenu à nouveau dès que la série sera intégralement disponible.
    </p>
    <hr style="border:none;border-top:1px solid #333;margin:20px 0;clear:both">
    <p style="color:#888;font-size:12px;margin:0">Géré par Plex RSS Monitor</p>
  </td></tr>
</table>
</body></html>"""


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


async def send_request_notification(
    settings: Settings, request: MediaRequest, recipient: str, display_name: str | None = None
):
    """Envoie l'email de confirmation de demande."""
    ctx = _build_context(request, display_name)
    template = settings.email_request_template if isinstance(settings.email_request_template, str) else None
    template = template or DEFAULT_REQUEST_TEMPLATE
    html = render_template(template, ctx)
    subject_tmpl = settings.email_request_subject if isinstance(settings.email_request_subject, str) else None
    subject_tmpl = subject_tmpl or "[Plex] Nouvelle demande : {{ title }}"
    subject = render_template(subject_tmpl, ctx)
    if subject.startswith("<p>Erreur de template"):
        subject = f"[Plex] Nouvelle demande : {request.title}"
    await _send(settings, recipient, subject, html)


async def send_available_notification(
    settings: Settings, request: MediaRequest, recipient: str, display_name: str | None = None
):
    """Envoie l'email de notification de disponibilité."""
    ctx = _build_context(request, display_name)
    template = settings.email_available_template if isinstance(settings.email_available_template, str) else None
    template = template or DEFAULT_AVAILABLE_TEMPLATE
    html = render_template(template, ctx)
    subject_tmpl = settings.email_available_subject if isinstance(settings.email_available_subject, str) else None
    subject_tmpl = subject_tmpl or "[Plex] Disponible : {{ title }}"
    subject = render_template(subject_tmpl, ctx)
    if subject.startswith("<p>Erreur de template"):
        subject = f"[Plex] Disponible : {request.title}"
    await _send(settings, recipient, subject, html)


async def send_vo_only_notification(
    settings: Settings, request: MediaRequest, recipient: str, display_name: str | None = None
):
    """Envoie l'email « disponible mais en VO uniquement » (suivi VFF)."""
    ctx = _build_context(request, display_name)
    html = render_template(DEFAULT_VO_ONLY_TEMPLATE, ctx)
    subject = f"[Plex] Disponible en VO : {request.title}"
    await _send(settings, recipient, subject, html)


async def send_vf_available_notification(
    settings: Settings, request: MediaRequest, recipient: str, display_name: str | None = None
):
    """Envoie l'email « la VF est maintenant disponible » (suivi VFF)."""
    ctx = _build_context(request, display_name)
    html = render_template(DEFAULT_VF_AVAILABLE_TEMPLATE, ctx)
    subject = f"[Plex] VF disponible : {request.title}"
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
    subject = f"[Plex] Partiellement disponible : {request.title} ({reason})" if reason else f"[Plex] Partiellement disponible : {request.title}"
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
    """Envoie l'email d'échec de transmission."""
    ctx = _build_context(request, display_name)
    ctx["reason"] = reason or "Erreur inconnue"
    template = settings.email_failure_template if isinstance(settings.email_failure_template, str) else None
    template = template or DEFAULT_FAILURE_TEMPLATE
    html = render_template(template, ctx)
    subject_tmpl = settings.email_failure_subject if isinstance(settings.email_failure_subject, str) else None
    subject_tmpl = subject_tmpl or "[Plex] Échec de transmission : {{ title }}"
    subject = render_template(subject_tmpl, ctx)
    if subject.startswith("<p>Erreur de template"):
        subject = f"[Plex] Échec de transmission : {request.title}"
    await _send(settings, recipient, subject, html)


async def test_smtp(settings: Settings, test_recipient: str) -> tuple[bool, str]:
    """Envoie un email de test pour valider la configuration SMTP.

    Returns:
        (success, message)
    """
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "[Plex RSS] Test SMTP"
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
