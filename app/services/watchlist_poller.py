import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone

import sqlalchemy
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from .. import metrics as app_metrics
from ..database import AsyncSessionLocal
from ..models import ArrInstance, DownloadClient, MediaRequest, PlexUser, PollHistory, RequestStatus, Settings
from ..utils import now_utc, now_utc_naive
from . import notification_orchestrator, prowlarr
from .download_clients import add_torrent_to_client
from .notification_orchestrator import _add_co_requester
from .radarr import add_movie, lookup_movie, resolve_tmdb_id
from .seer import _headers as _seer_headers
from .seer import _resolve_tmdb_id as _seer_resolve_tmdb_id
from .seer import request_media as seer_request
from .sonarr import add_series, lookup_series
from .watchlist import fetch_watchlist

logger = logging.getLogger(__name__)

# Empêche un déclenchement manuel (/api/requests/poll) de tourner en même temps qu'un
# cycle planifié (ou qu'un autre déclenchement manuel) : sans ce verrou, deux passages
# concurrents sur la même watchlist peuvent soumettre deux fois la même demande.
_poll_lock = asyncio.Lock()


async def _check_and_seed_instances_from_settings(db: AsyncSession, settings: Settings):
    """Crée les instances Sonarr/Radarr par défaut depuis les anciens settings si besoin."""
    count = (await db.execute(select(sqlalchemy.func.count()).select_from(ArrInstance))).scalar() or 0
    if count == 0 and settings:
        if settings.sonarr_url and settings.sonarr_api_key:
            db.add(
                ArrInstance(
                    name="Sonarr Default",
                    arr_type="sonarr",
                    url=settings.sonarr_url,
                    api_key=settings.sonarr_api_key,
                    quality_profile_id=settings.sonarr_quality_profile_id,
                    root_folder=settings.sonarr_root_folder,
                    enabled=settings.sonarr_enabled if settings.sonarr_enabled is not None else True,
                    is_default=True,
                )
            )
        if settings.radarr_url and settings.radarr_api_key:
            db.add(
                ArrInstance(
                    name="Radarr Default",
                    arr_type="radarr",
                    url=settings.radarr_url,
                    api_key=settings.radarr_api_key,
                    quality_profile_id=settings.radarr_quality_profile_id,
                    root_folder=settings.radarr_root_folder,
                    enabled=settings.radarr_enabled if settings.radarr_enabled is not None else True,
                    is_default=True,
                    minimum_availability=settings.radarr_minimum_availability or "released",
                )
            )
        await db.commit()


async def sync_users_from_feed(items: list[dict], db: AsyncSession):
    """Crée automatiquement un PlexUser pour chaque plex_user_id inconnu trouvé dans le flux."""
    known_ids = {u.plex_user_id for u in (await db.execute(select(PlexUser))).scalars().all()}
    created = 0
    for item in items:
        uid = item.get("plex_user_id") or item.get("plex_user")
        if not uid or uid == "unknown" or uid in known_ids:
            continue
        display_name = item.get("plex_user") if item.get("plex_user") != uid else None
        db.add(PlexUser(plex_user_id=uid, display_name=display_name, enabled=True, source=item.get("source")))
        known_ids.add(uid)
        created += 1
        logger.info(f"Auto-discovered Plex user: {uid}")
    if created:
        await db.commit()


async def _submit_to_arr(
    settings: Settings, item: dict, user_obj: PlexUser | None = None, db: AsyncSession | None = None
) -> tuple[int | None, bool, str | None]:
    """Envoie un média à Seer (si activé) ou Sonarr/Radarr/Prowlarr directement.

    Si l'utilisateur est actif sur Seer (seer_active=True), la demande
    est ignorée par défaut (il la gère lui-même depuis Seer), 
    sauf si seer_suppress_notifications est désactivé.

    Returns:
        (arr_id, already_existed, arr_slug)
    """
    if user_obj and user_obj.seer_active is True:
        if settings.seer_suppress_notifications:
            logger.debug(f"Skip '{item['title']}' — utilisateur actif sur Seer")
            return None, True, None
        else:
            logger.debug(f"Process '{item['title']}' for Seer user (suppression disabled)")

    if settings.seer_send_requests and settings.seer_url and settings.seer_api_key:
        t0 = time.monotonic()
        result = await seer_request(settings.seer_url, settings.seer_api_key, item)
        app_metrics.record_seer_latency((time.monotonic() - t0) * 1000)
        seer_ok = result[0] is not None or result[1]
        app_metrics.record_arr_submission(seer_ok)
        if seer_ok or not settings.seer_fallback_arr:
            return result
        logger.warning("Seer request failed, falling back to Sonarr/Radarr")

    if db is None:
        async with AsyncSessionLocal() as owned_db:
            return await _submit_to_arr(settings, item, user_obj, db=owned_db)
    active_db = db
    if active_db is not None:
        # Resolve ArrInstance
        instance = None
        if user_obj:
            instance_id = user_obj.sonarr_instance_id if item["media_type"] == "show" else user_obj.radarr_instance_id
            if instance_id:
                instance = (await active_db.execute(
                    select(ArrInstance).filter(ArrInstance.id == instance_id, ArrInstance.enabled)
                )).scalars().first()

        if not instance:
            target_arr_type = "sonarr" if item["media_type"] == "show" else "radarr"
            instance = (await active_db.execute(
                select(ArrInstance).filter(ArrInstance.arr_type == target_arr_type, ArrInstance.enabled, ArrInstance.is_default)
            )).scalars().first()

        if not instance or instance.arr_type not in ("sonarr", "radarr"):
            info_hash, already_existed, arr_slug, client_id = await _submit_to_torrent(active_db, settings, item)
            if info_hash:
                item["_torrent_hash"] = info_hash
                item["_download_client_id"] = client_id
                return None, already_existed, arr_slug
            # Ni Sonarr/Radarr actif ni filet Prowlarr+torrent exploitable : lever une
            # exception (au lieu de retourner silencieusement) pour que l'appelant marque
            # la demande "failed" et notifie l'échec, plutôt que de la laisser bloquée en
            # "sent_to_arr" avec un mail "demande prise en compte" trompeur.
            raise Exception(
                "Aucune instance Sonarr/Radarr active et aucun résultat exploitable via le filet Prowlarr/torrent"
            )

        item["_arr_instance_id"] = instance.id

        if instance.arr_type == "prowlarr":
            info_hash, arr_slug, client_id = await _prowlarr_search_and_download(active_db, settings, instance, item)
            if info_hash:
                item["_torrent_hash"] = info_hash
                item["_download_client_id"] = client_id
                return None, False, arr_slug
            raise Exception(
                "Aucun résultat exploitable trouvé via Prowlarr (recherche vide, filtres, ou envoi au client échoué)"
            )

        if instance.arr_type == "sonarr":
            t0 = time.monotonic()
            result = await add_series(
                instance.url, instance.api_key, instance.quality_profile_id, instance.root_folder, item
            )
            app_metrics.record_sonarr_latency((time.monotonic() - t0) * 1000)
            app_metrics.record_arr_submission(result[0] is not None or result[1])
            return result

        if instance.arr_type == "radarr":
            t0 = time.monotonic()
            result = await add_movie(
                instance.url,
                instance.api_key,
                instance.quality_profile_id,
                instance.root_folder,
                item,
                minimum_availability=instance.minimum_availability or "released",
            )
            app_metrics.record_radarr_latency((time.monotonic() - t0) * 1000)
            app_metrics.record_arr_submission(result[0] is not None or result[1])
            return result

    return None, False, None


def _filter_torrent_results(results: list[dict], settings: Settings) -> list[dict]:
    """Filtre les résultats de recherche Prowlarr selon taille et mots-clés requis/interdits."""
    filtered_results = []
    for r in results:
        title = r.get("title", "")
        size = r.get("size", 0)
        size_gb = size / (1024 * 1024 * 1024)

        if settings.torrent_min_size_gb is not None and size_gb < settings.torrent_min_size_gb:
            continue
        if settings.torrent_max_size_gb is not None and size_gb > settings.torrent_max_size_gb:
            continue

        if settings.torrent_required_keywords:
            req_words = [w.strip().lower() for w in settings.torrent_required_keywords.split(",") if w.strip()]
            if req_words and not any(w in title.lower() for w in req_words):
                continue

        if settings.torrent_forbidden_keywords:
            forb_words = [w.strip().lower() for w in settings.torrent_forbidden_keywords.split(",") if w.strip()]
            if any(w in title.lower() for w in forb_words):
                continue

        filtered_results.append(r)
    return filtered_results


async def _prowlarr_search_and_download(
    db: AsyncSession, settings: Settings, prowlarr_inst: ArrInstance, item: dict
) -> tuple[str | None, str | None, int | None]:
    """Cherche un média sur une instance Prowlarr donnée et l'envoie au client torrent par défaut.

    Contrairement à un simple comptage de résultats, ceci garantit qu'une demande routée
    vers Prowlarr obtient un `torrent_hash` exploitable par `check_torrent_statuses` — sans
    quoi elle resterait indéfiniment en `sent_to_arr` (Prowlarr ne fournit pas d'API de
    disponibilité, contrairement à Sonarr/Radarr).

    Returns: (info_hash, arr_slug, download_client_id) — info_hash est None si rien n'a
    été trouvé, filtré, ou envoyé avec succès.
    """
    client = (await db.execute(
        select(DownloadClient).filter(DownloadClient.enabled, DownloadClient.is_default)
    )).scalars().first()
    if not client:
        client = (await db.execute(select(DownloadClient).filter(DownloadClient.enabled))).scalars().first()
    if not client:
        logger.warning("Prowlarr: Aucun client de téléchargement actif trouvé")
        return None, None, None

    query = item["title"]
    if item.get("year"):
        query = f"{query} {item['year']}"

    indexer_ids = None
    if prowlarr_inst.indexer_ids:
        try:
            indexer_ids = json.loads(prowlarr_inst.indexer_ids)
        except Exception:
            pass

    try:
        results = await prowlarr.search(
            url=prowlarr_inst.url,
            api_key=prowlarr_inst.api_key,
            query=query,
            media_type=item["media_type"],
            indexer_ids=indexer_ids,
        )
    except Exception as e:
        logger.error(f"Prowlarr: Erreur lors de la recherche pour '{query}': {e}")
        return None, None, None

    if not results:
        logger.info(f"Prowlarr: Aucun résultat de recherche pour '{query}'")
        return None, None, None

    filtered_results = _filter_torrent_results(results, settings)
    if not filtered_results:
        logger.info(f"Prowlarr: Tous les résultats pour '{query}' ont été filtrés")
        return None, None, None

    filtered_results.sort(key=lambda x: x.get("seeders", 0), reverse=True)
    best_release = filtered_results[0]
    download_url = best_release.get("downloadUrl") or best_release.get("magnetUrl")

    if not download_url:
        return None, None, None

    ok, msg, info_hash = await add_torrent_to_client(
        client_type=client.client_type,
        url=client.url,
        username=client.username,
        password=client.password,
        torrent_url_or_magnet=download_url,
        category=client.category,
        tags=client.tags,
    )

    if ok:
        logger.info(f"Prowlarr: Envoyé avec succès au client torrent: {best_release.get('title')} (hash: {info_hash})")
        return info_hash, "torrent", client.id
    logger.error(f"Prowlarr: Erreur lors de l'envoi du torrent: {msg}")
    return None, None, None


async def _submit_to_torrent(
    db: AsyncSession, settings: Settings, item: dict
) -> tuple[str | None, bool, str | None, int | None]:
    """Recherche un média sur Prowlarr et l'envoie au client torrent par défaut si Sonarr/Radarr sont inactifs."""
    prowlarr_inst = (await db.execute(
        select(ArrInstance).filter(ArrInstance.arr_type == "prowlarr", ArrInstance.enabled)
    )).scalars().first()
    if not prowlarr_inst:
        logger.warning("Torrent automation: Aucune instance Prowlarr active trouvée")
        return None, False, None, None

    info_hash, arr_slug, client_id = await _prowlarr_search_and_download(db, settings, prowlarr_inst, item)
    if not info_hash:
        return None, False, None, None
    return info_hash, False, arr_slug, client_id


async def _ensure_tmdb_id(item: dict, settings: Settings, user_obj) -> dict:
    """Garantit un tmdb_id sur l'item quand c'est possible (normalisation déduplication).

    - Films : résout IMDB → TMDB via Radarr (disponible pour TOUS les utilisateurs,
      pas seulement les hybrides Seer). Radarr utilise la table de correspondance
      externe de TMDB, donc le résultat coïncide avec ce que produit Seer.
    - Fallback Seer (utilisateurs hybrides) : couvre les rares cas sans IMDB ni TVDB.

    Renvoie l'item (éventuellement enrichi d'un tmdb_id) sans le muter sur place.
    """
    if item.get("tmdb_id"):
        return item

    if (
        item.get("media_type") == "movie"
        and item.get("imdb_id")
        and settings
        and settings.radarr_url
        and settings.radarr_api_key
    ):
        resolved = await resolve_tmdb_id(settings.radarr_url, settings.radarr_api_key, item["imdb_id"])
        if resolved:
            logger.info(f"tmdb_id résolu via Radarr pour '{item['title']}' (imdb {item['imdb_id']}): {resolved}")
            return {**item, "tmdb_id": resolved}

    if (
        not item.get("tvdb_id")
        and user_obj
        and user_obj.seer_user_id
        and user_obj.seer_active
        and settings
        and settings.seer_url
        and settings.seer_api_key
    ):
        base = settings.seer_url.rstrip("/")
        headers = _seer_headers(settings.seer_api_key)
        try:
            search_item = {**item, "title": _clean_title(item["title"])}
            resolved = await _seer_resolve_tmdb_id(base, headers, search_item)
            if resolved:
                logger.debug(f"tmdb_id résolu via Seer pour '{item['title']}': {resolved}")
                return {**item, "tmdb_id": resolved}
        except Exception:
            pass

    return item


async def _find_global_request(
    db: AsyncSession,
    media_type: str,
    tmdb_id: str | None,
    title: str | None,
    tvdb_id: str | None = None,
):
    """Cherche une demande existante globalement (tous utilisateurs).

    Ordre de priorité : tmdb_id → tvdb_id → titre.
    Le fallback tvdb_id permet de déduper RSS (tvdb) ↔ Seer (tmdb) pour les séries.
    Le fallback titre rattrape les anciennes entrées RSS créées sans identifiant.
    """
    if tmdb_id:
        found = (await db.execute(
            select(MediaRequest).filter(
                MediaRequest.media_type == media_type,
                MediaRequest.tmdb_id == tmdb_id,
            )
        )).scalars().first()
        if found:
            return found
    if tvdb_id:
        found = (await db.execute(
            select(MediaRequest).filter(
                MediaRequest.media_type == media_type,
                MediaRequest.tvdb_id == tvdb_id,
            )
        )).scalars().first()
        if found:
            return found
    if title:
        return (await db.execute(
            select(MediaRequest).filter(
                MediaRequest.media_type == media_type,
                MediaRequest.title == title,
            )
        )).scalars().first()
    return None


async def _refresh_next_release(
    req: MediaRequest,
    settings: Settings,
    series_list: list[dict] | None = None,
    movies_list: list[dict] | None = None,
    inst: ArrInstance | None = None,
) -> None:
    """Met à jour req.next_release_at/label à partir de Sonarr/Radarr (best-effort).

    Alimente le cache consommé par /api/upcoming, pour éviter d'appeler Sonarr/Radarr
    à chaque chargement du dashboard. `series_list`/`movies_list` (pré-chargées une
    fois par run de check_arr_statuses) évitent un GET complet par demande.
    """
    try:
        url = inst.url if inst else (settings.sonarr_url if req.media_type == "show" else settings.radarr_url)
        api_key = (
            inst.api_key if inst else (settings.sonarr_api_key if req.media_type == "show" else settings.radarr_api_key)
        )
        if not url or not api_key:
            return

        if req.media_type == "show":
            data = await lookup_series(
                url,
                api_key,
                arr_id=req.arr_id,
                tvdb_id=req.tvdb_id,
                tmdb_id=req.tmdb_id,
                imdb_id=req.imdb_id,
                series_list=series_list,
            )
            next_airing = data.get("nextAiring") if data else None
            req.next_release_at = (
                datetime.fromisoformat(next_airing.replace("Z", "+00:00")).replace(tzinfo=None) if next_airing else None
            )
            req.next_release_label = "Prochain épisode" if next_airing else None
        elif req.media_type == "movie":
            data = await lookup_movie(
                url,
                api_key,
                arr_id=req.arr_id,
                tmdb_id=req.tmdb_id,
                imdb_id=req.imdb_id,
                movies_list=movies_list,
            )
            if not data:
                return
            now = now_utc()
            candidates = [
                (data.get("digitalRelease"), "Sortie numérique"),
                (data.get("physicalRelease"), "Sortie physique"),
                (data.get("inCinemas"), "Sortie cinéma"),
            ]
            future = [(datetime.fromisoformat(d.replace("Z", "+00:00")), label) for d, label in candidates if d]
            future = [(d, label) for d, label in future if d > now]
            if future:
                date, label = min(future, key=lambda x: x[0])
                req.next_release_at, req.next_release_label = date.replace(tzinfo=None), label
            else:
                req.next_release_at, req.next_release_label = None, None
    except Exception as e:
        logger.debug(f"next_release lookup failed for '{req.title}': {e}")


async def _process_watchlist_item(
    item: dict,
    settings: Settings,
    db: AsyncSession,
    users_map: dict,
    enabled_ids: set,
    has_filter: bool,
) -> str:
    """Traite un item de watchlist : dédup, soumission à *arr, notification.

    Isolé dans sa propre fonction pour que `poll_watchlists` puisse catcher toute
    exception par item sans interrompre le traitement des autres items du cycle.

    Returns: "skip" (ignoré), "sent" (transmis à *arr) ou "failed" (échec de transmission).
    """
    uid = item.get("plex_user_id") or item.get("plex_user", "unknown")

    # Ignorer les utilisateurs désactivés si la table utilisateurs est renseignée
    if has_filter and uid not in enabled_ids:
        return "skip"

    user_obj = users_map.get(uid)
    display_name = ((user_obj.custom_name or user_obj.display_name) if user_obj else None) or uid

    # Normalisation sur TMDB avant déduplication : le flux RSS n'apporte qu'un
    # IMDB ID (films) ou un TVDB ID (séries). Sans TMDB, la dédup retombe sur le
    # titre — qui diffère selon la langue → doublons RSS ↔ Seer. On résout donc
    # le TMDB ID pour tous les utilisateurs (pas seulement les hybrides).
    item = await _ensure_tmdb_id(item, settings, user_obj)

    # Dédup global : même média déjà demandé par un autre utilisateur ?
    global_req = await _find_global_request(db, item["media_type"], item.get("tmdb_id"), item["title"], item.get("tvdb_id"))
    if global_req and global_req.plex_user_id != uid:
        added = _add_co_requester(global_req, uid, display_name)
        if added:
            await db.commit()
            logger.info(f"Co-demandeur ajouté : {display_name} → '{global_req.title}'")
        return "skip"

    existing = global_req if global_req else None

    # Fallback : même utilisateur, même titre — ancienne demande sans identifiant
    if not existing and item.get("title"):
        existing = (await db.execute(
            select(MediaRequest).filter(
                MediaRequest.plex_user_id == uid,
                MediaRequest.media_type == item["media_type"],
                MediaRequest.title == item["title"],
                MediaRequest.tmdb_id.is_(None),
            )
        )).scalars().first()
        if existing:
            if item.get("tmdb_id"):
                existing.tmdb_id = item["tmdb_id"]
            if item.get("tvdb_id") and not existing.tvdb_id:
                existing.tvdb_id = item["tvdb_id"]

    if existing:
        # Ne retenter que les statuts récupérables
        if existing.status in (RequestStatus.pending, RequestStatus.failed):
            req = existing
        else:
            return "skip"
    else:
        req = MediaRequest(
            plex_user_id=uid,
            plex_user=display_name,
            title=item["title"],
            year=item.get("year"),
            media_type=item["media_type"],
            tmdb_id=item.get("tmdb_id"),
            tvdb_id=item.get("tvdb_id"),
            imdb_id=item.get("imdb_id"),
            plex_guid=item.get("plex_guid"),
            poster_url=item.get("poster_url"),
            overview=item.get("overview", ""),
            source=item.get("source"),
            status=RequestStatus.pending,
        )
        if item.get("requested_at"):
            req.requested_at = item["requested_at"]
        db.add(req)
        await db.flush()

    needs_approval = bool(
        settings.require_approval and not (user_obj and ((user_obj.role or "user") == "admin" or user_obj.auto_approve))
    )
    if needs_approval:
        req.status = RequestStatus.pending_approval
        await db.commit()
        logger.info("Demande en attente de validation : %s -> '%s'", display_name, item["title"])
        return "sent"

    # Routage intelligent : si l'utilisateur est Hybride (RSS + Seer actif),
    # vérifier si Seer a déjà traité cette demande.
    # Si oui → skip la soumission arr (Seer l'a déjà faite).
    # Si non → RSS sert de fallback et soumet lui-même.
    if user_obj and user_obj.seer_user_id and user_obj.seer_active:
        tmdb_id = item.get("tmdb_id")
        seer_id_filter = (MediaRequest.tmdb_id == tmdb_id) if tmdb_id else (MediaRequest.title == item["title"])
        seer_handled = (await db.execute(
            select(MediaRequest).filter(
                MediaRequest.plex_user_id == uid,
                MediaRequest.source == "seer",
                seer_id_filter,
            )
        )).scalars().first()
        if seer_handled:
            logger.debug(f"Routage Hybride : '{item['title']}' déjà géré par Seer pour {uid}, RSS skip")
            await db.commit()
            return "skip"

    already_existed = False
    result = "sent"
    try:
        arr_id, already_existed, arr_slug = await _submit_to_arr(settings, item, user_obj, db=db)
        req.status = RequestStatus.sent_to_arr
        req.arr_id = arr_id
        req.arr_slug = arr_slug
        req.arr_instance_id = item.get("_arr_instance_id")
        if item.get("_torrent_hash"):
            req.torrent_hash = item.get("_torrent_hash")
            req.download_client_id = item.get("_download_client_id")
    except Exception as e:
        logger.error(f"Failed to send '{item['title']}' to arr: {e}")
        req.status = RequestStatus.failed
        result = "failed"

    await db.commit()

    if already_existed:
        # Média déjà dans *arr : pas de notification (évite le spam au redémarrage)
        logger.info(f"'{item['title']}' already in arr — skipping notifications")
    elif req.status == RequestStatus.sent_to_arr:
        await notification_orchestrator._notify("request", settings, req, db)
    elif req.status == RequestStatus.failed:
        arr_name = "Sonarr" if req.media_type == "show" else "Radarr"
        await notification_orchestrator._notify(
            "failed", settings, req, db, f"Impossible de transmettre a {arr_name}. Verifiez la configuration."
        )

    return result


async def poll_watchlists():
    """Lit les watchlists Plex et synchronise les demandes vers Sonarr/Radarr.

    Logique :
    1. Récupère les éléments depuis l'API Plex ou le flux RSS (selon config).
    2. Auto-crée les utilisateurs inconnus.
    3. Pour chaque item d'un utilisateur actif :
       - Si demande inexistante : création + envoi à *arr.
       - Si demande en `pending` ou `failed` : tentative de renvoi.
       - Si déjà `sent_to_arr` ou `available` : ignoré.
    4. Notifie selon le résultat (succès, échec, déjà existant).

    Un verrou (`_poll_lock`) empêche un déclenchement manuel de tourner en même temps
    qu'un cycle planifié : sans lui, deux passages concurrents pourraient soumettre
    deux fois la même demande à *arr.
    """
    if _poll_lock.locked():
        logger.info("poll_watchlists déjà en cours, cycle ignoré")
        return

    logger.info("Polling watchlists...")
    _poll_start = time.monotonic()
    started_at = now_utc_naive()
    items_processed = 0
    new_requests = 0
    errors_count = 0
    error_details: list[str] = []
    db: AsyncSession = AsyncSessionLocal()
    _poll_error = False
    await _poll_lock.acquire()
    try:
        settings = (await db.execute(select(Settings))).scalars().first()
        if not settings:
            return

        await _check_and_seed_instances_from_settings(db, settings)

        items = await fetch_watchlist(settings)
        if not items:
            logger.info("No watchlist items returned")
            return

        items_processed = len(items)
        await sync_users_from_feed(items, db)

        all_users = (await db.execute(select(PlexUser))).scalars().all()
        users_map = {u.plex_user_id: u for u in all_users}
        enabled_ids = {u.plex_user_id for u in all_users if u.enabled}
        has_filter = len(all_users) > 0

        new_count = 0
        for item in items:
            # Chaque item est traité isolément : une exception inattendue (réseau, parsing,
            # etc.) ne doit pas interrompre le traitement des items restants du cycle.
            try:
                result = await _process_watchlist_item(item, settings, db, users_map, enabled_ids, has_filter)
            except Exception as e:
                title = item.get("title", "?")
                logger.error(f"Erreur inattendue en traitant '{title}': {e}")
                errors_count += 1
                error_details.append(f"{title}: {e}")
                continue

            if result in ("sent", "failed"):
                new_count += 1
                if result == "failed":
                    errors_count += 1
                    error_details.append(f"{item.get('title', '?')}: échec de transmission à *arr")

        new_requests = new_count
        logger.info(f"Poll complete: {new_count} requests processed")

    except Exception as e:
        logger.error(f"Poll error: {e}")
        _poll_error = True
        error_details.append(str(e))
        errors_count += 1
    finally:
        app_metrics.record_poll((time.monotonic() - _poll_start) * 1000, error=_poll_error)
        # Persist PollHistory (concatène toutes les erreurs du cycle, pas seulement la dernière)
        duration_ms = int((time.monotonic() - _poll_start) * 1000)
        error_detail = "; ".join(error_details)[:2000] if error_details else None
        poll_db: AsyncSession = AsyncSessionLocal()
        try:
            history = PollHistory(
                job="watchlist",
                started_at=started_at,
                duration_ms=duration_ms,
                items_processed=items_processed,
                new_requests=new_requests,
                newly_available=0,
                errors=errors_count,
                error_detail=error_detail,
            )
            poll_db.add(history)
            await poll_db.commit()
        except Exception as pe:
            logger.error(f"Failed to persist watchlist PollHistory: {pe}")
        finally:
            if poll_db is not db:
                await poll_db.close()
        await db.close()
        _poll_lock.release()


def _clean_title(title: str) -> str:
    """Supprime les suffixes d'année entre parenthèses ajoutés par Plex ex: 'INVINCIBLE (2021)' → 'INVINCIBLE'."""
    return re.sub(r"\s*\(\d{4}\)\s*$", "", title).strip()


async def sync_plex_dates(db: AsyncSession):
    """Met à jour les dates des MediaRequest existants depuis l'API Plex/RSS (requested_at)."""
    from .watchlist import fetch_watchlist
    
    settings = (await db.execute(select(Settings))).scalars().first()
    if not settings:
        return

    try:
        items = await fetch_watchlist(settings)
    except Exception as e:
        logger.error(f"sync_plex_dates: erreur lors de fetch_watchlist: {e}")
        return

    count = 0
    for item in items:
        req_date = item.get("requested_at")
        if not req_date:
            continue

        existing = await _find_global_request(
            db, item["media_type"], item.get("tmdb_id"), item["title"], item.get("tvdb_id")
        )
        if existing and existing.requested_at != req_date:
            existing.requested_at = req_date
            count += 1

    if count > 0:
        await db.commit()
        logger.info(f"sync_plex_dates: {count} dates mises à jour depuis Plex Watchlist")
    else:
        logger.info("sync_plex_dates: aucune date à mettre à jour")
