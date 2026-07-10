import asyncio
import logging
import re
import time

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import ArrInstance, DownloadClient, MediaRequest, PollHistory, RequestStatus, Settings, VfEpisodeStatus
from ..utils import now_utc, now_utc_naive
from . import notification_orchestrator, watchlist_poller
from .download_clients import delete_torrent, get_torrent_status
from .download_history import record_completed
from .notification_orchestrator import _handle_show_progress_notification
from .radarr import get_all_movies, get_queue_movie_ids, is_movie_available, movie_exists
from .seer import is_request_available as seer_available
from .sonarr import get_all_series, get_queue_series_ids, get_series_episode_stats, is_series_available, series_exists
from .watchlist_poller import _check_and_seed_instances_from_settings, _refresh_next_release

logger = logging.getLogger(__name__)


def _delete_vf_episode_cache(db: Session, request_id: int) -> None:
    """Purge le cache VF par épisode d'une demande supprimée (évite les lignes orphelines).

    Doublon volontaire du helper de `app/routers/requests_api.py` : les deux modules
    n'ont pas de dépendance commune vers les modèles sans risquer un import circulaire.
    """
    db.query(VfEpisodeStatus).filter(
        VfEpisodeStatus.source_type == "request", VfEpisodeStatus.source_id == request_id
    ).delete()


# Empêche un déclenchement manuel (/api/requests/poll) de tourner en même temps qu'un
# cycle planifié (toutes les 15 min) sur les mêmes demandes.
_arr_status_lock = asyncio.Lock()


async def check_arr_statuses():
    """Vérifie si des demandes `sent_to_arr` sont désormais disponibles dans *arr.

    Stratégie de lookup (sans webhook) :
    1. Si arr_id connu → GET /api/v3/series/{id} ou /api/v3/movie/{id}
    2. Sinon → scan de la liste complète filtré par tvdb_id/tmdb_id/imdb_id
       (cas des demandes créées avant la configuration de Sonarr/Radarr)

    Disponibilité :
    - Sonarr : statistics.episodeFileCount > 0
    - Radarr : hasFile == true

    En mode hybride (Seer + Sonarr/Radarr), Seer peut ne pas savoir qu'un média
    est disponible si l'import a été fait sans qu'il le détecte. Si Seer répond
    "non disponible", on retente directement Sonarr/Radarr en fallback (lookup
    par tvdb_id/tmdb_id/imdb_id uniquement, car req.arr_id désigne alors l'ID
    Seer et non l'ID Sonarr/Radarr).
    """
    if _arr_status_lock.locked():
        logger.info("check_arr_statuses déjà en cours, cycle ignoré")
        return

    logger.info("Checking arr statuses...")
    _check_start = time.monotonic()
    started_at = now_utc_naive()
    items_processed = 0
    newly_available = 0
    deleted_count = 0
    errors_count = 0
    error_details: list[str] = []
    db = SessionLocal()
    await _arr_status_lock.acquire()
    try:
        settings = db.query(Settings).first()
        if not settings:
            return

        _check_and_seed_instances_from_settings(db, settings)

        candidates = (
            db.query(MediaRequest)
            .filter(
                or_(
                    MediaRequest.status == RequestStatus.sent_to_arr,
                    # Séries déjà "available" mais encore partiellement diffusées : on
                    # continue de rafraîchir leurs compteurs d'épisodes tant qu'elles
                    # n'ont pas atteint episodes_total_count (nouveaux épisodes chaque
                    # semaine), pour le badge et les notifs de progression.
                    and_(
                        MediaRequest.status == RequestStatus.available,
                        MediaRequest.media_type == "show",
                        MediaRequest.episodes_total_count.isnot(None),
                        MediaRequest.episodes_available_count < MediaRequest.episodes_total_count,
                    ),
                )
            )
            .all()
        )

        # Filter out requests handled by Prowlarr since Prowlarr does not track availability
        candidates = [c for c in candidates if not (c.arr_slug and c.arr_slug.startswith("prowlarr:"))]

        if not candidates:
            return

        logger.info(f"Checking {len(candidates)} sent_to_arr requests...")
        items_processed = len(candidates)

        # Load all enabled instances
        instances = db.query(ArrInstance).filter(ArrInstance.enabled).all()

        for inst in instances:
            if inst.arr_type not in ("sonarr", "radarr"):
                continue

            # Filter candidates for this instance
            inst_candidates = []
            for req in candidates:
                if req.arr_instance_id == inst.id:
                    inst_candidates.append(req)
                elif req.arr_instance_id is None:
                    # Legacy requests check on default instance of correct type
                    if req.media_type == "show" and inst.arr_type == "sonarr" and inst.is_default:
                        inst_candidates.append(req)
                    elif req.media_type == "movie" and inst.arr_type == "radarr" and inst.is_default:
                        inst_candidates.append(req)

            if not inst_candidates:
                continue

            logger.info(f"Checking {len(inst_candidates)} requests on instance '{inst.name}'...")

            # Prefetch list for the instance
            series_list = None
            movies_list = None
            queue_ids: set[int] = set()
            if inst.arr_type == "sonarr":
                try:
                    series_list = await get_all_series(inst.url, inst.api_key)
                except Exception as e:
                    logger.warning(f"Sonarr series prefetch failed for '{inst.name}': {e}")
                    errors_count += 1
                    error_details.append(f"[{inst.name}] prefetch Sonarr: {e}")
                queue_ids = await get_queue_series_ids(inst.url, inst.api_key)
            elif inst.arr_type == "radarr":
                try:
                    movies_list = await get_all_movies(inst.url, inst.api_key)
                except Exception as e:
                    logger.warning(f"Radarr movies prefetch failed for '{inst.name}': {e}")
                    errors_count += 1
                    error_details.append(f"[{inst.name}] prefetch Radarr: {e}")
                queue_ids = await get_queue_movie_ids(inst.url, inst.api_key)

            for req in inst_candidates:
                available = False
                new_arr_id = None
                new_slug = None
                seer_checked = False
                series_stats = None
                try:
                    if req.source == "seer" and settings.seer_url and settings.seer_api_key:
                        seer_checked = True
                        available, new_arr_id, new_slug = await seer_available(
                            settings.seer_url,
                            settings.seer_api_key,
                            seer_request_id=req.arr_id,
                        )
                    elif req.media_type == "show" and inst.arr_type == "sonarr":
                        series_stats = await get_series_episode_stats(
                            inst.url,
                            inst.api_key,
                            arr_id=req.arr_id,
                            tvdb_id=req.tvdb_id,
                            tmdb_id=req.tmdb_id,
                            imdb_id=req.imdb_id,
                            series_list=series_list,
                        )
                        if series_stats:
                            available = series_stats["episode_file_count"] > 0
                            new_arr_id = series_stats["arr_id"]
                            new_slug = series_stats["title_slug"]
                    elif req.media_type == "movie" and inst.arr_type == "radarr":
                        available, new_arr_id, new_slug = await is_movie_available(
                            inst.url,
                            inst.api_key,
                            arr_id=req.arr_id,
                            tmdb_id=req.tmdb_id,
                            imdb_id=req.imdb_id,
                            movies_list=movies_list,
                        )

                    # Fallback hybride : Seer dit "non dispo" → on retente Sonarr/Radarr
                    # directement (req.arr_id n'est pas réutilisable ici, c'est l'ID Seer).
                    if seer_checked and not available:
                        if req.media_type == "show" and inst.arr_type == "sonarr":
                            series_stats = await get_series_episode_stats(
                                inst.url,
                                inst.api_key,
                                tvdb_id=req.tvdb_id,
                                tmdb_id=req.tmdb_id,
                                imdb_id=req.imdb_id,
                                series_list=series_list,
                            )
                            if series_stats:
                                available = series_stats["episode_file_count"] > 0
                                new_arr_id = new_arr_id or series_stats["arr_id"]
                                new_slug = new_slug or series_stats["title_slug"]
                        elif req.media_type == "movie" and inst.arr_type == "radarr":
                            available, arr_new_id, arr_new_slug = await is_movie_available(
                                inst.url,
                                inst.api_key,
                                tmdb_id=req.tmdb_id,
                                imdb_id=req.imdb_id,
                                movies_list=movies_list,
                            )
                            new_arr_id = new_arr_id or arr_new_id
                            new_slug = new_slug or arr_new_slug
                except Exception as e:
                    logger.warning(f"Status check error for '{req.title}': {e}")
                    errors_count += 1
                    error_details.append(f"{req.title}: {e}")
                    continue

                # Détection "supprimé côté *arr" : id déjà connu, mais introuvable ce cycle
                # (ni par id ni par tmdb/tvdb/imdb). is_movie_available/get_series_episode_stats
                # avalent les erreurs réseau en "introuvable" en interne — ce None seul ne suffit
                # donc PAS à distinguer un 404 confirmé d'un *arr injoignable. On vérifie
                # explicitement via movie_exists/series_exists, qui eux ne catchent pas les
                # erreurs réseau : toute exception ici est traitée comme "on ne sait pas",
                # jamais comme une suppression.
                if not seer_checked and req.arr_id and new_arr_id is None:
                    try:
                        if req.media_type == "movie" and inst.arr_type == "radarr":
                            still_exists = await movie_exists(inst.url, inst.api_key, req.arr_id)
                        elif req.media_type == "show" and inst.arr_type == "sonarr":
                            still_exists = await series_exists(inst.url, inst.api_key, req.arr_id)
                        else:
                            still_exists = True
                    except Exception as e:
                        logger.warning(f"Impossible de confirmer la suppression *arr pour '{req.title}': {e}")
                        still_exists = True  # doute => on ne supprime jamais

                    if not still_exists:
                        logger.info(
                            f"'{req.title}' n'existe plus dans {inst.arr_type} (id={req.arr_id}) — suppression de la demande"
                        )
                        _delete_vf_episode_cache(db, req.id)
                        db.delete(req)
                        db.commit()
                        deleted_count += 1
                        continue

                # Mettre à jour arr_id / arr_slug / arr_instance_id si on les découvre maintenant
                if new_arr_id and not req.arr_id:
                    req.arr_id = new_arr_id
                if new_slug and not req.arr_slug:
                    req.arr_slug = new_slug
                if req.arr_instance_id is None:
                    req.arr_instance_id = inst.id

                if series_stats:
                    req.episodes_available_count = series_stats["episode_file_count"]
                    req.episodes_aired_count = series_stats["episode_count"]
                    req.episodes_total_count = series_stats["total_episode_count"]

                # Reflète la présence (ou non) d'un item actif dans la file de téléchargement
                # *arr pour ce média. Permet de distinguer, côté UI, une vraie anomalie Plex
                # (fichier importé mais introuvable dans Plex) d'un média encore en cours de
                # téléchargement/import (ex: série avec d'autres épisodes en cours de téléchargement).
                effective_arr_id = None if seer_checked else (new_arr_id or req.arr_id)
                req.is_downloading = bool(effective_arr_id and effective_arr_id in queue_ids)

                was_already_available = req.status == RequestStatus.available
                if available:
                    if not was_already_available:
                        req.status = RequestStatus.available
                        req.available_at = now_utc_naive()
                        req.next_release_at = None
                        req.next_release_label = None
                        newly_available += 1
                        logger.info(f"'{req.title}' is now available")
                        db.commit()
                        record_completed(
                            db,
                            title=req.title,
                            year=req.year,
                            media_type=req.media_type,
                            source=inst.arr_type,
                            instance_name=inst.name,
                            poster_url=req.poster_url,
                            request_id=req.id,
                        )
                    else:
                        db.commit()

                    if req.media_type == "show":
                        # Gère la disponibilité partielle (série en cours de diffusion) :
                        # décide de la notif à envoyer (partielle / complète) selon la
                        # progression et la fréquence choisie. Tourne à chaque cycle tant
                        # que la série n'est pas intégralement disponible.
                        _handle_show_progress_notification(settings, req, db)
                    elif not was_already_available and not settings.vff_enabled:
                        # Quand VFF est actif, on diffère la notification « available » :
                        # check_vf_statuses enverra soit « available » (VF présente) soit
                        # « vo_only » (VO seule) — une seule notification, pas de doublon.
                        notification_orchestrator._notify("available", settings, req, db)
                else:
                    await _refresh_next_release(
                        req, settings, series_list=series_list, movies_list=movies_list, inst=inst
                    )
                    db.commit()

        # Analyse VF immédiate des nouvelles disponibilités (évite le délai jusqu'au
        # prochain passage planifié pour l'envoi de la notification différée).
        # Lancée en tâche de fond (pas de await) : un scan VFF sur un gros catalogue
        # ne doit pas retarder la fin de ce job planifié.
        if settings.vff_enabled and newly_available > 0:
            from .vff_scanner import check_vf_statuses

            asyncio.create_task(check_vf_statuses())

        if deleted_count:
            logger.info(f"{deleted_count} demande(s) supprimée(s) (média absent de *arr)")

        logger.info("Arr status check complete")

    except Exception as e:
        logger.error(f"check_arr_statuses error: {e}")
        error_details.append(str(e))
        errors_count += 1
    finally:
        # Persist PollHistory (concatène toutes les erreurs du cycle, pas seulement la dernière)
        duration_ms = int((time.monotonic() - _check_start) * 1000)
        error_detail = "; ".join(error_details)[:2000] if error_details else None
        poll_db = SessionLocal()
        try:
            history = PollHistory(
                job="arr_status",
                started_at=started_at,
                duration_ms=duration_ms,
                items_processed=items_processed,
                new_requests=0,
                newly_available=newly_available,
                errors=errors_count,
                error_detail=error_detail,
            )
            poll_db.add(history)
            poll_db.commit()
        except Exception as pe:
            logger.error(f"Failed to persist arr_status PollHistory: {pe}")
        finally:
            if poll_db is not db:
                poll_db.close()
        db.close()
        _arr_status_lock.release()


async def check_torrent_statuses():
    """Tâche périodique de suivi et nettoyage des torrents actifs."""
    logger.info("Checking torrent statuses...")
    db = watchlist_poller.SessionLocal()
    try:
        settings = db.query(Settings).first()
        if not settings:
            return

        requests = (
            db.query(MediaRequest)
            .filter(
                MediaRequest.torrent_hash.isnot(None),
                MediaRequest.status != RequestStatus.available,
            )
            .all()
        )

        for req in requests:
            client = db.query(DownloadClient).filter(DownloadClient.id == req.download_client_id).first()
            if not client or not client.enabled:
                continue

            status = await get_torrent_status(
                client.client_type, client.url, client.username, client.password, req.torrent_hash
            )
            if not status:
                logger.warning(f"Impossible de récupérer le statut du torrent {req.torrent_hash} pour '{req.title}'")
                continue

            logger.debug(
                f"Torrent '{req.title}' status: {status['status']}, progress: {status['progress']:.1f}%, ratio: {status['ratio']:.2f}"
            )

            # Transition vers disponible
            if status["progress"] >= 100.0 or status["status"] in ("completed", "seeding"):
                if req.status != RequestStatus.available:
                    req.status = RequestStatus.available
                    req.available_at = now_utc_naive()
                    db.commit()
                    record_completed(
                        db,
                        title=req.title,
                        year=req.year,
                        media_type=req.media_type,
                        source="torrent",
                        instance_name=client.name,
                        poster_url=req.poster_url,
                        request_id=req.id,
                    )
                    notification_orchestrator._notify("available", settings, req, db)
                    logger.info(f"Torrent '{req.title}' terminé et marqué comme disponible !")

            # Nettoyage automatique
            if status["status"] in ("seeding", "completed") or (status["progress"] >= 100.0):
                ratio_reached = False
                time_reached = False

                if settings.torrent_ratio_limit is not None and status["ratio"] >= settings.torrent_ratio_limit:
                    ratio_reached = True

                if settings.torrent_seed_time_limit_hours is not None:
                    seed_time_hours = status["seeding_time"] / 3600
                    if seed_time_hours >= settings.torrent_seed_time_limit_hours:
                        time_reached = True

                if ratio_reached or time_reached:
                    delete_files = (
                        settings.torrent_auto_delete_files if settings.torrent_auto_delete_files is not None else True
                    )
                    deleted = await delete_torrent(
                        client.client_type, client.url, client.username, client.password, req.torrent_hash, delete_files
                    )
                    if deleted:
                        logger.info(f"Torrent '{req.title}' nettoyé (suppression des fichiers={delete_files})")
                        req.torrent_hash = None
                        db.commit()
                    else:
                        logger.error(f"Échec de suppression du torrent '{req.title}'")
    except Exception as e:
        logger.error(f"Erreur check_torrent_statuses : {e}")
    finally:
        db.close()
