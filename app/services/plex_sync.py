import asyncio
import logging
import re
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import ArrInstance, LibraryItem, MediaRequest, RequestStatus, Settings
from ..utils import now_utc, now_utc_naive
from . import vff
from .radarr import get_all_movies
from .sonarr import get_all_series
from .vff_scanner import _invalidate_vf_cache, _parse_vff_libraries

logger = logging.getLogger(__name__)

plex_sync_state: dict[str, Any] = {
    "status": "idle",  # "idle" | "running" | "failed"
    "started_at": None,
    "finished_at": None,
    "items_synced": 0,
    "total_items": 0,
    "error": None,
}


def _find_library_item_by_ids(
    db: Session,
    plex_guid: str | None,
    tmdb_id: str | None,
    tvdb_id: str | None,
    imdb_id: str | None,
    title: str,
    year: int | None,
    media_type: str,
) -> "LibraryItem | None":
    """Cherche un LibraryItem par identité : GUID Plex > IDs externes > titre+année+type.

    Cœur de rapprochement partagé par `_find_library_item` (sync Plex) et
    `_link_request_to_library_item` (lien MediaRequest -> LibraryItem).
    """
    if plex_guid:
        found = db.query(LibraryItem).filter(LibraryItem.plex_guid == plex_guid).first()
        if found:
            return found

    conditions = []
    if tmdb_id:
        conditions.append(LibraryItem.tmdb_id == tmdb_id)
    if tvdb_id:
        conditions.append(LibraryItem.tvdb_id == tvdb_id)
    if imdb_id:
        conditions.append(LibraryItem.imdb_id == imdb_id)
    if conditions:
        found = db.query(LibraryItem).filter(or_(*conditions)).first()
        if found:
            return found

    return (
        db.query(LibraryItem)
        .filter(
            LibraryItem.title.ilike(title),
            LibraryItem.year == year,
            LibraryItem.media_type == media_type,
        )
        .first()
    )


def _find_library_item(db: Session, item: dict) -> "LibraryItem | None":
    """Cherche un LibraryItem déjà en base correspondant à un média Plex synchronisé."""
    return _find_library_item_by_ids(
        db,
        item["plex_guid"],
        item["tmdb_id"],
        item["tvdb_id"],
        item["imdb_id"],
        item["title"],
        item["year"],
        item["media_type"],
    )


def _link_request_to_library_item(db: Session, req: MediaRequest) -> "LibraryItem | None":
    """Lie une demande à son LibraryItem correspondant (source de vérité VF unique).

    Si déjà liée, renvoie directement le LibraryItem (retente un rapprochement si le lien
    est devenu orphelin). Sinon, tente un rapprochement par identité et persiste le lien
    s'il est trouvé (sans commit — à la charge de l'appelant). Renvoie None si aucun
    LibraryItem ne correspond (le média n'est pas encore synchronisé depuis Plex : la
    demande reste scannée indépendamment jusqu'au prochain rapprochement).
    """
    if req.library_item_id:
        li = db.query(LibraryItem).filter(LibraryItem.id == req.library_item_id).first()
        if li:
            return li
        req.library_item_id = None  # lien orphelin, on retente un rapprochement ci-dessous
    li = _find_library_item_by_ids(
        db, req.plex_guid, req.tmdb_id, req.tvdb_id, req.imdb_id, req.title, req.year, req.media_type
    )
    if li:
        req.library_item_id = li.id
    return li


def _integrate_plex_items(plex_items: list[dict], arr_lookup: dict) -> int:
    """Intègre les médias Plex en base (insert/mise à jour).

    Exécuté dans un thread (via asyncio.to_thread) pour ne PAS bloquer la boucle
    asyncio pendant l'intégration de milliers d'éléments — sinon le serveur devient
    non réactif juste après le démarrage. Commits par lots (200) pour borner la
    durée de verrou SQLite. Session dédiée (jamais partagée entre threads).
    Retourne le nombre de nouveaux éléments ajoutés.
    """
    db = SessionLocal()
    now = now_utc_naive()
    added_count = 0
    try:
        for i, item in enumerate(plex_items, 1):
            lib_item = _find_library_item(db, item)

            arr_match = None
            if item["media_type"] == "movie":
                if item["tmdb_id"] and ("movie", "tmdb", item["tmdb_id"]) in arr_lookup:
                    arr_match = arr_lookup[("movie", "tmdb", item["tmdb_id"])]
                elif item["imdb_id"] and ("movie", "imdb", item["imdb_id"]) in arr_lookup:
                    arr_match = arr_lookup[("movie", "imdb", item["imdb_id"])]
            else:
                if item["tvdb_id"] and ("show", "tvdb", item["tvdb_id"]) in arr_lookup:
                    arr_match = arr_lookup[("show", "tvdb", item["tvdb_id"])]
                elif item["tmdb_id"] and ("show", "tmdb", item["tmdb_id"]) in arr_lookup:
                    arr_match = arr_lookup[("show", "tmdb", item["tmdb_id"])]
                elif item["imdb_id"] and ("show", "imdb", item["imdb_id"]) in arr_lookup:
                    arr_match = arr_lookup[("show", "imdb", item["imdb_id"])]

            arr_instance_id = arr_match[0] if arr_match else None
            arr_id = arr_match[1] if arr_match else None
            arr_slug = arr_match[2] if arr_match else None

            added_date = item["added_at"]
            if added_date and added_date.tzinfo:
                added_date = added_date.replace(tzinfo=None)

            if lib_item is None:
                db.add(
                    LibraryItem(
                        title=item["title"],
                        year=item["year"],
                        media_type=item["media_type"],
                        tmdb_id=item["tmdb_id"],
                        tvdb_id=item["tvdb_id"],
                        imdb_id=item["imdb_id"],
                        plex_guid=item["plex_guid"],
                        poster_url=item["poster_url"],
                        overview=item["overview"],
                        added_at=added_date,
                        arr_instance_id=arr_instance_id,
                        arr_id=arr_id,
                        arr_slug=arr_slug,
                        has_vf=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                added_count += 1
            else:
                if not lib_item.plex_guid and item["plex_guid"]:
                    lib_item.plex_guid = item["plex_guid"]
                if not lib_item.poster_url and item["poster_url"]:
                    lib_item.poster_url = item["poster_url"]
                if not lib_item.arr_instance_id and arr_match:
                    lib_item.arr_instance_id = arr_instance_id
                    lib_item.arr_id = arr_id
                    lib_item.arr_slug = arr_slug
                lib_item.updated_at = now

            plex_sync_state["items_synced"] += 1
            if i % 200 == 0:
                db.commit()
        db.commit()
    finally:
        db.close()
    return added_count


async def sync_plex_media():
    """Tâche planifiée : synchronise les médias Plex configurés avec la base de données.

    Vérifie l'existence de chaque média par GUID Plex ou identifiant externe.
    Enregistre les nouveaux médias en statut disponible avec la source "plex_sync".
    """
    if plex_sync_state["status"] == "running":
        logger.info("VFF Sync : une synchronisation est déjà en cours, skip")
        return

    plex_sync_state["status"] = "running"
    plex_sync_state["started_at"] = now_utc().isoformat()
    plex_sync_state["finished_at"] = None
    plex_sync_state["items_synced"] = 0
    plex_sync_state["total_items"] = 0
    plex_sync_state["error"] = None

    db = SessionLocal()
    try:
        settings = db.query(Settings).first()
        if not settings or not settings.vff_enabled:
            plex_sync_state["status"] = "idle"
            return
        if not settings.plex_url or not settings.plex_token:
            logger.info("VFF Sync : Plex non configuré, skip")
            plex_sync_state["status"] = "idle"
            return

        libs = _parse_vff_libraries(settings)
        if not libs:
            logger.info("VFF Sync : aucune bibliothèque configurée, skip")
            plex_sync_state["status"] = "idle"
            return

        logger.info("VFF Sync : début de la synchronisation de la bibliothèque Plex")
        plex_items = await asyncio.to_thread(
            vff.sync_plex_library_blocking, settings.plex_url, settings.plex_token, libs
        )

        plex_sync_state["total_items"] = len(plex_items)
        logger.info(f"VFF Sync : {len(plex_items)} média(s) récupéré(s) de Plex, intégration en base...")

        # Charger la table de correspondance Sonarr/Radarr
        instances = db.query(ArrInstance).filter(ArrInstance.enabled).all()
        arr_lookup = {}
        for inst in instances:
            try:
                if inst.arr_type == "radarr":
                    movies = await get_all_movies(inst.url, inst.api_key)
                    for m in movies:
                        tmdb = str(m.get("tmdbId") or "")
                        imdb = m.get("imdbId")
                        slug = m.get("titleSlug")
                        arr_id = m.get("id")
                        if tmdb:
                            arr_lookup[("movie", "tmdb", tmdb)] = (inst.id, arr_id, slug)
                        if imdb:
                            arr_lookup[("movie", "imdb", imdb)] = (inst.id, arr_id, slug)
                else:  # sonarr
                    series = await get_all_series(inst.url, inst.api_key)
                    for s in series:
                        tvdb = str(s.get("tvdbId") or "")
                        tmdb = str(s.get("tmdbId") or "")
                        imdb = s.get("imdbId")
                        slug = s.get("titleSlug")
                        arr_id = s.get("id")
                        if tvdb:
                            arr_lookup[("show", "tvdb", tvdb)] = (inst.id, arr_id, slug)
                        if tmdb:
                            arr_lookup[("show", "tmdb", tmdb)] = (inst.id, arr_id, slug)
                        if imdb:
                            arr_lookup[("show", "imdb", imdb)] = (inst.id, arr_id, slug)
            except Exception as inst_exc:
                logger.warning(f"VFF Sync : impossible de charger la bibliothèque de {inst.name} : {inst_exc}")

        # Intégration hors boucle asyncio (thread + commits par lots) pour garder
        # le serveur réactif pendant la synchro, notamment au démarrage.
        added_count = await asyncio.to_thread(_integrate_plex_items, plex_items, arr_lookup)

        if added_count > 0:
            logger.info(f"VFF Sync : {added_count} nouveau(x) média(s) Plex ajouté(s) à la bibliothèque")
            # Déclencher immédiatement une analyse VFF pour les nouveaux médias ajoutés
            from .vff_scanner import check_vf_statuses

            asyncio.create_task(check_vf_statuses())
        else:
            logger.info("VFF Sync : aucun nouveau média Plex détecté")

        plex_sync_state["status"] = "idle"
        plex_sync_state["finished_at"] = now_utc().isoformat()
    except Exception as e:
        logger.error(f"VFF Sync : erreur synchronisation : {e}")
        plex_sync_state["status"] = "failed"
        plex_sync_state["error"] = str(e)
    finally:
        db.close()
