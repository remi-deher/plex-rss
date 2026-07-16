import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import sqlalchemy
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from .. import metrics as app_metrics
from ..database import AsyncSessionLocal
from ..models import ArrInstance, DownloadClient, MediaRequest, PlexUser, PollHistory, RequestStatus, Settings
from ..utils import now_utc, now_utc_naive
from . import notification_orchestrator, prowlarr
from .distributed_lock import acquire_distributed_lock, release_distributed_lock
from .download_clients import add_torrent_to_client
from .notification_orchestrator import _add_co_requester
from .radarr import add_movie, lookup_movie, resolve_tmdb_id
from .seer import _headers as _seer_headers
from .seer import _resolve_tmdb_id as _seer_resolve_tmdb_id
from .seer import request_media as seer_request
from .seer import resolve_mode as seer_resolve_mode
from .sonarr import add_series, lookup_series
from .watchlist import fetch_watchlist

logger = logging.getLogger(__name__)

# Empêche un déclenchement manuel (/api/requests/poll) de tourner en même temps qu'un
# cycle planifié (ou qu'un autre déclenchement manuel) DANS LE MÊME PROCESS : sans ce
# verrou, deux passages concurrents sur la même watchlist peuvent soumettre deux fois
# la même demande. Insuffisant à lui seul en déploiement multi-conteneurs (API +
# worker ARQ séparés) — voir _acquire_distributed_poll_lock ci-dessous.
_poll_lock = asyncio.Lock()

_DISTRIBUTED_POLL_LOCK_KEY = "plexarr:lock:poll_watchlists"
_DISTRIBUTED_POLL_LOCK_TTL = 300  # secondes ; filet de sécurité si le holder crash sans relâcher


async def _acquire_distributed_poll_lock() -> str | None:
    """Verrou Redis (SET NX EX), en plus de `_poll_lock`.

    `_poll_lock` est un `asyncio.Lock` local à un process Python : il ne protège pas
    contre deux déclenchements concurrents dans DEUX process différents — typiquement
    le cron ARQ (conteneur `worker`, toutes les 30s) et un déclenchement manuel HTTP
    (/api/requests/poll, retry, bulk retry...) qui appelle `poll_watchlists()`
    directement depuis le conteneur `plex-rss` (API), sans passer par ARQ. Sans verrou
    partagé, les deux process peuvent chacun croire l'item absent au même instant et
    créer un doublon — incident observé : deux `MediaRequest` identiques créées à
    369 ms d'écart, donnant deux mails de disponibilité pour le même film.

    Returns:
        Un token si le verrou est acquis (à repasser à `_release_distributed_poll_lock`),
        None si un autre process le détient déjà.
    """
    return await acquire_distributed_lock(_DISTRIBUTED_POLL_LOCK_KEY, _DISTRIBUTED_POLL_LOCK_TTL)


async def _release_distributed_poll_lock(token: str | None) -> None:
    await release_distributed_lock(_DISTRIBUTED_POLL_LOCK_KEY, token)


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
    """Envoie un média à Seer (mode acteur uniquement) ou Sonarr/Radarr/Prowlarr directement.

    Rôle de Seer (voir seer.resolve_mode) :
    - None / "observer" : Seer n'est jamais sollicité pour traiter la demande — le
      pipeline local (*arr / Prowlarr) soumet toujours lui-même.
    - "actor" : Seer est la cible prioritaire ; les demandes des utilisateurs actifs
      sur Seer sont ignorées (il les gère lui-même), sauf si
      seer_suppress_notifications est désactivé.

    Returns:
        (arr_id, already_existed, arr_slug)

    Pose `item["_attempted_target"]` ("seer"/"sonarr"/"radarr"/"prowlarr"/"torrent")
    avant chaque tentative, pour que l'appelant puisse rapporter la vraie cible en
    cas d'échec plutôt qu'un message générique "Sonarr/Radarr" trompeur.
    """
    seer_mode = seer_resolve_mode(settings)

    if seer_mode == "actor":
        if user_obj and user_obj.seer_active is True:
            if getattr(settings, "seer_suppress_notifications", True):
                logger.debug(f"Skip '{item['title']}' — utilisateur actif sur Seer")
                return None, True, None
            else:
                logger.debug(f"Process '{item['title']}' for Seer user (suppression disabled)")

        # L'appel Seer est isolé dans son propre try/except : request_media lève une
        # exception sur toute erreur (HTTP, réseau, TMDB introuvable). Sans ce catch,
        # l'exception court-circuitait le fallback *arr même avec seer_fallback_arr=True.
        item["_attempted_target"] = "seer"
        t0 = time.monotonic()
        result = None
        seer_error: Exception | None = None
        try:
            result = await seer_request(settings.seer_url, settings.seer_api_key, item)
        except Exception as e:
            seer_error = e
        app_metrics.record_seer_latency((time.monotonic() - t0) * 1000)
        seer_ok = result is not None and (result[0] is not None or result[1])
        app_metrics.record_arr_submission(seer_ok)
        if seer_ok:
            return result
        if not settings.seer_fallback_arr:
            if seer_error is not None:
                raise seer_error
            raise Exception("Envoi à Seer échoué et fallback Sonarr/Radarr désactivé")
        logger.warning(f"Seer request failed ({seer_error}), falling back to Sonarr/Radarr")

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
            item["_attempted_target"] = "torrent"
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
            item["_attempted_target"] = "prowlarr"
            info_hash, arr_slug, client_id = await _prowlarr_search_and_download(active_db, settings, instance, item)
            if info_hash:
                item["_torrent_hash"] = info_hash
                item["_download_client_id"] = client_id
                return None, False, arr_slug
            raise Exception(
                "Aucun résultat exploitable trouvé via Prowlarr (recherche vide, filtres, ou envoi au client échoué)"
            )

        if instance.arr_type == "sonarr":
            item["_attempted_target"] = "sonarr"
            t0 = time.monotonic()
            result = await add_series(
                instance.url, instance.api_key, instance.quality_profile_id, instance.root_folder, item
            )
            app_metrics.record_sonarr_latency((time.monotonic() - t0) * 1000)
            app_metrics.record_arr_submission(result[0] is not None or result[1])
            return result

        if instance.arr_type == "radarr":
            item["_attempted_target"] = "radarr"
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


async def _ensure_tmdb_id(item: dict, settings: Settings, user_obj, db: AsyncSession | None = None) -> dict:
    """Garantit un tmdb_id sur l'item quand c'est possible (normalisation déduplication).

    - Films : résout IMDB → TMDB via Radarr (disponible pour TOUS les utilisateurs,
      pas seulement les hybrides Seer). Radarr utilise la table de correspondance
      externe de TMDB, donc le résultat coïncide avec ce que produit Seer.
      Utilise d'abord les champs legacy `settings.radarr_*` (installs historiques),
      puis à défaut l'instance Radarr par défaut (`ArrInstance`) — sans ce repli, une
      install configurée uniquement via les instances sautait silencieusement cette
      normalisation, et la dédup RSS↔Seer retombait sur le titre (dépendant de la langue).
    - Fallback Seer (utilisateurs hybrides) : couvre les rares cas sans IMDB ni TVDB.

    Renvoie l'item (éventuellement enrichi d'un tmdb_id) sans le muter sur place.
    """
    if item.get("tmdb_id"):
        return item

    if item.get("media_type") == "movie" and item.get("imdb_id") and settings:
        radarr_url, radarr_api_key = settings.radarr_url, settings.radarr_api_key
        if not (radarr_url and radarr_api_key) and db is not None:
            inst = (await db.execute(
                select(ArrInstance).filter(ArrInstance.arr_type == "radarr", ArrInstance.enabled, ArrInstance.is_default)
            )).scalars().first()
            if inst:
                radarr_url, radarr_api_key = inst.url, inst.api_key
        if radarr_url and radarr_api_key:
            resolved = await resolve_tmdb_id(radarr_url, radarr_api_key, item["imdb_id"])
            if resolved:
                logger.info(f"tmdb_id résolu via Radarr pour '{item['title']}' (imdb {item['imdb_id']}): {resolved}")
                return {**item, "tmdb_id": resolved}

    if (
        not item.get("tvdb_id")
        and user_obj
        and user_obj.seer_user_id
        and user_obj.seer_active
        and seer_resolve_mode(settings) is not None
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


def _norm_title_for_dedup(value: str | None) -> str:
    """Normalise un titre pour la dédup par repli (aucun identifiant exploitable).

    Une comparaison `==` stricte rate les variantes de ponctuation entre sources —
    incident observé : Seer renvoie "Spider-Man : Across the Spider-Verse" (espace
    avant le ':', typographie FR) alors que le flux RSS Plex renvoie "Spider-Man:
    Across the Spider-Verse" (sans espace) pour le même film, créant un doublon
    quand la résolution tmdb_id échoue (ex: Radarr temporairement injoignable).
    Même normalisation que sonarr.py/radarr.py : casefold + tout non-alphanumérique
    réduit à un espace.
    """
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


async def _find_global_request(
    db: AsyncSession,
    media_type: str,
    tmdb_id: str | None,
    title: str | None,
    tvdb_id: str | None = None,
    imdb_id: str | None = None,
):
    """Cherche une demande existante globalement (tous utilisateurs).

    Ordre de priorité : tmdb_id → tvdb_id → imdb_id → titre (normalisé).
    Le fallback tvdb_id permet de déduper RSS (tvdb) ↔ Seer (tmdb) pour les séries.
    Le fallback titre rattrape les anciennes entrées RSS créées sans identifiant —
    comparaison normalisée (voir _norm_title_for_dedup) plutôt qu'une égalité stricte,
    fragile aux variantes de ponctuation entre sources.
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
    if imdb_id:
        found = (await db.execute(
            select(MediaRequest).filter(
                MediaRequest.media_type == media_type,
                MediaRequest.imdb_id == imdb_id,
            )
        )).scalars().first()
        if found:
            return found
    if title:
        norm = _norm_title_for_dedup(title)
        if norm:
            candidates = (await db.execute(
                select(MediaRequest).filter(MediaRequest.media_type == media_type)
            )).scalars().all()
            for candidate in candidates:
                if _norm_title_for_dedup(candidate.title) == norm:
                    return candidate
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
    item = await _ensure_tmdb_id(item, settings, user_obj, db)

    # Dédup global : même média déjà demandé par un autre utilisateur ?
    global_req = await _find_global_request(
        db, item["media_type"], item.get("tmdb_id"), item["title"], item.get("tvdb_id"), item.get("imdb_id")
    )
    if global_req and global_req.plex_user_id != uid:
        added = _add_co_requester(global_req, uid, display_name)
        if added:
            await db.commit()
            logger.info(f"Co-demandeur ajouté : {display_name} → '{global_req.title}'")
        return "skip"

    # `_find_global_request` matche déjà tous utilisateurs confondus (y compris le
    # demandeur courant) via tmdb_id/tvdb_id/imdb_id puis titre normalisé, donc
    # `global_req` couvre aussi le cas "même utilisateur, ancienne demande sans
    # identifiant" — pas besoin d'un second lookup dédié. On complète juste les
    # identifiants manquants sur l'entrée retrouvée.
    existing = global_req if global_req else None
    if existing:
        if item.get("tmdb_id") and not existing.tmdb_id:
            existing.tmdb_id = item["tmdb_id"]
        if item.get("tvdb_id") and not existing.tvdb_id:
            existing.tvdb_id = item["tvdb_id"]
        if item.get("imdb_id") and not existing.imdb_id:
            existing.imdb_id = item["imdb_id"]

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
            # Watchlist-ajout deja vieux de plus de 24h a la detection (RSS resurfacing) :
            # decide une bonne fois pour toutes, jamais reevalue plus tard (voir modele).
            if now_utc_naive() - item["requested_at"] > timedelta(hours=24):
                req.notify_suppressed = True
                logger.info(
                    "'%s' : ajout watchlist du %s (> 24h), notifications automatiques desactivees",
                    item["title"],
                    item["requested_at"],
                )
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

    # Routage intelligent (mode acteur uniquement) : si l'utilisateur est Hybride
    # (RSS + Seer actif), vérifier si Seer a déjà traité cette demande.
    # Si oui → skip la soumission arr (Seer l'a déjà faite).
    # Si non → RSS sert de fallback et soumet lui-même.
    # En mode observateur, on ne skip jamais : le pipeline local soumet toujours
    # lui-même (la dédup *arr rattrape le cas où Seer a déjà ajouté le média).
    if seer_resolve_mode(settings) == "actor" and user_obj and user_obj.seer_user_id and user_obj.seer_active:
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

    was_failed = existing and existing.status == RequestStatus.failed

    already_existed = False
    result = "sent"
    try:
        arr_id, already_existed, arr_slug = await _submit_to_arr(settings, item, user_obj, db=db)
        
        # Si aucun ID Radarr/Sonarr n'est retourné, et que ce n'est pas un film pré-existant,
        # et que le fallback torrent n'a pas non plus retourné de hash, c'est un échec.
        if arr_id is None and not already_existed and not item.get("_torrent_hash"):
            raise Exception("Transmission échouée : métadonnées introuvables (TMDB/TVDB) ou instance inaccessible.")
            
        req.status = RequestStatus.sent_to_arr
        req.arr_id = arr_id
        req.arr_slug = arr_slug
        req.arr_instance_id = item.get("_arr_instance_id")
        # Resoumission réussie après un échec précédent : autorise une nouvelle
        # notification d'échec si une future resoumission échoue à son tour.
        req.failure_mail_sent = False
        if item.get("_torrent_hash"):
            req.torrent_hash = item.get("_torrent_hash")
            req.download_client_id = item.get("_download_client_id")
    except Exception as e:
        body_log = ""
        if hasattr(e, "response") and hasattr(e.response, "text"):
            body_log = f" | Body: {e.response.text}"
        logger.error(f"Failed to send '{item['title']}' to arr: {e}{body_log}")
        req.status = RequestStatus.failed
        result = "failed"

    await db.commit()

    if req.status == RequestStatus.sent_to_arr:
        # `already_existed` signifie seulement que le tmdb_id était déjà catalogué côté
        # Radarr/Sonarr (ajouté par un autre biais, ou lors d'un cycle de poll précédent) —
        # ça ne veut pas dire que CETTE demande a déjà été notifiée. La garde anti-spam
        # correcte est `req.request_mail_sent` (vérifiée par `_notify` lui-même) : se fier
        # à `already_existed` ici a fait sauter le mail de confirmation pour toute demande
        # dont le média était déjà présent dans Radarr (ex: film déjà ajouté avant que ce
        # suivi n'existe), même pour un utilisateur jamais notifié.
        if already_existed:
            logger.info(f"'{item['title']}' already in arr — no new arr add, but notifying requester")
        await notification_orchestrator._notify("request", settings, req, db)
    elif req.status == RequestStatus.failed and not was_failed:
        target_labels = {
            "seer": "Seer",
            "sonarr": "Sonarr",
            "radarr": "Radarr",
            "prowlarr": "Prowlarr",
            "torrent": "Prowlarr/client torrent",
        }
        default_target = "Sonarr" if item["media_type"] == "show" else "Radarr"
        target_name = target_labels.get(item.get("_attempted_target"), default_target)
        await notification_orchestrator._notify(
            "failed", settings, req, db, f"Impossible de transmettre a {target_name}. Verifiez la configuration."
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

    Deux verrous empêchent un déclenchement manuel de tourner en même temps qu'un
    cycle planifié (sans quoi deux passages concurrents peuvent soumettre deux fois
    la même demande à *arr, et envoyer deux notifications) : `_poll_lock` protège
    contre la concurrence dans le même process, `_acquire_distributed_poll_lock`
    contre la concurrence entre le conteneur API et le conteneur worker ARQ.
    """
    if _poll_lock.locked():
        logger.info("poll_watchlists déjà en cours (verrou local), cycle ignoré")
        return

    await _poll_lock.acquire()
    dist_lock_token = await _acquire_distributed_poll_lock()
    if dist_lock_token is None:
        logger.info("poll_watchlists déjà en cours ailleurs (verrou Redis), cycle ignoré")
        _poll_lock.release()
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
        await _release_distributed_poll_lock(dist_lock_token)
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
            db, item["media_type"], item.get("tmdb_id"), item["title"], item.get("tvdb_id"), item.get("imdb_id")
        )
        if existing and existing.requested_at != req_date:
            existing.requested_at = req_date
            count += 1

    if count > 0:
        await db.commit()
        logger.info(f"sync_plex_dates: {count} dates mises à jour depuis Plex Watchlist")
    else:
        logger.info("sync_plex_dates: aucune date à mettre à jour")
