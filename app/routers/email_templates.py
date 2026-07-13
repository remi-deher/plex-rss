import json
from typing import Optional

import markdown
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import sqlalchemy

from ..database import get_db_async
from ..dependencies import get_settings_or_404, require_admin
from ..models import MediaRequest, PlexUser, Settings
from ..services.email_service import (
    DEFAULT_AVAILABLE_TEMPLATE,
    DEFAULT_CORRECTION_TEMPLATE,
    DEFAULT_FAILURE_TEMPLATE,
    DEFAULT_REQUEST_TEMPLATE,
    DEFAULT_UPGRADE_TEMPLATE,
    FONT_FAMILY_PRESETS,
    SYNOPSIS_FONT_SIZE_PRESETS,
    _build_jinja_ctx,
    _build_tags,
    build_tmdb_url,
    get_event_visuals,
    get_shared_email_parts,
    render_subject,
    render_template,
    resolve_plex_deep_link,
)
from ..services.email_service import _send as smtp_send
from ..services.notification_catalog import get_event

router = APIRouter(tags=["email-templates"], dependencies=[Depends(require_admin)])

_EVENT_TYPES = ("request", "available", "upgrade", "failure", "correction")


@router.get("/settings/email-templates")
def email_templates_redirect():
    return RedirectResponse("/settings?tab=notifications", status_code=308)


SAMPLE_CONTEXT = {
    "title": "Breaking Bad",
    "year": 2008,
    "poster_url": "https://image.tmdb.org/t/p/w300/ggFHVNu6YYI5L9pCfOacjizRGt.jpg",
    "plex_user": "Jean Dupont",
    "media_type": "show",
    "media_type_label": "Série",
    "media_type_label_cap": "La série",
    "overview": "Un professeur de chimie atteint d'un cancer du poumon se lance dans la fabrication et la vente de méthamphétamine afin de subvenir aux besoins de sa famille.",
    "genres": "Crime, Drame, Thriller",
}


def _create_dummy_request() -> MediaRequest:
    req = MediaRequest()
    req.title = "Breaking Bad"
    req.year = 2008
    req.plex_user = "Jean Dupont"
    req.media_type = "show"
    req.poster_url = "https://image.tmdb.org/t/p/w300/ggFHVNu6YYI5L9pCfOacjizRGt.jpg"
    req.overview = "Un professeur de chimie atteint d'un cancer du poumon se lance dans la fabrication et la vente de méthamphétamine afin de subvenir aux besoins de sa famille."
    setattr(
        req, "genres", "Crime, Drame, Thriller"
    )  # attribut dynamique, non déclaré sur MediaRequest (voir _build_jinja_ctx)
    req.tmdb_id = "1396"  # vrai ID TMDB de Breaking Bad, pour que le lien TMDB de démo soit réel
    return req


# Le catalogue de notifications (notification_catalog.EVENTS) utilise "failed" et n'a pas
# d'entrée "upgrade" (qui est une variante d'"available") : traduction des 4 clés de l'éditeur
# vers les clés du catalogue, pour le libellé/sujet par défaut uniquement.
_CATALOG_EVENT_KEY = {"upgrade": "available", "failure": "failed"}


def _parse_preview_variant(preview_variant: Optional[str]):
    """(scope, language, season_number, episode_number) pour un variant de preview donné."""
    if preview_variant == "movie_vo":
        return "movie", "vo", None, None
    if preview_variant == "movie_vf":
        return "movie", "vf", None, None
    if preview_variant == "episode":
        return "episode", None, 2, 1
    if preview_variant == "season_complete":
        return "season_complete", None, 2, None
    return "movie", None, None, None


class _EmailShellDraft(BaseModel):
    """Valeurs de brouillon (non enregistrées) pour la coquille email, en overrides des Settings."""

    header_brand: Optional[str] = None
    header_subtitle: Optional[str] = None
    footer_template: Optional[str] = None
    accent_color: Optional[str] = None
    badge_text: Optional[str] = None
    headline_text: Optional[str] = None
    show_synopsis: Optional[bool] = None
    show_poster: Optional[bool] = None
    show_genres: Optional[bool] = None
    show_requester: Optional[bool] = None
    requester_label: Optional[str] = None
    brand_color: Optional[str] = None
    show_header_subtitle: Optional[bool] = None
    poster_width: Optional[int] = None
    media_layout: Optional[str] = None
    bg_color: Optional[str] = None
    card_bg_color: Optional[str] = None
    font_family: Optional[str] = None
    card_width: Optional[int] = None
    card_border_radius: Optional[int] = None
    synopsis_font_size: Optional[str] = None
    show_tmdb_link: Optional[bool] = None
    show_plex_button: Optional[bool] = None


def _apply_draft_overrides(jinja_ctx: dict, draft: _EmailShellDraft) -> None:
    if draft.header_brand is not None:
        jinja_ctx["_header_brand"] = draft.header_brand
    if draft.header_subtitle is not None:
        jinja_ctx["_header_subtitle"] = draft.header_subtitle
    if draft.footer_template is not None:
        jinja_ctx["_footer_html"] = markdown.markdown(draft.footer_template)
    if draft.accent_color is not None:
        jinja_ctx["_accent_color"] = draft.accent_color
    if draft.badge_text is not None:
        jinja_ctx["_badge_text"] = draft.badge_text
    if draft.headline_text is not None:
        jinja_ctx["_headline_text"] = draft.headline_text
    if draft.show_synopsis is not None:
        jinja_ctx["_show_synopsis"] = draft.show_synopsis
    if draft.show_poster is not None:
        jinja_ctx["_show_poster"] = draft.show_poster
    if draft.show_genres is not None:
        jinja_ctx["_show_genres"] = draft.show_genres
    if draft.show_requester is not None:
        jinja_ctx["_show_requester"] = draft.show_requester
    if draft.requester_label is not None:
        jinja_ctx["_requester_label"] = draft.requester_label
    if draft.brand_color is not None:
        jinja_ctx["_brand_color"] = draft.brand_color
    if draft.show_header_subtitle is not None:
        jinja_ctx["_show_header_subtitle"] = draft.show_header_subtitle
    if draft.poster_width is not None:
        jinja_ctx["_poster_width"] = draft.poster_width
    if draft.media_layout is not None:
        jinja_ctx["_media_layout"] = draft.media_layout
    if draft.bg_color is not None:
        jinja_ctx["_bg_color"] = draft.bg_color
    if draft.card_bg_color is not None:
        jinja_ctx["_card_bg_color"] = draft.card_bg_color
    if draft.font_family is not None:
        jinja_ctx["_font_family"] = FONT_FAMILY_PRESETS.get(draft.font_family, FONT_FAMILY_PRESETS["arial"])
    if draft.card_width is not None:
        jinja_ctx["_card_width"] = draft.card_width
    if draft.card_border_radius is not None:
        jinja_ctx["_card_border_radius"] = draft.card_border_radius
    if draft.synopsis_font_size is not None:
        jinja_ctx["_synopsis_font_size"] = SYNOPSIS_FONT_SIZE_PRESETS.get(
            draft.synopsis_font_size, SYNOPSIS_FONT_SIZE_PRESETS["normal"]
        )
    if draft.show_tmdb_link is not None:
        jinja_ctx["_show_tmdb_link"] = draft.show_tmdb_link
    if draft.show_plex_button is not None:
        jinja_ctx["_show_plex_button"] = draft.show_plex_button


def _build_preview_jinja_ctx(
    settings, event_type: str, req, display_name: str, language: Optional[str], draft: _EmailShellDraft
) -> dict:
    jinja_ctx = _build_jinja_ctx(req, display_name=display_name)
    jinja_ctx.update(get_shared_email_parts(settings))
    jinja_ctx.update(get_event_visuals(settings, event_type))
    # Exception VO : même règle que send_available_notification (email_service.py).
    if event_type == "available" and language == "vo":
        jinja_ctx["_accent_color"] = "#0d6efd"
        jinja_ctx["_badge_text"] = "Disponible en VO"
    _apply_draft_overrides(jinja_ctx, draft)
    if event_type == "correction":
        jinja_ctx["_requester_label"] = "Destinataire"
    return jinja_ctx


class PreviewRequest(_EmailShellDraft):
    template: str
    subject: str
    type: str = "request"
    user_id: Optional[int] = None
    preview_variant: Optional[str] = None


@router.post("/api/email-preview")
async def preview_email(body: PreviewRequest, db: AsyncSession = Depends(get_db_async)):
    event_type = body.type if body.type in _EVENT_TYPES else "request"
    is_upgrade = event_type == "upgrade"
    # "upgrade" n'est pas un évènement du catalogue à part entière : c'est une variante
    # de "available" (voir email_service.send_available_notification). On réutilise donc
    # le libellé/sujet par défaut d'"available" pour le fallback.
    event_def = get_event(_CATALOG_EVENT_KEY.get(event_type, event_type))
    req = _create_dummy_request()
    display_name = "Jean Dupont"

    scope, language, season_number, episode_number = (
        _parse_preview_variant(body.preview_variant)
        if event_type in ("available", "upgrade")
        else ("movie", None, None, None)
    )

    settings = (await db.execute(select(Settings))).scalars().first()
    recipient_email = "jean.dupont@plex.local"
    if body.user_id:
        user = (await db.execute(select(PlexUser).filter(PlexUser.id == body.user_id))).scalars().first()
        if user:
            display_name = user.custom_name or user.display_name or user.plex_user_id
            recipient_email = user.notification_email or user.plex_email or "utilisateur@plex.local"

    tags = _build_tags(
        req,
        display_name=display_name,
        scope=scope,
        language=language,
        is_upgrade=is_upgrade,
        season_number=season_number,
        episode_number=episode_number,
        reason="Impossible de contacter Sonarr." if event_type == "failure" else "",
        corrections=["Son corrigé", "Sous-titres resynchronisés"],
        correction_note="Note complémentaire : le fichier a été remplacé par une version corrigée."
        if event_type == "correction"
        else "",
    )

    jinja_ctx = _build_preview_jinja_ctx(settings, event_type, req, display_name, language, body)
    # Aperçu : jamais d'appel Plex réel (redéclenché à chaque frappe) — lien TMDB réel
    # (la demande factice a un vrai tmdb_id), lien Plex factice juste pour visualiser la mise en page.
    jinja_ctx["_tmdb_url"] = build_tmdb_url(req)
    jinja_ctx["_plex_deep_link"] = "#"

    generic_fallback = f"[Plexarr] {'Correction' if event_type == 'correction' else event_def.label} : {req.title}"
    default_subject = (
        "[Plexarr] Correction : {titre} {details_saison_episode}"
        if event_type == "correction"
        else event_def.default_subject
    )
    fallback_subject = (
        render_subject(default_subject, tags, fallback=generic_fallback) if default_subject else generic_fallback
    )
    rendered_subject = render_subject(body.subject, tags, fallback=fallback_subject)

    html = render_template(body.template, tags, jinja_ctx)

    header_html = f"""
    <div style="background:#2a2a2a; color:#fff; font-family:sans-serif; padding:12px 20px; border-bottom:1px solid #333; margin-bottom:15px; font-size:13px;">
      <div style="margin-bottom:4px;"><strong>Objet :</strong> <span style="color:#e5a00d; font-weight:bold;">{rendered_subject}</span></div>
      <div style="margin-bottom:4px;"><strong>De :</strong> {settings.smtp_from if settings else "plex-rss@monitor.local"}</div>
      <div><strong>À :</strong> {recipient_email}</div>
    </div>
    """

    if "<body>" in html:
        html = html.replace("<body>", f"<body>{header_html}")
    elif "<body style=" in html:
        parts = html.split("<body", 1)
        if len(parts) == 2:
            body_tag, rest = parts[1].split(">", 1)
            html = f"{parts[0]}<body{body_tag}>{header_html}{rest}"
    else:
        html = header_html + html

    return Response(content=html, media_type="text/html")


class SaveTemplates(BaseModel):
    email_request_template: str
    email_available_template: str
    email_upgrade_template: Optional[str] = None
    email_failure_template: str
    email_correction_template: Optional[str] = None
    email_request_subject: Optional[str] = None
    email_available_subject: Optional[str] = None
    email_upgrade_subject: Optional[str] = None
    email_failure_subject: Optional[str] = None
    email_correction_subject: Optional[str] = None
    email_header_brand: Optional[str] = None
    email_header_subtitle: Optional[str] = None
    email_footer_template: Optional[str] = None
    email_request_accent_color: Optional[str] = None
    email_request_badge_text: Optional[str] = None
    email_request_headline_text: Optional[str] = None
    email_request_show_synopsis: Optional[bool] = None
    email_available_accent_color: Optional[str] = None
    email_available_badge_text: Optional[str] = None
    email_available_headline_text: Optional[str] = None
    email_available_show_synopsis: Optional[bool] = None
    email_upgrade_accent_color: Optional[str] = None
    email_upgrade_badge_text: Optional[str] = None
    email_upgrade_headline_text: Optional[str] = None
    email_upgrade_show_synopsis: Optional[bool] = None
    email_failure_accent_color: Optional[str] = None
    email_failure_badge_text: Optional[str] = None
    email_failure_headline_text: Optional[str] = None
    email_failure_show_synopsis: Optional[bool] = None
    email_correction_accent_color: Optional[str] = None
    email_correction_badge_text: Optional[str] = None
    email_correction_headline_text: Optional[str] = None
    email_correction_show_synopsis: Optional[bool] = None
    email_show_poster: Optional[bool] = None
    email_show_genres: Optional[bool] = None
    email_show_requester: Optional[bool] = None
    email_requester_label: Optional[str] = None
    email_brand_color: Optional[str] = None
    email_show_header_subtitle: Optional[bool] = None
    email_poster_width: Optional[int] = None
    email_media_layout: Optional[str] = None
    email_bg_color: Optional[str] = None
    email_card_bg_color: Optional[str] = None
    email_font_family: Optional[str] = None
    email_card_width: Optional[int] = None
    email_card_border_radius: Optional[int] = None
    email_synopsis_font_size: Optional[str] = None
    email_show_tmdb_link: Optional[bool] = None
    email_show_plex_button: Optional[bool] = None


TEMPLATE_FIELDS = [
    "email_request_template",
    "email_available_template",
    "email_upgrade_template",
    "email_failure_template",
    "email_correction_template",
    "email_request_subject",
    "email_available_subject",
    "email_upgrade_subject",
    "email_failure_subject",
    "email_correction_subject",
    "email_header_brand",
    "email_header_subtitle",
    "email_footer_template",
    "email_request_accent_color",
    "email_request_badge_text",
    "email_request_headline_text",
    "email_request_show_synopsis",
    "email_available_accent_color",
    "email_available_badge_text",
    "email_available_headline_text",
    "email_available_show_synopsis",
    "email_upgrade_accent_color",
    "email_upgrade_badge_text",
    "email_upgrade_headline_text",
    "email_upgrade_show_synopsis",
    "email_failure_accent_color",
    "email_failure_badge_text",
    "email_failure_headline_text",
    "email_failure_show_synopsis",
    "email_correction_accent_color",
    "email_correction_badge_text",
    "email_correction_headline_text",
    "email_correction_show_synopsis",
    "email_show_poster",
    "email_show_genres",
    "email_show_requester",
    "email_requester_label",
    "email_brand_color",
    "email_show_header_subtitle",
    "email_poster_width",
    "email_media_layout",
    "email_bg_color",
    "email_card_bg_color",
    "email_font_family",
    "email_card_width",
    "email_card_border_radius",
    "email_synopsis_font_size",
    "email_show_tmdb_link",
    "email_show_plex_button",
]


@router.put("/api/email-templates")
async def save_templates(body: SaveTemplates, db: AsyncSession = Depends(get_db_async), s: Settings = Depends(get_settings_or_404)):
    s.email_templates_backup = json.dumps({field: getattr(s, field) for field in TEMPLATE_FIELDS})
    for field in TEMPLATE_FIELDS:
        setattr(s, field, getattr(body, field, None))
    await db.commit()
    return {"status": "ok"}


@router.post("/api/email-templates/restore-previous")
async def restore_previous_templates(db: AsyncSession = Depends(get_db_async), s: Settings = Depends(get_settings_or_404)):
    if not s.email_templates_backup:
        raise HTTPException(status_code=404, detail="Aucune sauvegarde précédente disponible")
    backup = json.loads(s.email_templates_backup)
    for field in TEMPLATE_FIELDS:
        setattr(s, field, backup.get(field))
    s.email_templates_backup = None
    await db.commit()
    return {"status": "ok"}


@router.post("/api/email-templates/reset")
async def reset_templates(db: AsyncSession = Depends(get_db_async), s: Settings = Depends(get_settings_or_404)):
    s.email_templates_backup = json.dumps({field: getattr(s, field) for field in TEMPLATE_FIELDS})
    s.email_request_template = DEFAULT_REQUEST_TEMPLATE
    s.email_available_template = DEFAULT_AVAILABLE_TEMPLATE
    s.email_upgrade_template = DEFAULT_UPGRADE_TEMPLATE
    s.email_failure_template = DEFAULT_FAILURE_TEMPLATE
    s.email_correction_template = DEFAULT_CORRECTION_TEMPLATE
    s.email_request_subject = None
    s.email_available_subject = None
    s.email_upgrade_subject = None
    s.email_failure_subject = None
    s.email_correction_subject = None
    for field in (
        "email_header_brand",
        "email_header_subtitle",
        "email_footer_template",
        "email_request_accent_color",
        "email_request_badge_text",
        "email_request_headline_text",
        "email_request_show_synopsis",
        "email_available_accent_color",
        "email_available_badge_text",
        "email_available_headline_text",
        "email_available_show_synopsis",
        "email_upgrade_accent_color",
        "email_upgrade_badge_text",
        "email_upgrade_headline_text",
        "email_upgrade_show_synopsis",
        "email_failure_accent_color",
        "email_failure_badge_text",
        "email_failure_headline_text",
        "email_failure_show_synopsis",
        "email_correction_accent_color",
        "email_correction_badge_text",
        "email_correction_headline_text",
        "email_correction_show_synopsis",
        "email_show_poster",
        "email_show_genres",
        "email_show_requester",
        "email_requester_label",
        "email_brand_color",
        "email_show_header_subtitle",
        "email_poster_width",
        "email_media_layout",
        "email_bg_color",
        "email_card_bg_color",
        "email_font_family",
        "email_card_width",
        "email_card_border_radius",
        "email_synopsis_font_size",
        "email_show_tmdb_link",
        "email_show_plex_button",
    ):
        setattr(s, field, None)
    await db.commit()
    return {"status": "ok"}


class TestSendRequest(_EmailShellDraft):
    template: str
    subject: str
    type: str = "request"
    user_id: Optional[int] = None
    preview_variant: Optional[str] = None


@router.post("/api/email-templates/test-send")
async def test_send_email(
    body: TestSendRequest, db: AsyncSession = Depends(get_db_async), settings: Settings = Depends(get_settings_or_404)
):
    recipient = (settings.admin_notification_email or "").strip()
    display_name = "Jean Dupont"
    if body.user_id:
        user = (await db.execute(select(PlexUser).filter(PlexUser.id == body.user_id))).scalars().first()
        if user:
            recipient = user.notification_email or user.plex_email
            display_name = user.custom_name or user.display_name or user.plex_user_id

    if not recipient:
        recipient = settings.smtp_from

    if not recipient:
        raise HTTPException(
            status_code=400,
            detail="Aucun destinataire de test configuré",
        )

    event_type = body.type if body.type in _EVENT_TYPES else "request"
    is_upgrade = event_type == "upgrade"
    event_def = get_event(_CATALOG_EVENT_KEY.get(event_type, event_type))
    req = _create_dummy_request()

    scope, language, season_number, episode_number = (
        _parse_preview_variant(body.preview_variant)
        if event_type in ("available", "upgrade")
        else ("movie", None, None, None)
    )

    tags = _build_tags(
        req,
        display_name=display_name,
        scope=scope,
        language=language,
        is_upgrade=is_upgrade,
        season_number=season_number,
        episode_number=episode_number,
        reason="Impossible de contacter Sonarr." if event_type == "failure" else "",
        corrections=["Son corrigé", "Sous-titres resynchronisés"],
        correction_note="Note complémentaire : le fichier a été remplacé par une version corrigée."
        if event_type == "correction"
        else "",
    )

    jinja_ctx = _build_preview_jinja_ctx(settings, event_type, req, display_name, language, body)
    # Envoi réel (contrairement à l'aperçu) : résolution effective du lien Plex, avec
    # fallback silencieux (None -> bouton omis) si le serveur est injoignable ou l'item introuvable.
    jinja_ctx["_tmdb_url"] = build_tmdb_url(req)
    jinja_ctx["_plex_deep_link"] = await resolve_plex_deep_link(settings, req)

    generic_fallback = f"[Plexarr] {'Correction' if event_type == 'correction' else event_def.label} : {req.title}"
    default_subject = (
        "[Plexarr] Correction : {titre} {details_saison_episode}"
        if event_type == "correction"
        else event_def.default_subject
    )
    fallback_subject = (
        render_subject(default_subject, tags, fallback=generic_fallback) if default_subject else generic_fallback
    )
    rendered_subject = render_subject(body.subject, tags, fallback=fallback_subject)

    html = render_template(body.template, tags, jinja_ctx)

    try:
        from ..services.email_service import _send

        await _send(settings, recipient, rendered_subject, html)
        return {"status": "ok", "message": f"Email envoyé avec succès à {recipient}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
