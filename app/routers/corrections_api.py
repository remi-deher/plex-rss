import logging
from html import escape
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import get_db_async
from ..dependencies import require_admin, require_auth
from ..models import LibraryItem, MediaRequest, PlexUser, Settings, NotificationLog
from ..services.email_service import build_correction_email, send_correction_notification
from ..utils import async_get_or_404, now_utc_naive

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["corrections"], dependencies=[Depends(require_auth)])


class MediaCorrectionRequest(BaseModel):
    library_id: Optional[int] = None
    request_id: Optional[int] = None
    recipient_user_ids: list[int] = Field(default_factory=list)
    preview_user_id: Optional[int] = None
    corrections: list[str] = Field(default_factory=list)
    note: Optional[str] = Field(default=None, max_length=2000)
    scope: str = "media"
    season_number: Optional[int] = None
    episode_number: Optional[int] = None


CORRECTION_OPTIONS = {
    "Son corrigé",
    "Synchronisation audio corrigée",
    "Sous-titres corrigés",
    "Synchronisation des sous-titres corrigée",
    "Langue audio corrigée",
    "Qualité vidéo améliorée",
    "Mauvaise version remplacée",
    "Épisode corrigé",
    "Métadonnées corrigées",
    "Affiche / jaquette corrigée",
}


@router.get("/media/corrections/options")
async def get_correction_options():
    return sorted(list(CORRECTION_OPTIONS))


async def _resolve_correction_media(
    db: AsyncSession, library_id: Optional[int], request_id: Optional[int]
) -> LibraryItem | MediaRequest:
    if library_id:
        return await async_get_or_404(db, LibraryItem, library_id, "Library item not found")
    if request_id:
        return await async_get_or_404(db, MediaRequest, request_id, "Request not found")
    raise HTTPException(400, "library_id or request_id is required")


def _validated_corrections(values: list[str]) -> list[str]:
    cleaned = []
    for value in values:
        label = str(value).strip()
        if label in CORRECTION_OPTIONS and label not in cleaned:
            cleaned.append(label)
    if not cleaned:
        raise HTTPException(400, "Au moins une correction doit être sélectionnée")
    return cleaned


def _correction_recipient(user: PlexUser) -> tuple[str, str]:
    recipient = (user.notification_email or user.plex_email or "").strip()
    display_name = user.custom_name or user.display_name or user.plex_user_id
    return recipient, display_name


def _validated_correction_target(
    body: MediaCorrectionRequest, media: LibraryItem | MediaRequest
) -> tuple[str, int | None, int | None]:
    scope = (body.scope or "media").strip()
    if media.media_type != "show":
        return "movie", None, None
    if scope == "episode":
        if body.season_number is None or body.episode_number is None:
            raise HTTPException(400, "Saison et épisode sont requis")
        return "episode", body.season_number, body.episode_number
    if scope == "season":
        if body.season_number is None:
            raise HTTPException(400, "Saison requise")
        return "season", body.season_number, None
    return "series_complete", None, None


@router.post("/media/correction-preview", dependencies=[Depends(require_admin)])
async def preview_media_correction(body: MediaCorrectionRequest, db: AsyncSession = Depends(get_db_async)):
    settings = (await db.execute(select(Settings))).scalars().first()
    if not settings:
        raise HTTPException(500, "Settings manquants")
    media = await _resolve_correction_media(db, body.library_id, body.request_id)
    corrections = _validated_corrections(body.corrections)
    scope, season_number, episode_number = _validated_correction_target(body, media)

    user = None
    if body.preview_user_id:
        user = (await db.execute(select(PlexUser).filter(PlexUser.id == body.preview_user_id))).scalars().first()
    if not user and body.recipient_user_ids:
        user = (await db.execute(select(PlexUser).filter(PlexUser.id == body.recipient_user_ids[0]))).scalars().first()
    if not user:
        raise HTTPException(400, "Sélectionnez au moins un destinataire")

    recipient, display_name = _correction_recipient(user)
    if not recipient:
        recipient = "utilisateur@plex.local"
    subject, html = build_correction_email(
        settings,
        media,
        display_name,
        corrections,
        body.note or "",
        plex_deep_link="#",
        scope=scope,
        season_number=season_number,
        episode_number=episode_number,
    )
    header_html = f"""
    <div style="background:#2a2a2a; color:#fff; font-family:sans-serif; padding:12px 20px; border-bottom:1px solid #333; margin-bottom:15px; font-size:13px;">
      <div style="margin-bottom:4px;"><strong>Objet :</strong> <span style="color:#e5a00d; font-weight:bold;">{escape(subject)}</span></div>
      <div style="margin-bottom:4px;"><strong>De :</strong> {escape(settings.smtp_from or "plex-rss@monitor.local")}</div>
      <div><strong>À :</strong> {escape(recipient)} ({escape(display_name)})</div>
    </div>
    """
    if "<body style=" in html:
        parts = html.split("<body", 1)
        body_tag, rest = parts[1].split(">", 1)
        html = f"{parts[0]}<body{body_tag}>{header_html}{rest}"
    elif "<body>" in html:
        html = html.replace("<body>", f"<body>{header_html}")
    else:
        html = header_html + html
    return Response(content=html, media_type="text/html")


@router.post("/media/send-correction", dependencies=[Depends(require_admin)])
async def send_media_correction(body: MediaCorrectionRequest, db: AsyncSession = Depends(get_db_async)):
    settings = (await db.execute(select(Settings))).scalars().first()
    if not settings:
        raise HTTPException(500, "Settings manquants")
    media = await _resolve_correction_media(db, body.library_id, body.request_id)
    corrections = _validated_corrections(body.corrections)
    scope, season_number, episode_number = _validated_correction_target(body, media)
    if not body.recipient_user_ids:
        raise HTTPException(400, "Sélectionnez au moins un destinataire")

    users = (await db.execute(select(PlexUser).filter(PlexUser.id.in_(body.recipient_user_ids)))).scalars().all()
    by_id = {u.id: u for u in users}
    sent = []
    skipped = []
    errors = []
    for user_id in body.recipient_user_ids:
        user = by_id.get(user_id)
        if not user:
            skipped.append({"user_id": user_id, "reason": "Utilisateur introuvable"})
            continue
        recipient, display_name = _correction_recipient(user)
        if not recipient:
            skipped.append({"user_id": user_id, "name": display_name, "reason": "Aucune adresse email"})
            continue
        try:
            await send_correction_notification(
                settings,
                media,
                recipient,
                display_name,
                corrections,
                body.note or "",
                scope=scope,
                season_number=season_number,
                episode_number=episode_number,
            )
            sent.append({"user_id": user_id, "recipient": recipient, "name": display_name})
            db.add(NotificationLog(
                sent_at=now_utc_naive(),
                event="request.correction",
                recipient=recipient,
                success=True,
                media_title=media.title,
                media_type=media.media_type,
                req_id=body.request_id,
                is_admin=True
            ))
        except Exception as exc:
            errors.append({"user_id": user_id, "recipient": recipient, "name": display_name, "error": str(exc)})
            db.add(NotificationLog(
                sent_at=now_utc_naive(),
                event="request.correction",
                recipient=recipient,
                success=False,
                error_msg=str(exc),
                media_title=media.title,
                media_type=media.media_type,
                req_id=body.request_id,
                is_admin=True
            ))
    await db.commit()

    if errors and not sent:
        raise HTTPException(500, {"message": "Aucun email envoyé", "errors": errors, "skipped": skipped})
    return {"status": "ok", "sent": sent, "skipped": skipped, "errors": errors}
