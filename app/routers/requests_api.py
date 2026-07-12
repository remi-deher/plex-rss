import json as _json
import logging
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import current_user, require_admin, require_auth
from ..models import AdminActionLog, ArrInstance, DownloadClient, MediaRequest, PlexUser, RequestStatus, Settings, VfEpisodeStatus
from ..scheduler import _notify, check_arr_statuses, poll_watchlists
from ..services import radarr, sonarr
from ..utils import get_or_404, now_utc_naive, parse_email_list

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["requests"], dependencies=[Depends(require_auth)])


def _caller_plex_user_id(request, db: Session) -> str | None:
    caller = current_user(request, db)
    if not caller or caller.get("is_owner") or caller.get("role") == "admin":
        return None
    return caller.get("plex_user_id")


def _ensure_request_visible(req: MediaRequest, request, db: Session) -> None:
    uid = _caller_plex_user_id(request, db)
    if not uid:
        return
    if req.plex_user_id == uid:
        return
    try:
        extras = _json.loads(req.extra_requesters or "[]")
    except Exception:
        extras = []
    if any(e.get("plex_user_id") == uid for e in extras):
        return
    raise HTTPException(status_code=404, detail="Request not found")


class BulkAction(BaseModel):
    ids: list[int]
    delete_from_arr: bool = False
    delete_files: bool = False


async def _delete_media_from_arr(db: Session, req: MediaRequest, delete_files: bool) -> tuple[bool, str]:
    """Tente de supprimer le média correspondant dans Sonarr/Radarr.

    Ne renvoie jamais ok=True suite à une erreur réseau/HTTP : seule une confirmation
    explicite (suppression réussie ou déjà absent) vaut succès. L'appelant ne doit
    supprimer la demande locale que si ok=True, pour ne jamais désynchroniser les deux
    côtés quand Sonarr/Radarr est injoignable.
    """
    if not req.arr_id or not req.arr_instance_id:
        return True, "Aucune instance *arr liée à cette demande"
    if req.arr_slug and req.arr_slug.startswith("prowlarr:"):
        return True, "Gérée par Prowlarr, rien à supprimer côté *arr"

    inst = db.query(ArrInstance).filter(ArrInstance.id == req.arr_instance_id).first()
    if not inst:
        return True, "Instance *arr introuvable en base"

    try:
        if req.media_type == "movie" and inst.arr_type == "radarr":
            return await radarr.delete_movie(inst.url, inst.api_key, req.arr_id, delete_files)
        if req.media_type == "show" and inst.arr_type == "sonarr":
            return await sonarr.delete_series(inst.url, inst.api_key, req.arr_id, delete_files)
        return True, "Type d'instance incompatible, rien à supprimer côté *arr"
    except Exception as e:
        return False, str(e)


class RequestersUpdate(BaseModel):
    requester_ids: list[str]


@router.put("/requests/{request_id}/requesters", dependencies=[Depends(require_admin)])
def update_requesters(request_id: int, body: RequestersUpdate, db: Session = Depends(get_db)):
    """Définit la liste des demandeurs d'une demande (le 1er = demandeur principal,
    les suivants = demandeurs additionnels). Modification manuelle : **aucun mail de
    demande** n'est envoyé (le mail « demande reçue » ne part qu'à la création)."""
    req = get_or_404(db, MediaRequest, request_id, "Request not found")

    # Déduplique en conservant l'ordre
    seen: set[str] = set()
    ordered: list[str] = []
    for uid in body.requester_ids:
        uid = (uid or "").strip()
        if uid and uid not in seen:
            seen.add(uid)
            ordered.append(uid)
    if not ordered:
        raise HTTPException(400, "Au moins un demandeur est requis.")

    users = {u.plex_user_id: u for u in db.query(PlexUser).all()}

    def _name(uid: str) -> str:
        u = users.get(uid)
        return (u.display_name or u.plex_user_id) if u else uid

    primary = ordered[0]
    req.plex_user_id = primary
    req.plex_user = _name(primary)
    req.extra_requesters = _json.dumps(
        [{"plex_user_id": uid, "display_name": _name(uid)} for uid in ordered[1:]],
        ensure_ascii=False,
    )
    db.commit()
    return {"ok": True, "requester_ids": ordered}


def _delete_vf_episode_cache(db: Session, request_id: int) -> None:
    """Purge le cache VF par épisode d'une demande supprimée (évite les lignes orphelines)."""
    db.query(VfEpisodeStatus).filter(
        VfEpisodeStatus.source_type == "request", VfEpisodeStatus.source_id == request_id
    ).delete()


@router.get("/requests")
def list_requests(query: Optional[str] = None, request: Request = None, db: Session = Depends(get_db)):
    q = db.query(MediaRequest)
    uid = _caller_plex_user_id(request, db) if request else None
    if uid:
        q = q.filter(
            (MediaRequest.plex_user_id == uid)
            | (MediaRequest.extra_requesters.like(f'%"plex_user_id": "{uid}"%'))
            | (MediaRequest.extra_requesters.like(f'%"plex_user_id":"{uid}"%'))
        )
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


@router.get("/requests/pending", dependencies=[Depends(require_admin)])
def list_pending_requests(db: Session = Depends(get_db)):
    """File des demandes en attente de validation (admin). Déclaré avant
    /requests/{request_id} pour ne pas être capté par le param int."""
    from ..serializers import serialize_media_request

    reqs = (
        db.query(MediaRequest)
        .filter(MediaRequest.status == RequestStatus.pending_approval)
        .order_by(MediaRequest.requested_at.desc())
        .all()
    )
    users = {u.plex_user_id: (u.custom_name or u.display_name or u.plex_user_id) for u in db.query(PlexUser).all()}
    return [serialize_media_request(r, users) for r in reqs]


@router.get("/requests/{request_id}")
async def get_request(request_id: int, request: Request, db: Session = Depends(get_db)):
    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    _ensure_request_visible(req, request, db)
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


@router.post("/requests/bulk/retry", dependencies=[Depends(require_admin)])
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


@router.post("/requests/bulk/mark-processed", dependencies=[Depends(require_admin)])
def bulk_mark_requests_processed(body: BulkAction, request: Request, db: Session = Depends(get_db)):
    """Marque plusieurs demandes comme traitées (disponibles) sans email."""
    reqs = db.query(MediaRequest).filter(MediaRequest.id.in_(body.ids)).all()
    now = now_utc_naive()
    items = []
    for req in reqs:
        before_status = req.status.value if hasattr(req.status, "value") else req.status
        req.status = "available"
        req.request_mail_sent = True
        req.available_mail_sent = True
        if not req.available_at:
            req.available_at = now
        items.append(
            {
                "id": req.id,
                "title": req.title,
                "media_type": req.media_type,
                "status_before": before_status,
                "status_after": "available",
                "notification_sent": False,
            }
        )
    actor = current_user(request, db) or {}
    db.add(
        AdminActionLog(
            action="bulk_mark_processed_silent",
            actor_user_id=actor.get("id"),
            actor_name=actor.get("username") or actor.get("plex_user_id") or "api",
            summary=f"{len(reqs)} demande(s) traitee(s) sans notification",
            target_count=len(reqs),
            details=_json.dumps({"items": items, "notification_sent": False}, ensure_ascii=False),
        )
    )
    db.commit()
    return {"status": "success", "count": len(reqs)}


@router.post("/requests/bulk/delete", dependencies=[Depends(require_admin)])
async def bulk_delete_requests(body: BulkAction, db: Session = Depends(get_db)):
    """Supprime plusieurs demandes définitivement.

    Si `delete_from_arr=True`, tente aussi la suppression côté Sonarr/Radarr avant
    chaque suppression locale : si *arr est injoignable pour une demande donnée, celle-ci
    est laissée intacte (ni suppression locale ni *arr) plutôt que de désynchroniser les
    deux côtés — les autres demandes de la sélection sont traitées normalement.
    """
    reqs = db.query(MediaRequest).filter(MediaRequest.id.in_(body.ids)).all()
    count = 0
    skipped = []
    for req in reqs:
        if body.delete_from_arr:
            ok, msg = await _delete_media_from_arr(db, req, body.delete_files)
            if not ok:
                skipped.append({"id": req.id, "title": req.title, "reason": msg})
                continue
        _delete_vf_episode_cache(db, req.id)
        db.delete(req)
        count += 1
    db.commit()
    return {"status": "success", "count": count, "skipped": skipped}


class RejectBody(BaseModel):
    reason: Optional[str] = None


@router.post("/requests/{request_id}/approve", dependencies=[Depends(require_admin)])
async def approve_request(request_id: int, request: Request, db: Session = Depends(get_db)):
    """Valide une demande en attente : la transmet à *arr et bascule en sent_to_arr."""
    from ..services.watchlist_poller import _submit_to_arr

    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    if req.status != RequestStatus.pending_approval:
        raise HTTPException(400, "Seules les demandes en attente de validation peuvent être approuvées.")

    settings = db.query(Settings).first()
    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    item: dict[str, Any] = {
        "title": req.title,
        "year": req.year,
        "media_type": req.media_type,
        "tmdb_id": req.tmdb_id,
        "tvdb_id": req.tvdb_id,
        "imdb_id": req.imdb_id,
    }
    try:
        arr_id, _already, arr_slug = await _submit_to_arr(settings, item, user_obj, db=db)
    except Exception as e:
        raise HTTPException(502, f"Échec de transmission à *arr : {e}")

    # Source de suivi : Seer si l'envoi n'a pas transité par une instance *arr ni un torrent.
    seer_used = arr_id is not None and not item.get("_arr_instance_id") and not item.get("_torrent_hash")
    req.source = "seer" if seer_used else "manual_search"
    req.status = RequestStatus.sent_to_arr
    req.arr_id = arr_id if isinstance(arr_id, int) else None
    req.arr_slug = arr_slug
    req.arr_instance_id = item.get("_arr_instance_id")
    if item.get("_torrent_hash"):
        req.torrent_hash = item.get("_torrent_hash")
        req.download_client_id = item.get("_download_client_id")
    caller = current_user(request, db)
    req.approved_by = (caller or {}).get("plex_user_id") or "admin"
    req.approved_at = now_utc_naive()
    req.rejected_reason = None
    db.commit()

    if settings:
        _notify("request", settings, req, db)
    return {"ok": True, "status": "sent_to_arr", "id": req.id}


@router.post("/requests/{request_id}/reject", dependencies=[Depends(require_admin)])
def reject_request(request_id: int, body: RejectBody, request: Request, db: Session = Depends(get_db)):
    """Refuse une demande en attente (conservée en historique avec le motif)."""
    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    if req.status != RequestStatus.pending_approval:
        raise HTTPException(400, "Seules les demandes en attente de validation peuvent être refusées.")
    req.status = RequestStatus.rejected
    req.rejected_reason = (body.reason or "").strip() or None
    caller = current_user(request, db)
    req.approved_by = (caller or {}).get("plex_user_id") or "admin"
    req.approved_at = now_utc_naive()
    db.commit()
    return {"ok": True, "status": "rejected", "id": req.id}


@router.post("/requests/{request_id}/retry", dependencies=[Depends(require_admin)])
async def retry_request(request_id: int, db: Session = Depends(get_db)):
    """Repasse une demande en `pending` et déclenche un polling immédiat."""
    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    if req.status not in ("failed", "pending"):
        raise HTTPException(400, "Only failed or pending requests can be retried")
    req.status = "pending"
    db.commit()
    await poll_watchlists()
    return {"status": "retrying"}


@router.post("/requests/retry-failed", dependencies=[Depends(require_admin)])
async def retry_all_failed(db: Session = Depends(get_db)):
    """Repasse toutes les demandes 'failed' en 'pending' et déclenche un polling."""
    failed = db.query(MediaRequest).filter(MediaRequest.status == "failed").all()
    count = len(failed)
    for req in failed:
        req.status = "pending"
    db.commit()
    await poll_watchlists()
    return {"status": "ok", "retried": count}


@router.post("/requests/recalculate-dates", dependencies=[Depends(require_admin)])
async def recalculate_dates():
    """Re-joue sync_seer_requests pour corriger requested_at et available_at depuis Seer."""
    from ..scheduler import sync_seer_requests

    await sync_seer_requests()
    return {"status": "ok"}


@router.post("/requests/merge-duplicates", dependencies=[Depends(require_admin)])
def merge_duplicates_endpoint():
    """Fusionne les MediaRequest en double (même tmdb_id toutes sources)."""
    from scripts.merge_duplicate_requests import merge_duplicates

    merge_duplicates(dry_run=False)
    return {"status": "ok"}


@router.post("/requests/poll", dependencies=[Depends(require_admin)])
async def trigger_poll():
    """Déclenche manuellement le polling des watchlists ET la vérification des statuts *arr."""
    await poll_watchlists()
    await check_arr_statuses()
    return {"status": "poll triggered"}


@router.delete("/requests/{request_id}")
async def delete_request(
    request_id: int,
    delete_from_arr: bool = False,
    delete_files: bool = False,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Supprime une demande. Si `delete_from_arr=True`, supprime aussi le média dans
    Sonarr/Radarr — mais seulement si cette suppression réussit (ou que le média y est
    déjà absent) : si *arr est injoignable, rien n'est supprimé du tout (ni côté *arr,
    ni localement) pour ne jamais désynchroniser les deux."""
    req = get_or_404(db, MediaRequest, request_id, "Request not found")
    if delete_from_arr:
        ok, msg = await _delete_media_from_arr(db, req, delete_files)
        if not ok:
            raise HTTPException(502, f"Suppression *arr impossible ({msg}) — rien n'a été supprimé.")
    _delete_vf_episode_cache(db, req.id)
    db.delete(req)
    db.commit()
    return {"status": "deleted"}


@router.post("/requests/{request_id}/cancel")
def cancel_own_request(request_id: int, request: Request, db: Session = Depends(get_db)):
    """Annulation par l'utilisateur de SA propre demande (profil portail).

    Retire l'appelant de la liste des demandeurs. S'il en était le seul, la demande
    est annulée **localement** ; jamais de suppression du média côté Sonarr/Radarr/Plex
    (action réservée aux admins via DELETE). Un admin peut aussi retirer sa propre
    participation via ce point.
    """
    caller = current_user(request, db)
    if not caller:
        raise HTTPException(status_code=401, detail="Non authentifié")

    # Identité robuste : la session peut ne pas porter plex_user_id (login mot de passe).
    uid = caller.get("plex_user_id")
    if not uid and caller.get("id"):
        u = db.query(PlexUser).filter(PlexUser.id == caller["id"]).first()
        uid = u.plex_user_id if u else None
    is_admin = bool(caller.get("is_owner") or caller.get("role") == "admin")
    if not uid and not is_admin:
        raise HTTPException(status_code=403, detail="Impossible d'identifier le compte demandeur.")

    req = get_or_404(db, MediaRequest, request_id, "Request not found")

    try:
        extras = _json.loads(req.extra_requesters or "[]")
    except Exception:
        extras = []
    requester_ids = ([req.plex_user_id] if req.plex_user_id else []) + [
        e.get("plex_user_id") for e in extras if e.get("plex_user_id")
    ]

    # Un non-admin ne peut annuler que s'il figure parmi les demandeurs (sinon 404, on ne
    # révèle pas l'existence de la demande).
    if not is_admin and uid not in requester_ids:
        raise HTTPException(status_code=404, detail="Request not found")

    target = uid if uid in requester_ids else None
    remaining = [rid for rid in requester_ids if rid != target] if target else []

    if not remaining:
        # Seul demandeur (ou admin annulant) : on annule la demande localement.
        _delete_vf_episode_cache(db, req.id)
        db.delete(req)
        db.commit()
        return {"status": "cancelled", "removed": True}

    # D'autres demandeurs subsistent : on reconstruit primaire + additionnels sans l'appelant.
    users = {u.plex_user_id: u for u in db.query(PlexUser).all()}

    def _name(x: str) -> str:
        u = users.get(x)
        return (u.display_name or u.plex_user_id) if u else x

    req.plex_user_id = remaining[0]
    req.plex_user = _name(remaining[0])
    req.extra_requesters = _json.dumps(
        [{"plex_user_id": x, "display_name": _name(x)} for x in remaining[1:]],
        ensure_ascii=False,
    )
    db.commit()
    return {"status": "cancelled", "removed": False}


@router.post("/requests/{request_id}/mark-processed")
def mark_request_processed(
    request_id: int,
    event: str = "available",
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
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
