import json as _json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import sqlalchemy

from ..database import get_db_async
from ..dependencies import current_user, require_admin
from ..models import AdminActionLog, DiagnosticEvent, MediaRequest, NotificationLog, PlexUser, Settings
from ..notification_queue import enqueue as enqueue_notification
from ..notification_queue import cancel_all_pending, cancel_pending
from ..notification_queue import process_pending_id
from ..job_queue import arq_enabled, enqueue_job, notification_hold_enabled, set_notification_hold
from ..serializers import format_datetime
from ..services.email_service import (
    DEFAULT_AVAILABLE_TEMPLATE,
    DEFAULT_REQUEST_TEMPLATE,
    _build_tags,
    get_event_visuals,
    get_shared_email_parts,
    render_subject,
    render_template,
)
from ..services.notification_catalog import event_badge_class, event_mail_flags, get_event
from ..utils import async_get_or_404, now_utc, now_utc_naive

router = APIRouter(prefix="/api", tags=["notifications"], dependencies=[Depends(require_admin)])


class PendingNotificationPurge(BaseModel):
    ids: list[int] | None = None
    mark_handled: bool = False


class PendingNotificationAction(BaseModel):
    ids: list[int]


class NotificationHoldPayload(BaseModel):
    enabled: bool


async def _log_admin_action(
    db: AsyncSession,
    request: Request,
    *,
    action: str,
    summary: str,
    target_count: int,
    details: dict | None = None,
) -> None:
    actor = current_user(request, db) or {}
    db.add(
        AdminActionLog(
            action=action,
            actor_user_id=actor.get("id"),
            actor_name=actor.get("username") or actor.get("plex_user_id") or "api",
            summary=summary,
            target_count=target_count,
            details=_json.dumps(details or {}, ensure_ascii=False),
        )
    )


@router.get("/activity")
async def activity_log(db: AsyncSession = Depends(get_db_async)):
    """Retourne les 25 événements les plus récents (7 derniers jours) pour le journal."""
    cutoff = now_utc_naive() - timedelta(days=7)
    reqs = (
        await db.execute(
            select(MediaRequest)
            .filter(
                (MediaRequest.requested_at >= cutoff)
                | (MediaRequest.available_at >= cutoff)
                | (MediaRequest.vf_available_at >= cutoff)
            )
            .order_by(MediaRequest.requested_at.desc())
            .limit(120)
        )
    ).scalars().all()
    users = {u.plex_user_id: (u.custom_name or u.display_name or u.plex_user_id) for u in (await db.execute(select(PlexUser))).scalars().all()}

    events: list[dict[str, Any]] = []

    def add_event(req: MediaRequest, event_type: str, event_time, label: str, detail: str = ""):
        if not event_time:
            return
        user_name = users.get(req.plex_user_id) or req.plex_user or req.plex_user_id or "?"
        events.append(
            {
                "type": event_type,
                "label": label,
                "detail": detail,
                "title": req.title,
                "user": user_name,
                "media_type": req.media_type,
                "source": req.source,
                "status": req.status,
                "request_id": req.id,
                "arr_slug": req.arr_slug,
                "time": format_datetime(event_time),
            }
        )

    for r in reqs:
        if r.requested_at:
            if r.status == "failed":
                add_event(r, "failed", r.requested_at, "Echec", "Traitement en erreur")
            elif r.status == "sent_to_arr":
                add_event(r, "sent", r.requested_at, "Transmise", "Detection et envoi vers ARR")
            else:
                add_event(r, "detected", r.requested_at, "Ajoutee a la watchlist", "Ajout a la watchlist Plex ou creation de la demande")
        if r.available_at and r.available_at >= cutoff:
            add_event(r, "available", r.available_at, "Disponible", "Disponibilite confirmee")
        if r.vf_available_at and r.vf_available_at >= cutoff:
            add_event(r, "vf_available", r.vf_available_at, "VF disponible", "Upgrade VF detecte")

    logs = (
        await db.execute(
            select(NotificationLog)
            .filter(NotificationLog.sent_at >= cutoff)
            .order_by(NotificationLog.sent_at.desc())
            .limit(80)
        )
    ).scalars().all()
    for log in logs:
        events.append(
            {
                "type": "notification" if log.success else "notification_failed",
                "label": "Notification" if log.success else "Notif. echouee",
                "detail": log.event,
                "title": log.media_title or (f"Demande #{log.req_id}" if log.req_id else "Notification"),
                "user": "Admin" if log.is_admin else log.recipient,
                "media_type": log.media_type,
                "source": "notification",
                "status": "sent" if log.success else "failed",
                "request_id": log.req_id,
                "arr_slug": None,
                "time": format_datetime(log.sent_at),
            }
        )

    events.sort(key=lambda e: e["time"], reverse=True)
    return events[:40]


@router.get("/notifications/recent-available")
async def recent_available(since: str = None, db: AsyncSession = Depends(get_db_async)):
    """Retourne les médias devenus disponibles depuis `since` (ISO 8601)."""
    q = select(MediaRequest).filter(MediaRequest.status == "available")
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            q = q.filter(MediaRequest.available_at >= since_dt)
        except ValueError:
            pass
    items = (await db.execute(q.order_by(MediaRequest.available_at.desc()).limit(10))).scalars().all()
    return [{"id": r.id, "title": r.title, "available_at": format_datetime(r.available_at)} for r in items]


@router.get("/logs")
def get_logs(_: None = Depends(require_admin)):
    """Retourne les derniers logs applicatifs (buffer mémoire circulaire)."""
    from ..log_buffer import get_logs as _get_logs

    return _get_logs()


@router.get("/diagnostic-logs")
async def list_diagnostic_logs(
    limit: int = 200,
    offset: int = 0,
    category: str | None = None,
    request_id: int | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db_async),
):
    """Retourne le parcours persistant Demande → Arr → Plex → Notification."""
    effective_limit = min(max(limit, 1), 500)
    q = select(DiagnosticEvent)
    if category:
        q = q.filter(DiagnosticEvent.category == category)
    if request_id:
        q = q.filter(DiagnosticEvent.request_id == request_id)
    if search:
        pattern = f"%{search}%"
        q = q.filter(sqlalchemy.or_(
            DiagnosticEvent.title.ilike(pattern),
            DiagnosticEvent.message.ilike(pattern),
            DiagnosticEvent.action.ilike(pattern),
            DiagnosticEvent.correlation_id.ilike(pattern),
        ))
    q = q.order_by(DiagnosticEvent.created_at.desc())
    total = (await db.execute(sqlalchemy.select(sqlalchemy.func.count()).select_from(q.subquery()))).scalar()
    events = (await db.execute(q.offset(offset).limit(effective_limit))).scalars().all()
    return {
        "total": total,
        "offset": offset,
        "limit": effective_limit,
        "items": [
            {
                "id": event.id,
                "created_at": format_datetime(event.created_at),
                "request_id": event.request_id,
                "correlation_id": event.correlation_id,
                "category": event.category,
                "action": event.action,
                "status": event.status,
                "title": event.title,
                "media_type": event.media_type,
                "source": event.source,
                "message": event.message,
                "details": _json.loads(event.details or "{}"),
            }
            for event in events
        ],
    }


@router.get("/email/preview")
async def preview_email_template(event: str = "request", user_id: Optional[int] = None, db: AsyncSession = Depends(get_db_async)):
    """Rend le template email avec des données fictives et retourne le HTML."""
    settings = (await db.execute(select(Settings))).scalars().first()

    plex_user_name = "Jean Dupont"
    recipient_email = "jean.dupont@plex.local"
    if user_id:
        user = (await db.execute(select(PlexUser).filter(PlexUser.id == user_id))).scalars().first()
        if user:
            plex_user_name = user.custom_name or user.display_name or user.plex_user_id
            recipient_email = user.notification_email or user.plex_email or "utilisateur@plex.local"

    fake = MediaRequest(
        title="Dune : Deuxième Partie",
        year=2024,
        media_type="movie",
        plex_user=plex_user_name,
        overview="Paul Atréides s'unit aux Fremen pour mener la guerre sainte contre ceux qui ont détruit sa famille.",
        poster_url="https://image.tmdb.org/t/p/w300/1pdfLvkbY9ohJlCjQH2CZjjYVvJ.jpg",
    )
    tags = _build_tags(fake, plex_user_name, language="vf")

    if event == "available":
        tpl = (
            settings.email_available_template
            if (settings and isinstance(settings.email_available_template, str))
            else None
        ) or DEFAULT_AVAILABLE_TEMPLATE
        subject_tmpl = (
            settings.email_available_subject
            if (settings and isinstance(settings.email_available_subject, str))
            else None
        ) or "[Plexarr] {titre} est disponible sur Plex !"
    else:
        tpl = (
            settings.email_request_template if (settings and isinstance(settings.email_request_template, str)) else None
        ) or DEFAULT_REQUEST_TEMPLATE
        subject_tmpl = (
            settings.email_request_subject if (settings and isinstance(settings.email_request_subject, str)) else None
        ) or "[Plexarr] Nouvelle demande : {titre}"

    fallback_subject = (
        f"[Plexarr] Nouvelle demande : {fake.title}"
        if event == "request"
        else f"[Plexarr] {fake.title} est disponible sur Plex !"
    )
    rendered_subject = render_subject(subject_tmpl, tags, fallback=fallback_subject)

    jinja_ctx = get_shared_email_parts(settings)
    jinja_ctx.update(get_event_visuals(settings, event if event == "available" else "request"))
    html = render_template(tpl, tags, jinja_ctx)

    header_html = f"""
    <div style="background:#2a2a2a; color:#fff; font-family:sans-serif; padding:12px 20px; border-bottom:1px solid #333; margin-bottom:15px; font-size:13px;">
      <div style="margin-bottom:4px;"><strong>Objet :</strong> <span style="color:#e5a00d; font-weight:bold;">{rendered_subject}</span></div>
      <div style="margin-bottom:4px;"><strong>De :</strong> {(settings.smtp_from if settings else None) or "plex-rss@monitor.local"}</div>
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

    return HTMLResponse(content=html)


@router.get("/notifications/log")
async def list_notification_logs(
    limit: int = 50,
    offset: int = 0,
    state: str = None,
    types: str = None,
    users: str = None,
    search: str = None,
    db: AsyncSession = Depends(get_db_async)
):
    effective_limit = min(limit, 200)
    q = select(NotificationLog)

    if state == "success":
        q = q.filter(NotificationLog.success.is_(True))
    elif state == "error":
        q = q.filter(NotificationLog.success.is_(False))

    if types:
        type_list = [t.strip() for t in types.split(",") if t.strip()]
        if type_list:
            conditions = []
            for t in type_list:
                if t == "correction":
                    conditions.append(NotificationLog.event.startswith("correction"))
                    conditions.append(NotificationLog.event.startswith("request.correction"))
                elif t == "upgrade":
                    conditions.append(NotificationLog.is_upgrade.is_(True))
                    conditions.append(NotificationLog.event == "vf_available")
                else:
                    conditions.append(NotificationLog.event.startswith(t))
                    if t == "available":
                        legacy_prefixes = [
                            "episode_track", "vo_only",
                            "partially_available", "language_"
                        ]
                        for lp in legacy_prefixes:
                            conditions.append(NotificationLog.event.startswith(lp))
            q = q.filter(sqlalchemy.or_(*conditions))

    if users:
        user_ids = []
        for u in users.split(","):
            if u.strip().isdigit():
                user_ids.append(int(u.strip()))
        if user_ids:
            db_users = (await db.execute(select(PlexUser).filter(PlexUser.id.in_(user_ids)))).scalars().all()
            emails = []
            for u in db_users:
                if u.notification_email:
                    emails.append(u.notification_email.strip())
                if u.plex_email:
                    emails.append(u.plex_email.strip())
            if emails:
                q = q.filter(NotificationLog.recipient.in_(emails))
            else:
                q = q.filter(sqlalchemy.false())

    if search:
        search_str = f"%{search}%"
        q = q.filter(
            sqlalchemy.or_(
                NotificationLog.media_title.ilike(search_str),
                NotificationLog.recipient.ilike(search_str),
                NotificationLog.event.ilike(search_str),
                NotificationLog.error_msg.ilike(search_str)
            )
        )

    q = q.order_by(NotificationLog.sent_at.desc())
    total = (await db.execute(sqlalchemy.select(sqlalchemy.func.count()).select_from(q.subquery()))).scalar()
    logs = (await db.execute(q.offset(offset).limit(effective_limit))).scalars().all()
    return {
        "total": total,
        "offset": offset,
        "limit": effective_limit,
        "items": [
            {
                "id": log.id,
                "sent_at": format_datetime(log.sent_at),
                "event": log.event,
                "event_label": get_event(log.event).label,
                "event_group": get_event(log.event).group,
                "event_description": get_event(log.event).description,
                "event_badge_class": event_badge_class(log.event),
                "recipient": log.recipient,
                "is_admin": log.is_admin,
                "media_title": log.media_title,
                "media_type": log.media_type,
                "success": log.success,
                "status_label": "Envoyé" if log.success else "Erreur",
                "error_msg": log.error_msg,
                "req_id": log.req_id,
            }
            for log in logs
        ],
    }


@router.get("/admin-action-logs")
async def list_admin_action_logs(
    limit: int = 50,
    offset: int = 0,
    action: Optional[str] = None,
    db: AsyncSession = Depends(get_db_async),
):
    q = select(AdminActionLog)
    if action:
        q = q.filter(AdminActionLog.action == action)
    q = q.order_by(AdminActionLog.created_at.desc())
    total = (await db.execute(sqlalchemy.select(sqlalchemy.func.count()).select_from(q.subquery()))).scalar()
    logs = (await db.execute(q.offset(offset).limit(min(limit, 200)))).scalars().all()

    def _details(raw: str | None) -> dict:
        if not raw:
            return {}
        try:
            return _json.loads(raw)
        except Exception:
            return {"raw": raw}

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "id": log.id,
                "created_at": format_datetime(log.created_at),
                "action": log.action,
                "actor_user_id": log.actor_user_id,
                "actor_name": log.actor_name,
                "summary": log.summary,
                "target_count": log.target_count,
                "details": _details(log.details),
            }
            for log in logs
        ],
    }


@router.get("/notifications/hold")
async def get_notification_hold(db: AsyncSession = Depends(get_db_async)):
    pending_count = await db.scalar(text("SELECT COUNT(*) FROM pending_notifications"))
    return {"enabled": await notification_hold_enabled(), "pending_count": int(pending_count or 0)}


@router.put("/notifications/hold")
async def update_notification_hold(body: NotificationHoldPayload, request: Request, db: AsyncSession = Depends(get_db_async)):
    await set_notification_hold(body.enabled, db=db)
    pending_count = await db.scalar(text("SELECT COUNT(*) FROM pending_notifications"))
    await _log_admin_action(
        db,
        request,
        action="notification_hold_enabled" if body.enabled else "notification_hold_disabled",
        summary="Notifications mises en attente" if body.enabled else "Notifications automatiques réactivées",
        target_count=0,
        details={"enabled": body.enabled},
    )
    await db.commit()
    return {
        "enabled": body.enabled,
        "pending_count": int(pending_count or 0),
        "message": (
            "Les notifications sont maintenant mises en attente. "
            "Les nouvelles notifications resteront dans la file jusqu'à un envoi manuel."
            if body.enabled
            else "Les notifications automatiques sont réactivées. Les notifications déjà en file restent en attente."
        ),
    }


@router.get("/notifications/pending")
async def list_pending_notifications(db: AsyncSession = Depends(get_db_async)):
    rows = (
        await db.execute(
            text("SELECT id, created_at, event, req_id, recipients, reason FROM pending_notifications ORDER BY id DESC")
        )
    ).fetchall()
    req_ids = []
    for row in rows:
        try:
            req_ids.append(int(row.req_id))
        except Exception:
            pass
    titles = {
        req.id: {"title": req.title, "media_type": req.media_type}
        for req in (await db.execute(select(MediaRequest).filter(MediaRequest.id.in_(req_ids)))).scalars().all()
    }

    def _json_value(raw, fallback):
        try:
            value = _json.loads(raw) if raw else fallback
            return value if value is not None else fallback
        except Exception:
            return fallback

    items = []
    invalid = 0
    for row in rows:
        recipients = _json_value(row.recipients, [])
        context = _json_value(row.reason, {})
        is_valid = row.event in ("request", "available", "failed", "correction", "request.correction") and isinstance(recipients, list)
        if not is_valid:
            invalid += 1
        media = titles.get(row.req_id, {})
        items.append(
            {
                "id": row.id,
                "created_at": str(row.created_at or ""),
                "event": row.event,
                "event_label": get_event(row.event).label,

                "req_id": row.req_id,
                "media_title": media.get("title"),
                "media_type": media.get("media_type"),
                "recipients": recipients if isinstance(recipients, list) else [],
                "context": context if isinstance(context, dict) else {},
                "valid": is_valid,
            }
        )
    return {"total": len(items), "invalid": invalid, "items": items}


async def _pending_rows_for_purge(db: AsyncSession, ids: list[int]) -> list:
    if ids:
        stmt = text(
            "SELECT id, event, req_id, recipients, reason FROM pending_notifications WHERE id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        result = await db.execute(stmt, {"ids": [int(i) for i in ids]})
        return result.fetchall()
    result = await db.execute(text("SELECT id, event, req_id, recipients, reason FROM pending_notifications"))
    return result.fetchall()


def _safe_json_value(raw, fallback):
    try:
        value = _json.loads(raw) if raw else fallback
        return value if value is not None else fallback
    except Exception:
        return fallback


async def _mark_pending_rows_handled(db: AsyncSession, rows: list) -> int:
    req_ids = []
    for row in rows:
        try:
            req_ids.append(int(row.req_id))
        except Exception:
            pass
    if not req_ids:
        return 0

    reqs = {
        req.id: req
        for req in (await db.execute(select(MediaRequest).filter(MediaRequest.id.in_(sorted(set(req_ids)))))).scalars().all()
    }
    handled = 0
    for row in rows:
        event = "failed" if row.event == "failure" else row.event
        try:
            req = reqs.get(int(row.req_id))
        except Exception:
            req = None
        if not req:
            continue

        changed = False
        for attr in event_mail_flags(event):
            if hasattr(req, attr) and not getattr(req, attr):
                setattr(req, attr, True)
                changed = True

        if event == "available":
            context = _safe_json_value(row.reason, {})
            scope = context.get("scope") if isinstance(context, dict) else None
            if scope in ("episode", "season_start", "season_complete") and not req.partial_available_mail_sent:
                req.partial_available_mail_sent = True
                changed = True
            if req.episodes_available_count is not None:
                current = req.last_notified_episode_count or 0
                if req.episodes_available_count > current:
                    req.last_notified_episode_count = req.episodes_available_count
                    changed = True

        if changed:
            handled += 1
    return handled


@router.post("/notifications/pending/purge")
async def purge_pending_notifications(
    body: PendingNotificationPurge,
    request: Request,
    db: AsyncSession = Depends(get_db_async),
):
    ids = body.ids or []
    pending_rows = await _pending_rows_for_purge(db, ids)
    handled = await _mark_pending_rows_handled(db, pending_rows) if body.mark_handled else 0
    if body.mark_handled:
        await db.commit()
    else:
        await db.rollback()
    if ids:
        deleted = await cancel_pending(ids)
        action = "notification_queue_delete"
        summary = f"{deleted} notification(s) en attente supprimée(s)"
        details = {"ids": ids, "mark_handled": body.mark_handled, "handled_requests": handled}
    else:
        deleted = await cancel_all_pending()
        action = "notification_queue_purge_handled" if body.mark_handled else "notification_queue_purge"
        summary = f"{deleted} notification(s) en attente purgée(s)"
        if body.mark_handled:
            summary += f", {handled} demande(s) marquee(s) traitee(s)"
        details = {"purge_all": True, "mark_handled": body.mark_handled, "handled_requests": handled}
    await _log_admin_action(db, request, action=action, summary=summary, target_count=deleted, details=details)
    await db.commit()
    return {"status": "success", "deleted": deleted, "handled_requests": handled}


@router.post("/notifications/pending/process")
async def process_pending_notifications(
    body: PendingNotificationAction,
    request: Request,
    db: AsyncSession = Depends(get_db_async),
):
    ids = sorted({int(value) for value in body.ids})
    if not ids:
        return {"status": "success", "queued": 0}

    rows = await _pending_rows_for_purge(db, ids)
    existing_ids = {int(row.id) for row in rows}
    queued = 0
    for pending_id in ids:
        if pending_id not in existing_ids:
            continue
        if arq_enabled():
            await enqueue_job(
                "job_send_notification",
                pending_id,
                True,
                job_id=f"manual-notification:{pending_id}:{time.time_ns()}",
            )
        else:
            await process_pending_id(pending_id, force=True)
        queued += 1

    await _log_admin_action(
        db,
        request,
        action="notification_queue_process",
        summary=f"{queued} notification(s) envoyée(s) manuellement",
        target_count=queued,
        details={"ids": sorted(existing_ids.intersection(ids))},
    )
    await db.commit()
    return {"status": "success", "queued": queued}


@router.post("/notifications/{log_id}/resend")
async def resend_notification(log_id: int, db: AsyncSession = Depends(get_db_async)):
    log = (await db.execute(select(NotificationLog).filter(NotificationLog.id == log_id))).scalars().first()
    if not log:
        raise HTTPException(404, "Log introuvable")
    if not log.req_id:
        raise HTTPException(400, "req_id manquant sur cette entrée de log (envoi antérieur à la v2.1)")
    req = await async_get_or_404(db, MediaRequest, log.req_id, "Demande originale introuvable")
    # Les anciens évènements de disponibilité (available_vf, vo_only, vf_available,
    # episode_track, partially_available, available_vo_tracking — retirés du catalogue,
    # voir notification_catalog.py) sont tous fusionnés dans "available" aujourd'hui.
    event = log.event if log.event in ("request", "available", "failed", "correction") else "available"
    context = (
        {
            "scope": log.scope,
            "language": log.language,
            "is_upgrade": log.is_upgrade,
            "season_number": log.season_number,
            "episode_number": log.episode_number,
        }
        if event == "available"
        else None
    )
    await enqueue_notification(event, req.id, [log.recipient], context)
    return {"status": "queued", "recipient": log.recipient, "event": event}
