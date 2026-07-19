import json as _json
import logging
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import sqlalchemy
import asyncio

from ..database import get_db_async
from ..dependencies import current_user, require_admin, require_auth
from ..models import AdminActionLog, ArrInstance, DeletedMediaLog, DownloadClient, LibraryItem, MediaRequest, PlexUser, RequestStatus, Settings, VfEpisodeStatus
from ..scheduler import check_arr_statuses, poll_watchlists
from ..services.notification_orchestrator import _notify, notify_single_user
from ..services.request_lifecycle import transition_request
from ..services import arr_orphans, deleted_media, radarr, sonarr
from ..utils import async_get_or_404, now_utc_naive, parse_email_list

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["requests"], dependencies=[Depends(require_auth)])


def _caller_plex_user_id(request, db: AsyncSession) -> str | None:
    caller = current_user(request, db)
    if not caller or caller.get("is_owner") or caller.get("role") == "admin":
        return None
    return caller.get("plex_user_id")


async def _ensure_request_visible(req: MediaRequest, request, db: AsyncSession) -> None:
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


class BulkResolveFilters(BaseModel):
    type: Optional[str] = None
    view: Optional[str] = None
    search: Optional[str] = None
    user: Optional[str] = None
    status: Optional[str] = None
    source: Optional[str] = None
    vf: Optional[str] = None


async def _bulk_request_ids_for_filters(db: AsyncSession, filters: BulkResolveFilters) -> list[int]:
    q = select(MediaRequest)
    if filters.type in ("movie", "show"):
        q = q.filter(MediaRequest.media_type == filters.type)
    if filters.search:
        q = q.filter(MediaRequest.title.ilike(f"%{filters.search}%"))
    if filters.user:
        q = q.filter(
            or_(
                MediaRequest.plex_user_id == filters.user,
                MediaRequest.extra_requesters.like(f'%"plex_user_id": "{filters.user}"%'),
                MediaRequest.extra_requesters.like(f'%"plex_user_id":"{filters.user}"%'),
            )
        )
    if filters.status:
        q = q.filter(MediaRequest.status == filters.status)
        if filters.status == RequestStatus.partially_available:
            # Meme raffinement que la vue "En cours" cote frontend (RequestsView.vue) et
            # le compteur dashboard (_is_show_genuinely_incomplete, metrics_api.py) : une
            # serie encore en diffusion mais a jour sur tout ce qui est deja sorti n'a rien
            # de "non complet" a proprement parler.
            q = q.filter(
                MediaRequest.episodes_aired_count.isnot(None),
                MediaRequest.episodes_aired_count > 0,
                MediaRequest.episodes_available_count < MediaRequest.episodes_aired_count,
            )
    if filters.source:
        q = q.filter(MediaRequest.source == filters.source)

    vf = filters.vf
    if vf == "vf":
        ids = select(LibraryItem.id).filter(LibraryItem.has_vf.is_(True))
        q = q.filter(MediaRequest.library_item_id.in_(ids))
    elif vf in ("vo", "season_partial", "episode_partial"):
        ids = select(LibraryItem.id).filter(LibraryItem.has_vf.is_(False))
        if vf != "vo":
            ids = ids.filter(LibraryItem.vf_granularity == vf)
        q = q.filter(MediaRequest.library_item_id.in_(ids))
    elif vf == "vf_secondary":
        ids = (
            select(VfEpisodeStatus.source_id)
            .filter(
                VfEpisodeStatus.source_type == "library_item",
                VfEpisodeStatus.has_vf.is_(True),
                VfEpisodeStatus.fr_is_default.is_(False),
            )
            .distinct()
        )
        q = q.filter(MediaRequest.library_item_id.in_(ids))
    elif vf == "unchecked":
        ids = select(LibraryItem.id).filter(LibraryItem.has_vf.is_(None))
        q = q.filter(MediaRequest.library_item_id.in_(ids))
    elif vf == "requested":
        q = q.filter(MediaRequest.library_item_id.is_(None))
    elif vf == "plex_anomaly":
        q = q.filter(
            MediaRequest.status == RequestStatus.available,
            MediaRequest.library_item_id.is_(None),
            MediaRequest.is_downloading.is_(False),
        )

    rows = (await db.execute(q.order_by(MediaRequest.requested_at.desc()))).scalars().all()
    return [r.id for r in rows]


async def _delete_media_from_arr(db: AsyncSession, req: MediaRequest, delete_files: bool) -> tuple[bool, str]:
    """Tente de supprimer le média correspondant dans Sonarr/Radarr et Seer.

    Ne renvoie jamais ok=True suite à une erreur réseau/HTTP pour Sonarr/Radarr.
    La suppression dans Seer est "best effort" et ne bloque pas la suppression locale.
    """
    # 1. Suppression Seer (best effort, mode acteur uniquement : en observateur on ne
    # modifie jamais l'état de Seer, on se contente de le lire)
    try:
        settings = (await db.execute(select(Settings))).scalars().first()
        from ..services.seer import delete_request_by_tmdb, resolve_mode

        if settings and resolve_mode(settings) == "actor" and req.tmdb_id:
            await delete_request_by_tmdb(
                settings.seer_url,
                settings.seer_api_key,
                req.media_type,
                req.tmdb_id,
            )
    except Exception as e:
        logger.warning(f"Erreur non fatale lors de la suppression Seer pour req#{req.id}: {e}")

    # 2. Suppression Sonarr/Radarr
    if not req.arr_id or not req.arr_instance_id:
        return True, "Aucune instance *arr liée à cette demande"
    if req.arr_slug and req.arr_slug.startswith("prowlarr:"):
        return True, "Gérée par Prowlarr, rien à supprimer côté *arr"

    inst = (await db.execute(select(ArrInstance).filter(ArrInstance.id == req.arr_instance_id))).scalars().first()
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
async def update_requesters(request_id: int, body: RequestersUpdate, db: AsyncSession = Depends(get_db_async)):
    """Définit la liste des demandeurs d'une demande (le 1er = demandeur principal,
    les suivants = demandeurs additionnels). Modification manuelle : **aucun mail** n'est
    envoyé automatiquement ici (les futures notifications de la demande incluront
    désormais tous les demandeurs, voir `_get_recipients`/`_resolve_requester_users`) —
    pour renvoyer rétroactivement un mail déjà parti à un demandeur nouvellement ajouté,
    voir `POST /requests/{request_id}/notify-user`."""
    req = await async_get_or_404(db, MediaRequest, request_id, "Request not found")

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

    users = {u.plex_user_id: u for u in (await db.execute(select(PlexUser))).scalars().all()}

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
    await db.commit()
    return {"ok": True, "requester_ids": ordered}


class NotifyUserRequest(BaseModel):
    plex_user_id: str
    events: list[str]


@router.post("/requests/{request_id}/notify-user", dependencies=[Depends(require_admin)])
async def notify_single_requester(request_id: int, body: NotifyUserRequest, db: AsyncSession = Depends(get_db_async)):
    """Renvoie rétroactivement le mail "demande" et/ou "disponibilité" à UN SEUL
    demandeur — utilisé quand un co-demandeur est ajouté après coup à une demande déjà
    en cours et que l'admin confirme explicitement vouloir le rattraper (voir
    MediaDetailDrawer.vue::addRequester, jamais déclenché automatiquement)."""
    req = await async_get_or_404(db, MediaRequest, request_id, "Request not found")
    settings = (await db.execute(select(Settings))).scalars().first()
    if not settings:
        raise HTTPException(400, "Paramètres introuvables")
    events = [e for e in body.events if e in ("request", "available")]
    if not events:
        raise HTTPException(400, "events doit contenir 'request' et/ou 'available'")
    queued = [event for event in events if await notify_single_user(event, settings, req, db, body.plex_user_id)]
    return {"status": "ok", "queued": queued}


async def _delete_vf_episode_cache(db: AsyncSession, request_id: int) -> None:
    """Purge le cache VF par épisode d'une demande supprimée (évite les lignes orphelines)."""
    await db.execute(sqlalchemy.delete(VfEpisodeStatus).where(VfEpisodeStatus.source_type == "request", VfEpisodeStatus.source_id == request_id))


@router.get("/requests")
async def list_requests(query: Optional[str] = None, request: Request = None, db: AsyncSession = Depends(get_db_async)):
    q = select(MediaRequest)
    uid = _caller_plex_user_id(request, db) if request else None
    if uid:
        q = q.filter(
            (MediaRequest.plex_user_id == uid)
            | (MediaRequest.extra_requesters.like(f'%"plex_user_id": "{uid}"%'))
            | (MediaRequest.extra_requesters.like(f'%"plex_user_id":"{uid}"%'))
        )
    if query:
        q = q.filter(MediaRequest.title.ilike(f"%{query}%"))
    # RequestsView.vue charge la liste entiere puis filtre cote client (statut/type/
    # source/demandeur) -- une limite trop basse tronquait silencieusement les demandes
    # les plus anciennes encore ouvertes (regression production : des films "sent_to_arr"
    # de mars, plus vieux que les 200 lignes les plus recentes toutes tendances confondues,
    # disparaissaient de la vue alors qu'ils etaient toujours reellement en cours cote
    # Radarr). Relevee tres au-dela d'un volume realiste plutot que supprimee : garde un
    # garde-fou contre une croissance non bornee.
    return (await db.execute(q.order_by(MediaRequest.requested_at.desc()).limit(5000))).scalars().all()


@router.get("/requests/orphans")
async def list_orphan_requests(db: AsyncSession = Depends(get_db_async)):
    """Séries/films surveillés par Sonarr/Radarr mais jamais passés par une demande
    Plexarr (ajoutés directement dans l'un des deux) et pas encore complets.

    Affichées à part sur la page Demandes (badge "Suivi Sonarr/Radarr", pas de
    demandeur ni d'actions de workflow — seule la suppression via `DELETE
    /requests/orphans/{arr_type}/{instance_id}/{arr_id}` s'applique, en agissant
    directement sur Sonarr/Radarr).
    """
    shows = await arr_orphans.find_orphan_shows(db)
    movies = await arr_orphans.find_orphan_movies(db)
    return shows + movies


@router.post("/requests/orphans/{arr_type}/{instance_id}/{arr_id}/open")
async def open_orphan_detail(arr_type: str, instance_id: int, arr_id: int, db: AsyncSession = Depends(get_db_async)):
    """Ouvre la fiche detaillee d'un item "Suivi Sonarr/Radarr" : materialise (ou
    retrouve) le LibraryItem correspondant, pour que le frontend puisse naviguer vers
    /media/library/{id} comme pour n'importe quel autre media de la bibliotheque."""
    if arr_type not in ("sonarr", "radarr"):
        raise HTTPException(400, "arr_type doit etre 'sonarr' ou 'radarr'")
    inst = await async_get_or_404(db, ArrInstance, instance_id, "Arr instance not found")
    li = await arr_orphans.materialize_orphan_library_item(db, inst, arr_type, arr_id)
    await db.commit()
    return {"library_item_id": li.id}


@router.delete("/requests/orphans/{arr_type}/{instance_id}/{arr_id}", dependencies=[Depends(require_admin)])
async def delete_orphan_request(
    arr_type: str, instance_id: int, arr_id: int, request: Request,
    delete_files: bool = False, db: AsyncSession = Depends(get_db_async),
):
    """Supprime une série/film orpheline directement dans Sonarr/Radarr (pas de
    MediaRequest à supprimer côté Plexarr, il n'y en a jamais eu)."""
    if arr_type not in ("sonarr", "radarr"):
        raise HTTPException(400, "arr_type doit etre 'sonarr' ou 'radarr'")
    inst = await async_get_or_404(db, ArrInstance, instance_id, "Arr instance not found")
    # Récupéré avant suppression : une fois le média retiré de Sonarr/Radarr, il n'y a
    # plus aucun moyen de retrouver son tvdb_id/tmdb_id pour la trace de suppression.
    if arr_type == "sonarr":
        item = await sonarr.lookup_series(inst.url, inst.api_key, arr_id=arr_id)
        title, tvdb_id, tmdb_id, imdb_id = (item or {}).get("title", "?"), (item or {}).get("tvdbId"), None, None
    else:
        item = await radarr.lookup_movie(inst.url, inst.api_key, arr_id=arr_id)
        title, tvdb_id, tmdb_id, imdb_id = (item or {}).get("title", "?"), None, (item or {}).get("tmdbId"), (item or {}).get("imdbId")

    if arr_type == "sonarr":
        ok, message = await sonarr.delete_series(inst.url, inst.api_key, arr_id, delete_files=delete_files)
    else:
        ok, message = await radarr.delete_movie(inst.url, inst.api_key, arr_id, delete_files=delete_files)
    if not ok:
        raise HTTPException(502, message)

    actor = current_user(request, db) or {}
    await deleted_media.record_deletion(
        db, "show" if arr_type == "sonarr" else "movie", title,
        tmdb_id=tmdb_id, tvdb_id=tvdb_id, imdb_id=imdb_id,
        deleted_by=actor.get("username") or actor.get("plex_user_id") or "api",
    )
    await db.commit()
    # Sans ca, l'item supprime resterait visible jusqu'a expiration du cache orphelins
    # (voir arr_orphans.py) au lieu de disparaitre immediatement de la page Bibliotheque.
    await arr_orphans._invalidate_orphans_cache()
    return {"status": "ok", "message": message}


@router.get("/requests/deleted-log", dependencies=[Depends(require_admin)])
async def list_deleted_media_log(db: AsyncSession = Depends(get_db_async)):
    """Médias volontairement supprimés par un admin (demande ou orpheline arr) —
    toute nouvelle demande pour l'un de ces titres est forcée en attente
    d'approbation tant qu'il figure ici. Voir app.services.deleted_media."""
    rows = (await db.execute(
        select(DeletedMediaLog).order_by(DeletedMediaLog.deleted_at.desc())
    )).scalars().all()
    return rows


@router.delete("/requests/deleted-log/{log_id}", dependencies=[Depends(require_admin)])
async def forget_deleted_media_log(log_id: int, db: AsyncSession = Depends(get_db_async)):
    """Oublie une suppression : une nouvelle demande pour ce média ne sera plus
    forcée en attente d'approbation."""
    row = await async_get_or_404(db, DeletedMediaLog, log_id, "Log entry not found")
    await db.delete(row)
    await db.commit()
    return {"status": "ok"}


@router.get("/plex/library-search")
async def plex_library_search(query: str, db: AsyncSession = Depends(get_db_async)):
    """Cherche un titre dans la bibliothèque Plex locale."""
    s = (await db.execute(select(Settings))).scalars().first()
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
async def list_pending_requests(db: AsyncSession = Depends(get_db_async)):
    """File des demandes en attente de validation (admin). Déclaré avant
    /requests/{request_id} pour ne pas être capté par le param int."""
    from ..serializers import serialize_media_request

    reqs = (await db.execute(select(MediaRequest).filter(MediaRequest.status == RequestStatus.pending_approval).order_by(MediaRequest.requested_at.desc()))).scalars().all()
    users = {u.plex_user_id: (u.custom_name or u.display_name or u.plex_user_id) for u in (await db.execute(select(PlexUser))).scalars().all()}
    return [serialize_media_request(r, users) for r in reqs]


@router.post("/requests/bulk/resolve", dependencies=[Depends(require_admin)])
async def resolve_bulk_requests(body: BulkResolveFilters, db: AsyncSession = Depends(get_db_async)):
    ids = await _bulk_request_ids_for_filters(db, body)
    return {"status": "success", "count": len(ids), "ids": ids}


@router.get("/requests/{request_id}")
async def get_request(request_id: int, request: Request, db: AsyncSession = Depends(get_db_async)):
    req = await async_get_or_404(db, MediaRequest, request_id, "Request not found")
    await _ensure_request_visible(req, request, db)
    d = {c.name: getattr(req, c.name) for c in req.__table__.columns}

    # Utilise le sérialiseur centralisé pour les formats de dates
    from ..serializers import format_datetime

    d["requested_at"] = format_datetime(req.requested_at)
    d["available_at"] = format_datetime(req.available_at)

    if req.torrent_hash and req.download_client_id:
        client = (await db.execute(select(DownloadClient).filter(DownloadClient.id == req.download_client_id))).scalars().first()
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

    settings = (await db.execute(select(Settings))).scalars().first()
    user_obj = (await db.execute(select(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id))).scalars().first()
    raw = (user_obj.notification_email if user_obj else None) or (settings.smtp_from if settings else "") or ""
    user_emails = parse_email_list(raw)
    notify_admin = bool(user_obj and getattr(user_obj, "notify_admin", True))
    admin_emails = parse_email_list(settings.admin_notification_email if settings and notify_admin else None)
    d["_user_emails"] = user_emails
    d["_admin_emails"] = admin_emails
    d["_notify_admin"] = notify_admin

    users = {u.plex_user_id: (u.custom_name or u.display_name or u.plex_user_id) for u in (await db.execute(select(PlexUser))).scalars().all()}
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
async def bulk_retry_requests(body: BulkAction, db: AsyncSession = Depends(get_db_async)):
    """Repasse plusieurs demandes en pending et lance un polling."""
    reqs = (await db.execute(select(MediaRequest).filter(MediaRequest.id.in_(body.ids)))).scalars().all()
    count = 0
    for req in reqs:
        if req.status in ("failed", "pending"):
            await transition_request(db, req, "retry", source="manual_bulk")
            count += 1
    if count > 0:
        await db.commit()
        await poll_watchlists()
    return {"status": "success", "count": count}


@router.post("/requests/bulk/mark-processed", dependencies=[Depends(require_admin)])
async def bulk_mark_requests_processed(body: BulkAction, request: Request, db: AsyncSession = Depends(get_db_async)):
    """Marque plusieurs demandes comme traitées (disponibles) sans email."""
    reqs = (await db.execute(select(MediaRequest).filter(MediaRequest.id.in_(body.ids)))).scalars().all()
    items = []
    for req in reqs:
        before_status = req.status.value if hasattr(req.status, "value") else req.status
        await transition_request(db, req, "available", source="manual_admin")
        req.request_mail_sent = True
        req.available_mail_sent = True
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
    await db.commit()
    return {"status": "success", "count": len(reqs)}


@router.post("/requests/bulk/delete", dependencies=[Depends(require_admin)])
async def bulk_delete_requests(body: BulkAction, request: Request, db: AsyncSession = Depends(get_db_async)):
    """Supprime plusieurs demandes définitivement.

    Si `delete_from_arr=True`, tente aussi la suppression côté Sonarr/Radarr avant
    chaque suppression locale : si *arr est injoignable pour une demande donnée, celle-ci
    est laissée intacte (ni suppression locale ni *arr) plutôt que de désynchroniser les
    deux côtés — les autres demandes de la sélection sont traitées normalement.
    """
    reqs = (await db.execute(select(MediaRequest).filter(MediaRequest.id.in_(body.ids)))).scalars().all()
    actor = current_user(request, db) or {}
    deleted_by = actor.get("username") or actor.get("plex_user_id") or "api"
    count = 0
    skipped = []
    for req in reqs:
        if body.delete_from_arr:
            ok, msg = await _delete_media_from_arr(db, req, body.delete_files)
            if not ok:
                skipped.append({"id": req.id, "title": req.title, "reason": msg})
                continue
        await deleted_media.record_deletion(
            db, req.media_type, req.title,
            tmdb_id=req.tmdb_id, tvdb_id=req.tvdb_id, imdb_id=req.imdb_id, deleted_by=deleted_by,
        )
        await _delete_vf_episode_cache(db, req.id)
        await db.delete(req)
        count += 1
    await db.commit()
    return {"status": "success", "count": count, "skipped": skipped}


class RejectBody(BaseModel):
    reason: Optional[str] = None


@router.post("/requests/{request_id}/approve", dependencies=[Depends(require_admin)])
async def approve_request(request_id: int, request: Request, db: AsyncSession = Depends(get_db_async)):
    """Valide une demande en attente : la transmet à *arr et bascule en sent_to_arr."""
    from ..services.watchlist_poller import _submit_to_arr

    req = await async_get_or_404(db, MediaRequest, request_id, "Request not found")
    if req.status != RequestStatus.pending_approval:
        raise HTTPException(400, "Seules les demandes en attente de validation peuvent être approuvées.")

    settings = (await db.execute(select(Settings))).scalars().first()
    user_obj = (await db.execute(select(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id))).scalars().first()
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
    await transition_request(db, req, "submitted", source=item.get("_attempted_target") or "manual")
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
    await db.commit()

    if settings:
        await _notify("request", settings, req, db)
    return {"ok": True, "status": "sent_to_arr", "id": req.id}


@router.post("/requests/{request_id}/reject", dependencies=[Depends(require_admin)])
async def reject_request(request_id: int, body: RejectBody, request: Request, db: AsyncSession = Depends(get_db_async)):
    """Refuse une demande en attente (conservée en historique avec le motif)."""
    req = await async_get_or_404(db, MediaRequest, request_id, "Request not found")
    if req.status != RequestStatus.pending_approval:
        raise HTTPException(400, "Seules les demandes en attente de validation peuvent être refusées.")
    await transition_request(db, req, "rejected", source="manual_admin", message=body.reason)
    req.rejected_reason = (body.reason or "").strip() or None
    caller = current_user(request, db)
    req.approved_by = (caller or {}).get("plex_user_id") or "admin"
    req.approved_at = now_utc_naive()
    await db.commit()
    return {"ok": True, "status": "rejected", "id": req.id}


@router.post("/requests/{request_id}/retry", dependencies=[Depends(require_admin)])
async def retry_request(request_id: int, db: AsyncSession = Depends(get_db_async)):
    """Repasse une demande en `pending` et déclenche un polling immédiat."""
    req = await async_get_or_404(db, MediaRequest, request_id, "Request not found")
    if req.status not in ("failed", "pending"):
        raise HTTPException(400, "Only failed or pending requests can be retried")
    await transition_request(db, req, "retry", source="manual")
    await db.commit()
    await poll_watchlists()
    return {"status": "retrying"}


@router.post("/requests/retry-failed", dependencies=[Depends(require_admin)])
async def retry_all_failed(db: AsyncSession = Depends(get_db_async)):
    """Repasse toutes les demandes 'failed' en 'pending' et déclenche un polling."""
    failed = (await db.execute(select(MediaRequest).filter(MediaRequest.status == "failed"))).scalars().all()
    count = len(failed)
    for req in failed:
        await transition_request(db, req, "retry", source="manual_bulk")
    await db.commit()
    await poll_watchlists()
    return {"status": "ok", "retried": count}


@router.post("/requests/recalculate-dates", dependencies=[Depends(require_admin)])
async def recalculate_dates(db: AsyncSession = Depends(get_db_async)):
    """Re-joue sync_seer_requests et sync_plex_dates pour corriger requested_at et available_at."""
    from ..scheduler import sync_seer_requests
    from ..services.watchlist_poller import sync_plex_dates

    await sync_seer_requests()
    await sync_plex_dates(db)
    return {"status": "ok"}


@router.post("/requests/merge-duplicates", dependencies=[Depends(require_admin)])
async def merge_duplicates_endpoint():
    """Fusionne les MediaRequest en double (même tmdb_id toutes sources)."""
    from scripts.merge_duplicate_requests import merge_duplicates

    await asyncio.to_thread(merge_duplicates, dry_run=False)
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
    request: Request,
    delete_from_arr: bool = False,
    delete_files: bool = False,
    db: AsyncSession = Depends(get_db_async),
    _: None = Depends(require_admin),
):
    """Supprime une demande. Si `delete_from_arr=True`, supprime aussi le média dans
    Sonarr/Radarr — mais seulement si cette suppression réussit (ou que le média y est
    déjà absent) : si *arr est injoignable, rien n'est supprimé du tout (ni côté *arr,
    ni localement) pour ne jamais désynchroniser les deux."""
    req = await async_get_or_404(db, MediaRequest, request_id, "Request not found")
    if delete_from_arr:
        ok, msg = await _delete_media_from_arr(db, req, delete_files)
        if not ok:
            raise HTTPException(502, f"Suppression *arr impossible ({msg}) — rien n'a été supprimé.")
    actor = current_user(request, db) or {}
    await deleted_media.record_deletion(
        db, req.media_type, req.title,
        tmdb_id=req.tmdb_id, tvdb_id=req.tvdb_id, imdb_id=req.imdb_id,
        deleted_by=actor.get("username") or actor.get("plex_user_id") or "api",
    )
    await _delete_vf_episode_cache(db, req.id)
    await db.delete(req)
    await db.commit()
    return {"status": "deleted"}


@router.post("/requests/{request_id}/cancel")
async def cancel_own_request(request_id: int, request: Request, db: AsyncSession = Depends(get_db_async)):
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
        u = (await db.execute(select(PlexUser).filter(PlexUser.id == caller["id"]))).scalars().first()
        uid = u.plex_user_id if u else None
    is_admin = bool(caller.get("is_owner") or caller.get("role") == "admin")
    if not uid and not is_admin:
        raise HTTPException(status_code=403, detail="Impossible d'identifier le compte demandeur.")

    req = await async_get_or_404(db, MediaRequest, request_id, "Request not found")

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
        await _delete_vf_episode_cache(db, req.id)
        await db.delete(req)
        await db.commit()
        return {"status": "cancelled", "removed": True}

    # D'autres demandeurs subsistent : on reconstruit primaire + additionnels sans l'appelant.
    users = {u.plex_user_id: u for u in (await db.execute(select(PlexUser))).scalars().all()}

    def _name(x: str) -> str:
        u = users.get(x)
        return (u.display_name or u.plex_user_id) if u else x

    req.plex_user_id = remaining[0]
    req.plex_user = _name(remaining[0])
    req.extra_requesters = _json.dumps(
        [{"plex_user_id": x, "display_name": _name(x)} for x in remaining[1:]],
        ensure_ascii=False,
    )
    await db.commit()
    return {"status": "cancelled", "removed": False}


@router.post("/requests/{request_id}/mark-processed")
async def mark_request_processed(
    request_id: int,
    event: str = "available",
    notify: bool = True,
    stop_vf_tracking: bool = False,
    db: AsyncSession = Depends(get_db_async),
    _: None = Depends(require_admin),
):
    """Envoie manuellement le mail "demande" ou "disponible" pour une requête, et/ou
    clôture le suivi VF.

    `stop_vf_tracking` pose `vf_tracking_disabled` : la demande sort définitivement des
    scans VF périodiques (check_vf_statuses) — utile pour une demande VO qu'on sait ne
    jamais avoir de VF, ou dont on ne veut simplement plus suivre l'évolution.
    """
    req = await async_get_or_404(db, MediaRequest, request_id, "Request not found")
    settings = (await db.execute(select(Settings))).scalars().first()

    if event == "request":
        if settings and notify:
            await _notify("request", settings, req, db, force=True, triggered_by="manual")
        req.request_mail_sent = True
    else:
        event = "available"
        if settings and notify:
            await _notify("available", settings, req, db, force=True, triggered_by="manual")
        await transition_request(db, req, "available", source="manual_admin")
        req.available_mail_sent = True

    if stop_vf_tracking:
        req.vf_tracking_disabled = True

    await db.commit()

    return {
        "status": "success",
        "message": "Demande marquée comme traitée",
        "notified": notify,
        "event": event,
        "vf_tracking_disabled": req.vf_tracking_disabled,
    }


@router.post("/requests/{request_id}/resend-mail")
async def resend_request_mail(
    request_id: int,
    event: str,
    db: AsyncSession = Depends(get_db_async),
    _: None = Depends(require_admin),
):
    """Renvoie manuellement le mail de demande ou de disponibilité, sans modifier le statut.

    Contrairement à `mark-processed`, ne force jamais le statut à "available" ni ne
    touche aux flags `*_mail_sent` directement : ceux-ci sont mis à jour par le worker
    de notification une fois l'envoi réellement confirmé (voir notification_queue._process).
    """
    if event not in ("request", "available"):
        raise HTTPException(400, "event doit être 'request' ou 'available'")
    req = await async_get_or_404(db, MediaRequest, request_id, "Request not found")
    settings = (await db.execute(select(Settings))).scalars().first()
    if not settings:
        raise HTTPException(400, "Paramètres introuvables")
    await _notify(event, settings, req, db, force=True, triggered_by="manual")
    return {"status": "queued", "event": event}
