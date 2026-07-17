import hmac
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import false, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import sqlalchemy

from ..database import AsyncSessionLocal
from ..dependencies import require_admin
from ..job_queue import mark_external_availability_event
from ..models import ArrInstance, MediaRequest, PlexUser, RequestStatus, Settings, VfEpisodeStatus
from ..services import radarr, sonarr
from ..services.audio_analyzer import languages_list_has_french
from ..services.availability_service import has_plex_proof, note_arr_processed
from ..services.diagnostics import record_event, update_request_context
from ..services.download_history import record_completed
from ..services.notification_orchestrator import (
    AvailabilityCandidate,
    _resolve_movie_notify_language,
    resolve_and_notify_availability,
)
from ..services.vff_scanner import scan_and_notify_availability, trigger_plex_library_refresh
from ..utils import now_utc_naive

router = APIRouter(prefix="/webhook", tags=["webhook"])
logger = logging.getLogger(__name__)

# Stockage en mémoire des derniers tests reçus (réinitialisé au redémarrage).
# Structure : {"sonarr": datetime | None, "radarr": datetime | None, "plex": datetime | None}
_last_webhook_test: dict[str, datetime | None] = {"sonarr": None, "radarr": None, "plex": None}


def _check_webhook_secret(request: Request, settings: Settings | None) -> None:
    """Vérifie le secret partagé si un webhook_secret est configuré.

    Un secret est généré automatiquement au premier démarrage (voir
    database.seed_defaults) donc ce contrôle est actif par défaut. Le secret
    peut être fourni via le header X-Webhook-Secret ou le paramètre de requête
    ?secret= (nécessaire pour Plex, qui ne permet pas de header custom sur ses
    webhooks). Si l'admin l'a explicitement révoqué, l'endpoint reste ouvert.
    """
    expected = (settings.webhook_secret if settings else None) or ""
    if not expected:
        logger.warning("Webhook reçu sans webhook_secret configuré : endpoint non authentifié")
        return
    provided = request.headers.get("X-Webhook-Secret") or request.query_params.get("secret") or ""
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="Secret de webhook invalide")


def _has_fallback_mechanism(settings: Settings, req: MediaRequest, user_obj) -> bool:
    """True si un suivi fin (scan VF ou suivi épisode sans langue) couvre ce média — dans
    ce cas on n'envoie JAMAIS le mail générique "available" en secours, même si le scan
    immédiat n'a rien trouvé cette fois : le prochain scan planifié enverra le bon jalon,
    sans jamais faire doublon avec ce mail générique (c'était la cause du "3 mails pour
    1 épisode" : le générique partait en plus du jalon, dès que le scan immédiat ratait la
    fenêtre d'indexation Plex)."""
    if not settings.vff_enabled:
        return False
    if req.media_type == "movie":
        return _resolve_movie_notify_language(settings, user_obj)
    return True  # séries : toujours couvertes (scan langue ou suivi sans langue)


def _get_recipients(user_obj, settings: Settings) -> list[str]:
    raw = (user_obj.notification_email if user_obj else None) or (settings.smtp_from if settings else "") or ""
    recipients = [e.strip() for e in raw.split(",") if e.strip()]
    admin_email = (settings.admin_notification_email or "").strip() if settings else ""
    if admin_email and user_obj and getattr(user_obj, "notify_admin", True):
        for addr in [e.strip() for e in admin_email.split(",") if e.strip()]:
            if addr not in recipients:
                recipients.append(addr)
    return recipients


async def _delete_vf_episode_cache(db: AsyncSession, request_id: int) -> None:
    await db.execute(sqlalchemy.delete(VfEpisodeStatus).where(VfEpisodeStatus.source_type == "request", VfEpisodeStatus.source_id == request_id))


def _arr_event_query(
    db: AsyncSession,
    media_type: str,
    *,
    arr_id: int | None = None,
    tmdb_id: int | str | None = None,
    tvdb_id: int | str | None = None,
    imdb_id: str | None = None,
    title: str | None = None,
    instance_id: int | None = None,
):
    q = select(MediaRequest).filter(MediaRequest.media_type == media_type)
    if instance_id:
        q = q.filter(MediaRequest.arr_instance_id == instance_id)

    candidates = []
    if arr_id:
        candidates.append(MediaRequest.arr_id == int(arr_id))
    if tmdb_id:
        candidates.append(MediaRequest.tmdb_id == str(tmdb_id))
    if tvdb_id:
        candidates.append(MediaRequest.tvdb_id == str(tvdb_id))
    if imdb_id:
        candidates.append(MediaRequest.imdb_id == str(imdb_id))

    if candidates:
        return q.filter(or_(*candidates))
    if title:
        return q.filter(MediaRequest.title.ilike(f"%{title}%"))
    return q.filter(false())


async def _mark_available_and_notify(
    title: str,
    media_type: str,
    arr_id: int | None,
    db: AsyncSession,
    settings: Settings,
    *,
    tmdb_id: int | str | None = None,
    tvdb_id: int | str | None = None,
    imdb_id: str | None = None,
    instance_id: int | None = None,
    source: str = "arr",
    instance_name: str | None = None,
    arr_detected_vf: bool = False,
):
    """Trouve les demandes correspondantes, les marque disponibles, empile les notifications.

    `arr_detected_vf` : signal rapide, non autoritaire (voir `languages_list_has_french`) —
    une piste française a été détectée par Sonarr/Radarr (ffprobe) sur le fichier qui vient
    d'être importé. Accélère uniquement la confirmation POSITIVE (has_vf=True) dès cet
    appel, avant même que Plex ait scanné le fichier ; ne remplace jamais le scan Plex qui
    suit (toujours exécuté) et n'est jamais utilisé pour conclure à une absence de VF.
    """
    q = _arr_event_query(
        db,
        media_type,
        arr_id=arr_id,
        tmdb_id=tmdb_id,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
        title=title,
        instance_id=instance_id,
    )
    requests = (await db.execute(q)).scalars().all()
    for req in requests:
        update_request_context(
            req,
            availability_source=source,
            arr_event="availability_detected",
            arr_id=arr_id,
            arr_instance=instance_name,
        )
        await record_event(
            db,
            category="arr",
            action="availability_detected",
            request=req,
            message=f"Disponibilité détectée par {source}.",
            details={"arr_id": arr_id, "instance": instance_name, "arr_detected_vf": arr_detected_vf},
        )
        if req.status == RequestStatus.available:
            # Webhook répété sur une demande déjà disponible (ex. upgrade Sonarr/Radarr
            # remplaçant un fichier VO par une release VF) : on ne refait pas le
            # bookkeeping initial, mais on retente un scan VF si la VF n'est pas
            # encore confirmée, sinon ce cas ne serait détecté qu'au prochain scan
            # planifié (jusqu'à `vff_recheck_interval_minutes`, 6h par défaut).
            if settings and req.has_vf is not True:
                if arr_detected_vf:
                    # Confirmation VF anticipée via *arr (upgrade VO -> VF) : on persiste
                    # le signal mais on laisse quand même tourner le scan Plex ci-dessous,
                    # c'est lui qui envoie la notification "VF disponible" — la sauter
                    # ferait taire cette notification alors que la VF vient d'arriver.
                    req.has_vf = True
                    req.vf_checked_at = now_utc_naive()
                    await db.commit()
                await mark_external_availability_event(req.id)
                await scan_and_notify_availability(req, settings, db)
            from ..realtime import publish

            await publish("request.updated", {"request_id": req.id}, user_id=req.plex_user_id)
            await db.commit()
            continue
        if not await has_plex_proof(db, req):
            note_arr_processed(req, arr_id=arr_id, arr_instance_id=instance_id)
            if arr_detected_vf and req.has_vf is not True:
                # Media pas encore confirmé disponible côté Plex, mais on sait déjà via
                # *arr qu'une piste VF existe sur le fichier importé — pas la peine
                # d'attendre la confirmation Plex pour connaître ça (voir docstring).
                req.has_vf = True
                req.vf_checked_at = now_utc_naive()
            await db.commit()
            logger.info(
                "Webhook %s: '%s' traite cote *arr, attente confirmation Plex avant disponibilite",
                source,
                req.title,
            )
            from ..realtime import publish

            await publish("request.updated", {"request_id": req.id}, user_id=req.plex_user_id)
            continue
        req.status = RequestStatus.available
        req.available_at = now_utc_naive()
        req.is_downloading = False
        if arr_id and not req.arr_id:
            req.arr_id = int(arr_id)
        if instance_id and not req.arr_instance_id:
            req.arr_instance_id = instance_id
        await db.commit()
        await record_completed(
            db,
            title=req.title,
            year=req.year,
            media_type=req.media_type,
            source=source,
            instance_name=instance_name,
            poster_url=req.poster_url,
            request_id=req.id,
        )
        if arr_detected_vf and req.has_vf is not True:
            # Confirmation VF anticipée via *arr (voir docstring) : le scan Plex ci-dessous
            # tourne quand même (et fera foi s'il contredit ce signal), mais si Plex n'a pas
            # encore indexé le fichier (`found: False`), cette écriture évite de rester bloqué
            # sur "VO uniquement" ou "non analysé" jusqu'au prochain scan planifié.
            req.has_vf = True
            req.vf_checked_at = now_utc_naive()
            await db.commit()
        # Scan Plex immédiat avant d'envoyer le mail générique : propose directement le
        # bon mail (VF/VO/jalon série) si VFF est actif, sans attendre le prochain scan
        # planifié. Le mail générique ne part QUE si aucun suivi fin ne couvrira jamais ce
        # média (_has_fallback_mechanism) — sinon on laisse le prochain scan planifié
        # envoyer le bon jalon, pour ne jamais faire doublon.
        await mark_external_availability_event(req.id)
        handled = await scan_and_notify_availability(req, settings, db) if settings else False
        user_obj = (await db.execute(select(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id))).scalars().first()
        if (
            not handled
            and settings
            and not _has_fallback_mechanism(settings, req, user_obj)
            and settings.email_on_available
            and not req.available_mail_sent
        ):
            await resolve_and_notify_availability(
                settings,
                req,
                db,
                candidates=[AvailabilityCandidate(scope="movie" if req.media_type == "movie" else "series_complete")],
            )
        from ..realtime import publish

        await publish("request.updated", {"request_id": req.id}, user_id=req.plex_user_id)
    return len(requests)


async def _delete_arr_requests(
    db: AsyncSession,
    media_type: str,
    *,
    arr_id: int | None = None,
    tmdb_id: int | str | None = None,
    tvdb_id: int | str | None = None,
    imdb_id: str | None = None,
    title: str | None = None,
    instance_id: int | None = None,
) -> int:
    query = _arr_event_query(
        db,
        media_type,
        arr_id=arr_id,
        tmdb_id=tmdb_id,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
        title=title,
        instance_id=instance_id,
    )
    requests = (await db.execute(query)).scalars().all()
    count = 0
    for req in requests:
        await _delete_vf_episode_cache(db, req.id)
        await db.delete(req)
        count += 1
    await db.commit()
    return count


def _query_instance_id(request: Request) -> int | None:
    raw = request.query_params.get("instance_id")
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


async def _instance_name(db: AsyncSession, instance_id: int | None) -> str | None:
    if not instance_id:
        return None
    inst = (await db.execute(select(ArrInstance).filter(ArrInstance.id == instance_id))).scalars().first()
    return inst.name if inst else None


async def _resolve_arr_connection(db: AsyncSession, service: str, instance_id: int | None) -> tuple[str, str, str] | None:
    """Résout (url, api_key, cache_key) pour l'instance *arr concernée par ce webhook.

    Utilisé pour vérifier si Sonarr/Radarr a déjà un connecteur natif "Plex Media Server"
    (voir `trigger_plex_library_refresh`) — repli sur l'instance par défaut puis sur les
    réglages globaux legacy, comme le reste des résolutions d'instance de l'app.
    """
    if instance_id:
        inst = (await db.execute(select(ArrInstance).filter(ArrInstance.id == instance_id, ArrInstance.arr_type == service))).scalars().first()
        if inst:
            return inst.url, inst.api_key, f"{service}:{inst.id}"
        return None
    inst = (await db.execute(
        select(ArrInstance).filter(ArrInstance.arr_type == service, ArrInstance.enabled, ArrInstance.is_default)
    )).scalars().first()
    if inst:
        return inst.url, inst.api_key, f"{service}:{inst.id}"
    settings = (await db.execute(select(Settings))).scalars().first()
    url = getattr(settings, f"{service}_url", None) if settings else None
    api_key = getattr(settings, f"{service}_api_key", None) if settings else None
    if url and api_key:
        return url, api_key, f"{service}:legacy"
    return None


@router.post("/sonarr")
async def sonarr_webhook(request: Request):
    """Receives Sonarr OnImport/OnDownload/Test webhook events."""
    db: AsyncSession = AsyncSessionLocal()
    try:
        settings = (await db.execute(select(Settings))).scalars().first()
        _check_webhook_secret(request, settings)

        data = await request.json()
        event = data.get("eventType", "")
        logger.info(f"Sonarr webhook: {event}")

        if event == "Test":
            _last_webhook_test["sonarr"] = datetime.now(timezone.utc)
            logger.info("Sonarr webhook test reçu avec succès")
            return {"status": "ok", "event": "Test", "message": "Webhook Sonarr opérationnel"}

        if event in ("SeriesDelete", "EpisodeFileDelete"):
            series = data.get("series", {})
            deleted = await _delete_arr_requests(
                db,
                "show",
                arr_id=series.get("id"),
                tvdb_id=series.get("tvdbId"),
                title=series.get("title", ""),
                instance_id=_query_instance_id(request),
            )
            return {"status": "ok", "deleted": deleted}

        if event not in ("Download", "Import"):
            return {"status": "ignored"}

        webhook_instance_id = _query_instance_id(request)
        if settings:
            conn = await _resolve_arr_connection(db, "sonarr", webhook_instance_id)
            await trigger_plex_library_refresh(
                settings,
                "show",
                arr_type="sonarr",
                arr_url=conn[0] if conn else None,
                arr_api_key=conn[1] if conn else None,
                cache_key=conn[2] if conn else None,
            )

        series = data.get("series", {})
        title = series.get("title", "")
        sonarr_id = series.get("id")
        tvdb_id = series.get("tvdbId")
        episode_file_media_info = (data.get("episodeFile") or {}).get("mediaInfo") or {}
        arr_detected_vf = languages_list_has_french(episode_file_media_info.get("audioLanguages"))

        matched = await _mark_available_and_notify(
            title,
            "show",
            sonarr_id,
            db,
            settings,
            tvdb_id=tvdb_id,
            instance_id=webhook_instance_id,
            source="sonarr",
            instance_name=await _instance_name(db, webhook_instance_id),
            arr_detected_vf=arr_detected_vf,
        )
        return {"status": "ok", "matched": matched}
    finally:
        await db.close()


@router.post("/radarr")
async def radarr_webhook(request: Request):
    """Receives Radarr OnDownload/OnImport/Test webhook events."""
    db: AsyncSession = AsyncSessionLocal()
    try:
        settings = (await db.execute(select(Settings))).scalars().first()
        _check_webhook_secret(request, settings)

        data = await request.json()
        event = data.get("eventType", "")
        logger.info(f"Radarr webhook: {event}")

        if event == "Test":
            _last_webhook_test["radarr"] = datetime.now(timezone.utc)
            logger.info("Radarr webhook test reçu avec succès")
            return {"status": "ok", "event": "Test", "message": "Webhook Radarr opérationnel"}

        if event in ("MovieDelete", "MovieFileDelete"):
            movie = data.get("movie", {})
            deleted = await _delete_arr_requests(
                db,
                "movie",
                arr_id=movie.get("id"),
                tmdb_id=movie.get("tmdbId"),
                imdb_id=movie.get("imdbId"),
                title=movie.get("title", ""),
                instance_id=_query_instance_id(request),
            )
            return {"status": "ok", "deleted": deleted}

        if event not in ("Download", "Import", "MovieAdded"):
            return {"status": "ignored"}

        instance_id = _query_instance_id(request)
        if settings and event in ("Download", "Import"):
            conn = await _resolve_arr_connection(db, "radarr", instance_id)
            await trigger_plex_library_refresh(
                settings,
                "movie",
                arr_type="radarr",
                arr_url=conn[0] if conn else None,
                arr_api_key=conn[1] if conn else None,
                cache_key=conn[2] if conn else None,
            )

        movie = data.get("movie", {})
        title = movie.get("title", "")
        radarr_id = movie.get("id")
        tmdb_id = movie.get("tmdbId")
        imdb_id = movie.get("imdbId")
        movie_file_media_info = (data.get("movieFile") or {}).get("mediaInfo") or {}
        arr_detected_vf = languages_list_has_french(movie_file_media_info.get("audioLanguages"))

        matched = await _mark_available_and_notify(
            title,
            "movie",
            radarr_id,
            db,
            settings,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
            instance_id=instance_id,
            arr_detected_vf=arr_detected_vf,
            source="radarr",
            instance_name=await _instance_name(db, instance_id),
        )
        return {"status": "ok", "matched": matched}
    finally:
        await db.close()


@router.post("/plex")
async def plex_webhook(request: Request):
    """Reçoit les événements Plex (library.new, media.scrobble).

    Plex envoie un multipart/form-data avec un champ `payload` contenant le JSON.
    Nécessite Plex Pass et la configuration d'un webhook dans Plex → Paramètres → Webhooks.

    Événements traités :
    - library.new       : nouveau média ajouté à la bibliothèque Plex
    - media.scrobble    : média regardé en entier (marqué comme vu)
    """
    db = AsyncSessionLocal()
    try:
        settings = (await db.execute(select(Settings))).scalars().first()
        _check_webhook_secret(request, settings)
    finally:
        await db.close()

    try:
        form = await request.form()
        raw = str(form.get("payload", ""))
        if not raw:
            # Fallback : JSON direct (certains proxys aplatissent le multipart)
            try:
                data = await request.json()
            except Exception:
                return {"status": "ignored", "reason": "empty payload"}
        else:
            data = json.loads(raw)
    except Exception as e:
        logger.warning(f"Plex webhook parse error: {e}")
        return {"status": "error", "reason": str(e)}

    event = data.get("event", "")
    logger.info(f"Plex webhook: {event}")

    # N'importe quel événement reçu de Plex confirme que le webhook fonctionne
    if event:
        _last_webhook_test["plex"] = datetime.now(timezone.utc)

    if event == "media.play" and data.get("Metadata") is None:
        # Plex envoie un event vide pour tester la connectivité
        logger.info("Plex webhook test reçu avec succès")
        return {"status": "ok", "event": "Test", "message": "Webhook Plex opérationnel"}

    if event not in ("library.new", "media.scrobble"):
        if event in ("media.play", "media.pause", "media.resume", "media.stop", "media.rate"):
            # Ces events Plex ne contiennent pas de Guid → on les ignore silencieusement
            return {"status": "ignored", "event": event}
        return {"status": "ignored", "event": event}

    metadata = data.get("Metadata", {})
    media_type_plex = metadata.get("type", "")  # "movie" ou "episode"
    title = metadata.get("title", "") or metadata.get("grandparentTitle", "")

    # Pour les épisodes, on utilise le titre de la série parente
    if media_type_plex == "episode":
        title = metadata.get("grandparentTitle", title)
        media_type = "show"
    elif media_type_plex == "movie":
        media_type = "movie"
    else:
        return {"status": "ignored", "reason": f"unsupported media type: {media_type_plex}"}

    # Extraction des identifiants depuis Metadata.Guid (liste)
    guids = metadata.get("Guid", [])
    tmdb_id = None
    tvdb_id = None
    imdb_id = None
    for g in guids:
        gid = g.get("id", "")
        if gid.startswith("tmdb://"):
            tmdb_id = gid.replace("tmdb://", "")
        elif gid.startswith("tvdb://"):
            tvdb_id = gid.replace("tvdb://", "")
        elif gid.startswith("imdb://"):
            imdb_id = gid.replace("imdb://", "")

    def _identity_filter(q):
        # Filtre par identifiant si disponible, sinon par titre
        if tmdb_id:
            return q.filter(MediaRequest.tmdb_id == tmdb_id)
        if tvdb_id:
            return q.filter(MediaRequest.tvdb_id == tvdb_id)
        if imdb_id:
            return q.filter(MediaRequest.imdb_id == imdb_id)
        return q.filter(MediaRequest.title.ilike(f"%{title}%"))

    plex_guid = metadata.get("guid")
    plex_match_method = "tmdb" if tmdb_id else "tvdb" if tvdb_id else "imdb" if imdb_id else "title"

    # Recherche et mise à jour des demandes correspondantes
    db: AsyncSession = AsyncSessionLocal()
    try:
        settings = (await db.execute(select(Settings))).scalars().first()
        q = _identity_filter(
            select(MediaRequest).filter(
                MediaRequest.status != RequestStatus.available,
                MediaRequest.media_type == media_type,
            )
        )

        requests = (await db.execute(q)).scalars().all()
        for req in requests:
            update_request_context(
                req,
                plex_match_status="confirmed",
                plex_match_method=plex_match_method,
                plex_match_title=title,
                plex_guid=plex_guid,
            )
            await record_event(
                db,
                category="plex",
                action="matched",
                request=req,
                message=f"Média Plex trouvé par {plex_match_method}.",
                details={"event": event, "plex_title": title, "plex_guid": plex_guid},
            )
            req.status = RequestStatus.available
            req.available_at = now_utc_naive()
            req.is_downloading = False
            await db.commit()
            logger.info(f"Plex webhook: '{req.title}' marqué disponible")
            await record_completed(
                db,
                title=req.title,
                year=req.year,
                media_type=req.media_type,
                source="plex",
                poster_url=req.poster_url,
                request_id=req.id,
            )
            await mark_external_availability_event(req.id)
            handled = await scan_and_notify_availability(req, settings, db) if settings else False
            user_obj = (await db.execute(select(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id))).scalars().first()
            if (
                not handled
                and settings
                and not _has_fallback_mechanism(settings, req, user_obj)
                and settings.email_on_available
                and not req.available_mail_sent
            ):
                await resolve_and_notify_availability(
                    settings,
                    req,
                    db,
                    candidates=[
                        AvailabilityCandidate(scope="movie" if req.media_type == "movie" else "series_complete")
                    ],
                )

        # « library.new » est le signal le plus fiable qui existe pour savoir que Plex a
        # fini d'indexer un média (contrairement au webhook *arr, qui peut arriver avant
        # que Plex ait scanné — course gérée jusqu'ici en différant au scan léger/complet).
        # On en profite pour retenter tout de suite le scan VF des demandes déjà
        # "disponibles" côté *arr mais encore non confirmées VF (has_vf IS NULL, jamais
        # analysé, ou False, VO suivi en attente d'upgrade) : c'est quasi garanti de
        # réussir puisque Plex vient de confirmer la présence du fichier.
        if not requests:
            await record_event(
                db,
                category="plex",
                action="not_matched",
                status="warning",
                message="Webhook Plex reçu sans demande correspondante.",
                details={"event": event, "title": title, "plex_guid": plex_guid},
            )

        rescanned = 0
        if event == "library.new" and settings:
            pending_vf_q = _identity_filter(
                select(MediaRequest).filter(
                    MediaRequest.status == RequestStatus.available,
                    MediaRequest.media_type == media_type,
                    or_(MediaRequest.has_vf.is_(None), MediaRequest.has_vf.is_(False)),
                )
            )
            for req in (await db.execute(pending_vf_q)).scalars().all():
                if await scan_and_notify_availability(req, settings, db):
                    rescanned += 1

        await db.commit()
        return {"status": "ok", "event": event, "matched": len(requests), "rescanned": rescanned, "title": title}
    finally:
        await db.close()


@router.get("/status", dependencies=[Depends(require_admin)])
def webhook_status():
    """Retourne le statut des derniers tests reçus pour chaque webhook."""

    def _fmt(dt: datetime | None) -> dict:
        if dt is None:
            return {"received": False, "at": None, "ago_seconds": None}
        ago = (datetime.now(timezone.utc) - dt).total_seconds()
        return {"received": True, "at": dt.isoformat(), "ago_seconds": int(ago)}

    return {
        "sonarr": _fmt(_last_webhook_test["sonarr"]),
        "radarr": _fmt(_last_webhook_test["radarr"]),
        "plex": _fmt(_last_webhook_test["plex"]),
    }


async def _check_live_plex() -> dict:
    """Vérifie l'état du webhook Plex à partir du dernier événement réellement reçu.

    Contrairement à Sonarr/Radarr, Plex n'expose pas d'API fiable pour déclencher un envoi
    de test à distance (l'ancien endpoint `/:/webhooks` renvoie une 404 sur les versions
    récentes) ni pour lister les webhooks enregistrés — impossible de confirmer
    l'enregistrement sans risquer un faux diagnostic. On se limite donc au signal fiable
    dont on dispose déjà : le dernier événement réel reçu par `/webhook/plex` (mis à jour
    à chaque webhook Plex traité, y compris le ping de connectivité envoyé par Plex à
    l'enregistrement de l'URL).
    """
    db: AsyncSession = AsyncSessionLocal()
    try:
        settings = (await db.execute(select(Settings))).scalars().first()
    finally:
        await db.close()
    if not settings or not settings.plex_url or not settings.plex_token:
        return {
            "instance": "Plex",
            "configured": False,
            "success": False,
            "message": "Plex non configuré (URL ou token manquant)",
        }

    last = _last_webhook_test.get("plex")
    if last:
        ago = int((datetime.now(timezone.utc) - last).total_seconds())
        return {
            "instance": "Plex",
            "configured": True,
            "success": True,
            "message": f"Dernier événement Plex reçu il y a {ago}s — le webhook fonctionne.",
        }
    return {
        "instance": "Plex",
        "configured": False,
        "success": False,
        "message": (
            "Aucun événement Plex reçu pour l'instant. Vérifie que l'URL ci-dessus est bien "
            "collée dans Plex → Paramètres → Webhooks, puis lis un média ou ajoute-en un à la "
            "bibliothèque pour déclencher un vrai événement (Plex ne permet pas de test à "
            "distance, contrairement à Sonarr/Radarr)."
        ),
    }


@router.post("/check-live/{service}", dependencies=[Depends(require_admin)])
async def check_live_webhook(service: str, instance_id: int | None = None):
    """Déclenche depuis Sonarr/Radarr un test réel du connecteur Webhook pointant vers cette app.

    Contrairement à /webhook/status (qui attend passivement un événement Test), cet endpoint
    interroge l'API Sonarr/Radarr pour retrouver le connecteur Webhook configuré (Settings →
    Connect) et lui fait déclencher lui-même un envoi de test, confirmant en direct que la
    notification temps réel fonctionnera bien à la disponibilité d'un média. Pour Plex — qui
    n'expose aucune API fiable de déclenchement à distance ni de lister ses webhooks —
    rapporte à la place le dernier événement réel reçu (voir `_check_live_plex`).
    """
    if service == "plex":
        return {"results": [await _check_live_plex()]}
    if service not in ("sonarr", "radarr"):
        raise HTTPException(status_code=400, detail="service doit être 'sonarr', 'radarr' ou 'plex'")

    client = sonarr if service == "sonarr" else radarr
    webhook_path = f"/webhook/{service}"

    db: AsyncSession = AsyncSessionLocal()
    try:
        if instance_id is not None:
            inst = (await db.execute(select(ArrInstance).filter(ArrInstance.id == instance_id, ArrInstance.arr_type == service))).scalars().first()
            if not inst:
                raise HTTPException(status_code=404, detail="Instance introuvable")
            instances = [inst]
        else:
            instances = (await db.execute(select(ArrInstance).filter(ArrInstance.arr_type == service, ArrInstance.enabled))).scalars().all()
            if not instances:
                settings = (await db.execute(select(Settings))).scalars().first()
                url = getattr(settings, f"{service}_url", None) if settings else None
                api_key = getattr(settings, f"{service}_api_key", None) if settings else None
                if url and api_key:
                    instances = [ArrInstance(name=service.capitalize(), arr_type=service, url=url, api_key=api_key)]

        if not instances:
            return {
                "results": [
                    {"instance": None, "configured": False, "success": False, "message": "Aucune instance configurée"}
                ]
            }

        results = []
        for inst in instances:
            entry = {"instance": inst.name, "instance_id": inst.id, "url": inst.url}
            try:
                notifications = await client.get_notifications(inst.url, inst.api_key)
            except Exception as e:
                entry.update(
                    {
                        "configured": False,
                        "success": False,
                        "message": f"Connexion à {service.capitalize()} impossible : {e}",
                    }
                )
                results.append(entry)
                continue

            match = client.find_webhook_notification(notifications, webhook_path)
            if not match:
                entry.update(
                    {
                        "configured": False,
                        "success": False,
                        "message": (
                            f"Aucun connecteur Webhook pointant vers {webhook_path} trouvé dans "
                            f"{service.capitalize()} → Connexions"
                        ),
                    }
                )
                results.append(entry)
                continue

            ok, msg = await client.test_notification(inst.url, inst.api_key, match)
            entry.update({"configured": True, "success": ok, "message": msg})
            if ok:
                _last_webhook_test[service] = datetime.now(timezone.utc)
            results.append(entry)

        return {"results": results}
    finally:
        await db.close()


_WEBHOOK_EVENT_FLAGS: dict[str, dict[str, bool]] = {
    # Evenements requis pour que webhook.py traite correctement les notifications (voir
    # sonarr_webhook/radarr_webhook ci-dessus : eventType in ("Download", "Import") pour la
    # disponibilite/scan VF, "SeriesDelete"/"EpisodeFileDelete" ou "MovieDelete"/
    # "MovieFileDelete" pour le nettoyage des demandes supprimees).
    "sonarr": {
        "onGrab": False,
        "onDownload": True,
        "onUpgrade": True,
        "onImportComplete": True,
        "onRename": False,
        "onSeriesAdd": False,
        "onSeriesDelete": True,
        "onEpisodeFileDelete": True,
        "onEpisodeFileDeleteForUpgrade": False,
        "onHealthIssue": False,
        "onApplicationUpdate": False,
    },
    "radarr": {
        # Pas de "onImportComplete" ici : contrairement a Sonarr (imports multi-episodes
        # partiels), Radarr n'expose pas cette notion — verifie en direct sur une instance
        # reelle, son schema renvoie `supportsOnImportComplete: null` et le champ revient
        # systematiquement a `null` apres ecriture. L'inclure ici faisait boucler
        # "Configurer automatiquement" en boucle sur "corrige" a chaque clic, la comparaison
        # (null != True) semblant toujours en desaccord alors que rien n'est reellement a
        # corriger.
        "onGrab": False,
        "onDownload": True,
        "onUpgrade": True,
        "onRename": False,
        "onMovieAdded": False,
        "onMovieDelete": True,
        "onMovieFileDelete": True,
        "onMovieFileDeleteForUpgrade": False,
        "onHealthIssue": False,
        "onApplicationUpdate": False,
    },
}


class ConfigureWebhookRequest(BaseModel):
    webhook_url: str


@router.post("/configure/{service}", dependencies=[Depends(require_admin)])
async def configure_webhook(service: str, body: ConfigureWebhookRequest, instance_id: int | None = None):
    """Crée ou corrige automatiquement le connecteur Webhook Sonarr/Radarr pointant vers cette app.

    Si un connecteur webhook existe déjà (retrouvé via l'URL /webhook/{service}) mais avec des
    événements manquants (cas réel rencontré : "On Download" désactivé, empêchant toute
    notification lors d'un import automatique classique), il est corrigé en place. Sinon un
    nouveau connecteur est créé à partir du schéma Sonarr/Radarr, avec uniquement les
    événements dont webhook.py a besoin pour fonctionner.
    """
    if service not in ("sonarr", "radarr"):
        raise HTTPException(status_code=400, detail="service doit être 'sonarr' ou 'radarr'")

    client = sonarr if service == "sonarr" else radarr
    webhook_path = f"/webhook/{service}"
    desired_flags = _WEBHOOK_EVENT_FLAGS[service]

    db: AsyncSession = AsyncSessionLocal()
    try:
        if instance_id is not None:
            inst = (await db.execute(select(ArrInstance).filter(ArrInstance.id == instance_id, ArrInstance.arr_type == service))).scalars().first()
            if not inst:
                raise HTTPException(status_code=404, detail="Instance introuvable")
            instances = [inst]
        else:
            instances = (await db.execute(select(ArrInstance).filter(ArrInstance.arr_type == service, ArrInstance.enabled))).scalars().all()
            if not instances:
                settings = (await db.execute(select(Settings))).scalars().first()
                url = getattr(settings, f"{service}_url", None) if settings else None
                api_key = getattr(settings, f"{service}_api_key", None) if settings else None
                if url and api_key:
                    instances = [ArrInstance(name=service.capitalize(), arr_type=service, url=url, api_key=api_key)]

        if not instances:
            return {"results": [{"instance": None, "success": False, "message": "Aucune instance configurée"}]}

        results = []
        for inst in instances:
            entry = {"instance": inst.name, "instance_id": inst.id}
            try:
                notifications = await client.get_notifications(inst.url, inst.api_key)
            except Exception as e:
                entry.update({"success": False, "message": f"Connexion à {service.capitalize()} impossible : {e}"})
                results.append(entry)
                continue

            try:
                existing = client.find_webhook_notification(notifications, webhook_path)
                if existing:
                    changed = False
                    for key, val in desired_flags.items():
                        if existing.get(key) != val:
                            existing[key] = val
                            changed = True
                    for field in existing.get("fields", []):
                        if field.get("name") == "url" and field.get("value") != body.webhook_url:
                            field["value"] = body.webhook_url
                            changed = True
                    if changed:
                        await client.update_notification(inst.url, inst.api_key, existing)
                        entry.update({"success": True, "message": "Connecteur existant corrigé (événements manquants activés)."})
                    else:
                        entry.update({"success": True, "message": "Déjà correctement configuré."})
                else:
                    schema = await client.get_webhook_schema(inst.url, inst.api_key)
                    if not schema:
                        entry.update({"success": False, "message": "Schéma du connecteur Webhook introuvable."})
                        results.append(entry)
                        continue
                    payload = client.build_webhook_payload(schema, body.webhook_url, desired_flags)
                    await client.create_notification(inst.url, inst.api_key, payload)
                    entry.update({"success": True, "message": "Connecteur webhook créé."})
            except Exception as e:
                entry.update({"success": False, "message": str(e)})
            results.append(entry)

        return {"results": results}
    finally:
        await db.close()


@router.get("/plex-connector-status/{service}", dependencies=[Depends(require_admin)])
async def plex_connector_status(service: str, instance_id: int | None = None):
    """Vérifie si Sonarr/Radarr a déjà un connecteur natif "Plex Media Server" actif.

    Si oui, notre propre refresh de section Plex (déclenché à chaque webhook Download/
    Import, voir `trigger_plex_library_refresh`) est redondant : l'*arr notifie déjà Plex
    directement avec un scan ciblé sur le dossier importé, plus précis que le nôtre.
    """
    if service not in ("sonarr", "radarr"):
        raise HTTPException(status_code=400, detail="service doit être 'sonarr' ou 'radarr'")

    client = sonarr if service == "sonarr" else radarr

    db: AsyncSession = AsyncSessionLocal()
    try:
        if instance_id is not None:
            inst = (await db.execute(select(ArrInstance).filter(ArrInstance.id == instance_id, ArrInstance.arr_type == service))).scalars().first()
            if not inst:
                raise HTTPException(status_code=404, detail="Instance introuvable")
            instances = [inst]
        else:
            instances = (await db.execute(select(ArrInstance).filter(ArrInstance.arr_type == service, ArrInstance.enabled))).scalars().all()
            if not instances:
                settings = (await db.execute(select(Settings))).scalars().first()
                url = getattr(settings, f"{service}_url", None) if settings else None
                api_key = getattr(settings, f"{service}_api_key", None) if settings else None
                if url and api_key:
                    instances = [ArrInstance(name=service.capitalize(), arr_type=service, url=url, api_key=api_key)]

        if not instances:
            return {
                "results": [
                    {"instance": None, "configured": False, "success": False, "message": "Aucune instance configurée"}
                ]
            }

        results = []
        for inst in instances:
            entry = {"instance": inst.name, "instance_id": inst.id}
            try:
                notifications = await client.get_notifications(inst.url, inst.api_key)
            except Exception as e:
                entry.update(
                    {
                        "configured": False,
                        "success": False,
                        "message": f"Connexion à {service.capitalize()} impossible : {e}",
                    }
                )
                results.append(entry)
                continue

            match = client.find_plex_notification(notifications)
            if match:
                entry.update(
                    {
                        "configured": True,
                        "success": True,
                        "message": (
                            f"Connecteur natif 'Plex Media Server' actif dans {service.capitalize()} — "
                            "notre propre refresh de section est automatiquement désactivé pour cette instance."
                        ),
                    }
                )
            else:
                entry.update(
                    {
                        "configured": False,
                        "success": True,
                        "message": (
                            f"Aucun connecteur natif Plex trouvé dans {service.capitalize()} → Connexions — "
                            "notre refresh de section Plex prend le relais à chaque import."
                        ),
                    }
                )
            results.append(entry)

        return {"results": results}
    finally:
        await db.close()
