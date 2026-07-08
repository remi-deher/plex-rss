import json as _json
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_auth
from ..models import DownloadClient, MediaRequest, PlexUser, RequestStatus, Settings, VfEpisodeStatus
from ..scheduler import _notify, check_arr_statuses, poll_watchlists
from ..utils import get_or_404, now_utc_naive, parse_email_list

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["requests"], dependencies=[Depends(require_auth)])


class BulkAction(BaseModel):
    ids: list[int]


def _delete_vf_episode_cache(db: Session, request_id: int) -> None:
    """Purge le cache VF par épisode d'une demande supprimée (évite les lignes orphelines)."""
    db.query(VfEpisodeStatus).filter(
        VfEpisodeStatus.source_type == "request", VfEpisodeStatus.source_id == request_id
    ).delete()


@router.get("/requests")
def list_requests(query: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(MediaRequest)
    if query:
        q = q.filter(MediaRequest.title.ilike(f"%{query}%"))
    return q.order_by(MediaRequest.requested_at.desc()).limit(200).all()


@router.get("/plex/library-search")
async def plex_library_search(query: str, db: Session = Depends(get_db)):
    """Cherche un titre dans la bibliothèque Plex locale."""
    s = db.query(Settings).first()
    if not s or not s.plex_url or not s.plex_token:
        return []
    try:
        async with httpx.AsyncClient(timeout=10, verify=s.plex_verify_ssl) as client:
            r = await client.get(
                f"{s.plex_url.rstrip('/')}/search",
                params={"query": query, "X-Plex-Token": s.plex_token, "limit": 10},
                headers={"Accept": "application/json"},
            )
            r.raise_for_status()
            data = r.json()
            items = data.get("MediaContainer", {}).get("Metadata", [])
            return [
                {
                    "title": i.get("title", ""),
                    "year": i.get("year"),
                    "media_type": "show" if i.get("type") in ("show", "season", "episode") else "movie",
                    "thumb": f"{s.plex_url.rstrip('/')}{i['thumb']}?X-Plex-Token={s.plex_token}"
                    if i.get("thumb")
                    else None,
                    "summary": i.get("summary", ""),
                    "plex_type": i.get("type", ""),
                }
                for i in items
                if i.get("type") in ("movie", "show")
            ]
    except Exception as e:
        logger.warning(f"Plex library search failed: {e}")
        return []


@router.get("/requests/{request_id}")
async def get_request(request_id: int, db: Session = Depends(get_db)):
    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    d = {c.name: getattr(req, c.name) for c in req.__table__.columns}

    # Utilise le sérialiseur centralisé pour les formats de dates
    from ..serializers import format_datetime
    d["requested_at"] = format_datetime(req.requested_at)
    d["available_at"] = format_datetime(req.available_at)

    if req.torrent_hash and req.download_client_id:
        client = db.query(DownloadClient).filter(DownloadClient.id == req.download_client_id).first()
        if client and client.enabled:
            try:
                from ..services.download_clients import get_torrent_status

                status = await get_torrent_status(
                    client.client_type, client.url, client.username, client.password, req.torrent_hash
                )
                if status:
                    d["_torrent_status"] = status
            except Exception as e:
                logger.warning(f"Could not retrieve torrent status: {e}")

    settings = db.query(Settings).first()
    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    raw = (user_obj.notification_email if user_obj else None) or (settings.smtp_from if settings else "") or ""
    user_emails = parse_email_list(raw)
    notify_admin = bool(user_obj and getattr(user_obj, "notify_admin", True))
    admin_emails = parse_email_list(settings.admin_notification_email if settings and notify_admin else None)
    d["_user_emails"] = user_emails
    d["_admin_emails"] = admin_emails
    d["_notify_admin"] = notify_admin

    users = {u.plex_user_id: (u.custom_name or u.display_name or u.plex_user_id) for u in db.query(PlexUser).all()}
    d["plex_user"] = users.get(req.plex_user_id, req.plex_user or req.plex_user_id)
    try:
        extras = _json.loads(req.extra_requesters or "[]")
        for extra in extras:
            extra["display_name"] = users.get(
                extra.get("plex_user_id"), extra.get("display_name") or extra.get("plex_user_id")
            )
        d["extra_requesters"] = _json.dumps(extras)
    except Exception:
        pass
    return d


@router.post("/requests/bulk/retry")
async def bulk_retry_requests(body: BulkAction, db: Session = Depends(get_db)):
    """Repasse plusieurs demandes en pending et lance un polling."""
    reqs = db.query(MediaRequest).filter(MediaRequest.id.in_(body.ids)).all()
    count = 0
    for req in reqs:
        if req.status in ("failed", "pending"):
            req.status = "pending"
            count += 1
    if count > 0:
        db.commit()
        await poll_watchlists()
    return {"status": "success", "count": count}


@router.post("/requests/bulk/mark-processed")
def bulk_mark_requests_processed(body: BulkAction, db: Session = Depends(get_db)):
    """Marque plusieurs demandes comme traitées (disponibles) sans email."""
    reqs = db.query(MediaRequest).filter(MediaRequest.id.in_(body.ids)).all()
    now = now_utc_naive()
    for req in reqs:
        req.status = "available"
        req.request_mail_sent = True
        req.available_mail_sent = True
        if not req.available_at:
            req.available_at = now
    db.commit()
    return {"status": "success", "count": len(reqs)}


@router.post("/requests/bulk/delete")
def bulk_delete_requests(body: BulkAction, db: Session = Depends(get_db)):
    """Supprime plusieurs demandes définitivement."""
    reqs = db.query(MediaRequest).filter(MediaRequest.id.in_(body.ids)).all()
    count = len(reqs)
    for req in reqs:
        _delete_vf_episode_cache(db, req.id)
        db.delete(req)
    db.commit()
    return {"status": "success", "count": count}


@router.post("/requests/{request_id}/retry")
async def retry_request(request_id: int, db: Session = Depends(get_db)):
    """Repasse une demande en `pending` et déclenche un polling immédiat."""
    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    if req.status not in ("failed", "pending"):
        raise HTTPException(400, "Only failed or pending requests can be retried")
    req.status = "pending"
    db.commit()
    await poll_watchlists()
    return {"status": "retrying"}


@router.post("/requests/retry-failed")
async def retry_all_failed(db: Session = Depends(get_db)):
    """Repasse toutes les demandes 'failed' en 'pending' et déclenche un polling."""
    failed = db.query(MediaRequest).filter(MediaRequest.status == "failed").all()
    count = len(failed)
    for req in failed:
        req.status = "pending"
    db.commit()
    await poll_watchlists()
    return {"status": "ok", "retried": count}


@router.post("/requests/recalculate-dates")
async def recalculate_dates():
    """Re-joue sync_seer_requests pour corriger requested_at et available_at depuis Seer."""
    from ..scheduler import sync_seer_requests

    await sync_seer_requests()
    return {"status": "ok"}


@router.post("/requests/merge-duplicates")
def merge_duplicates_endpoint():
    """Fusionne les MediaRequest en double (même tmdb_id toutes sources)."""
    from scripts.merge_duplicate_requests import merge_duplicates

    merge_duplicates(dry_run=False)
    return {"status": "ok"}


@router.post("/requests/poll")
async def trigger_poll():
    """Déclenche manuellement le polling des watchlists ET la vérification des statuts *arr."""
    await poll_watchlists()
    await check_arr_statuses()
    return {"status": "poll triggered"}


@router.delete("/requests/{request_id}")
def delete_request(request_id: int, db: Session = Depends(get_db)):
    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    _delete_vf_episode_cache(db, req.id)
    db.delete(req)
    db.commit()
    return {"status": "deleted"}


@router.post("/requests/{request_id}/mark-processed")
def mark_request_processed(
    request_id: int,
    event: str = "available",
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    """Envoie manuellement le mail "demande" ou "disponible" pour une requête."""
    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    settings = db.query(Settings).first()

    if event == "request":
        if settings:
            _notify("request", settings, req, db, force=True)
        req.request_mail_sent = True
    else:
        event = "available"
        if settings:
            _notify("available", settings, req, db, force=True)
        req.status = RequestStatus.available
        req.available_mail_sent = True
        if not req.available_at:
            req.available_at = now_utc_naive()

    db.commit()

    return {
        "status": "success",
        "message": "Demande marquée comme traitée",
        "notified": True,
        "event": event,
    }
