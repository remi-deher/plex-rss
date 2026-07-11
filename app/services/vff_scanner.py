import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import ColumnElement, true
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import ArrInstance, LibraryItem, MediaRequest, PlexUser, RequestStatus, Settings, VfEpisodeStatus
from ..utils import now_utc, now_utc_naive
from . import radarr, sonarr, vff
from .notification_orchestrator import (
    _notify,
    _queue_milestone,
    _queue_show_milestones,
    _resolve_movie_notify_language,
    _resolve_series_notify_language,
)
from .radarr import search_movie
from .sonarr import get_season_aired_episode_counts, search_series

logger = logging.getLogger(__name__)

vff_scan_state: dict[str, Any] = {
    "status": "idle",  # "idle" | "running" | "failed"
    "started_at": None,
    "finished_at": None,
    "items_scanned": 0,
    "total_items": 0,
    "error": None,
}

episode_scan_state: dict[str, Any] = {
    "status": "idle",  # "idle" | "running" | "failed"
    "started_at": None,
    "finished_at": None,
    "items_scanned": 0,
    "total_items": 0,
    "error": None,
}


def _link_request_to_library_item(db: Session, req: MediaRequest) -> "LibraryItem | None":
    from .plex_sync import _link_request_to_library_item as _link

    return _link(db, req)


def _parse_vff_libraries(settings: Settings) -> list[dict]:
    """Parse la config JSON des bibliothèques VFF. Retourne [] si absente/invalide.

    Format : [{"name": "Films", "kind": "movie"}, {"name": "Animes", "kind": "anime"}]
    kind ∈ {"movie", "series", "anime"} — "anime" est traité comme une section Plex
    de type série mais catégorisé à part pour le ciblage des notifications.
    """
    raw = getattr(settings, "vff_libraries", None)
    if not raw:
        return []
    try:
        libs = json.loads(raw)
    except Exception:
        logger.warning("vff_libraries : JSON invalide, ignoré")
        return []
    out = []
    for entry in libs if isinstance(libs, list) else []:
        name = (entry.get("name") or "").strip()
        kind = (entry.get("kind") or "").strip().lower()
        if name and kind in ("movie", "series", "anime"):
            out.append({"name": name, "kind": kind})
    return out


def _load_known_vf_episodes(db: Session, source_type: str, source_ids: list[int]) -> dict[int, dict[int, set[int]]]:
    """Charge le cache des épisodes déjà confirmés VF pour une liste de médias.

    Retourne {source_id: {season_number: {episode_number, ...}}}. Ne contient que les
    épisodes has_vf=True : un épisode confirmé VF ne redevient jamais VO, donc ce cache
    permet d'éviter tout appel Plex superflu pour les épisodes déjà connus.
    """
    if not source_ids:
        return {}
    rows = (
        db.query(VfEpisodeStatus)
        .filter(
            VfEpisodeStatus.source_type == source_type,
            VfEpisodeStatus.source_id.in_(source_ids),
            VfEpisodeStatus.has_vf.is_(True),
            VfEpisodeStatus.fr_is_default.is_(True),
        )
        .all()
    )
    out: dict[int, dict[int, set[int]]] = {}
    for r in rows:
        out.setdefault(r.source_id, {}).setdefault(r.season_number, set()).add(r.episode_number)
    return out


def _load_episode_status_map(
    db: Session, source_type: str, source_ids: list[int]
) -> dict[int, dict[int, dict[int, bool]]]:
    if not source_ids:
        return {}
    rows = (
        db.query(VfEpisodeStatus)
        .filter(VfEpisodeStatus.source_type == source_type, VfEpisodeStatus.source_id.in_(source_ids))
        .all()
    )
    out: dict[int, dict[int, dict[int, bool]]] = {}
    for row in rows:
        out.setdefault(row.source_id, {}).setdefault(row.season_number, {})[row.episode_number] = bool(row.has_vf)
    return out


def _persist_episode_status(
    db: Session,
    source_type: str,
    source_id: int,
    episode_status: dict[int, dict[int, bool]],
    now: datetime,
    french_default: dict[int, dict[int, bool]] | None = None,
) -> None:
    """Upsert le statut VF par épisode dans le cache (`vf_episode_status`)."""
    if not episode_status:
        return
    existing = {
        (r.season_number, r.episode_number): r
        for r in db.query(VfEpisodeStatus).filter(
            VfEpisodeStatus.source_type == source_type, VfEpisodeStatus.source_id == source_id
        )
    }
    for sn, eps in episode_status.items():
        for en, has_vf in eps.items():
            fr_is_default = (french_default or {}).get(sn, {}).get(en)
            row = existing.get((sn, en))
            if row:
                if row.has_vf != has_vf:
                    row.has_vf = has_vf
                if fr_is_default is not None and row.fr_is_default != fr_is_default:
                    row.fr_is_default = fr_is_default
                row.checked_at = now
            else:
                db.add(
                    VfEpisodeStatus(
                        source_type=source_type,
                        source_id=source_id,
                        season_number=sn,
                        episode_number=en,
                        has_vf=has_vf,
                        fr_is_default=fr_is_default,
                        checked_at=now,
                    )
                )


def _invalidate_vf_cache(
    db: Session,
    source_type: Optional[str] = None,
    source_id: Optional[int] = None,
    season_number: Optional[int] = None,
    episode_number: Optional[int] = None,
) -> int:
    """Invalide (supprime) des entrées du cache VF par épisode pour forcer un re-scan Plex.

    Le cache par épisode suppose qu'un épisode confirmé VF le reste (ce qui est vrai en
    fonctionnement normal), mais un faux positif de détection ou un remplacement de
    fichier côté Plex peut rendre une entrée obsolète. Ce helper permet de la purger à
    la granularité voulue, avec une portée croissante selon les paramètres fournis :
    - aucun paramètre                        : tout le cache (force globale)
    - source_type + source_id                : une série/un film entier (force série)
    - + season_number                        : une seule saison (force saison)
    - + season_number + episode_number       : un seul épisode (force épisode)

    Ne fait pas de commit : à la charge de l'appelant.
    Retourne le nombre de lignes supprimées.
    """
    q = db.query(VfEpisodeStatus)
    if source_type is not None:
        q = q.filter(VfEpisodeStatus.source_type == source_type)
    if source_id is not None:
        q = q.filter(VfEpisodeStatus.source_id == source_id)
    if season_number is not None:
        q = q.filter(VfEpisodeStatus.season_number == season_number)
    if episode_number is not None:
        q = q.filter(VfEpisodeStatus.episode_number == episode_number)
    return q.delete()


def _scan_vf_blocking(
    plex_url: str,
    plex_token: str,
    candidates: list[dict],
    libs: list[dict],
    known_vf_by_id: Optional[dict[int, dict[int, set[int]]]] = None,
    state: dict[str, Any] | None = None,
) -> list[dict]:
    """Analyse (bloquante, plexapi) la présence de VF pour chaque candidat.

    `state` : dict de progression à incrémenter (`items_scanned`) — `vff_scan_state` par
    défaut si non fourni, pour ne pas casser un appelant qui ne suit pas sa propre
    progression séparément.

    Exécutée dans un thread via asyncio.to_thread pour ne pas bloquer la boucle async.
    `known_vf_by_id` (séries) : cache par candidat, voir `_load_known_vf_episodes` —
    les épisodes déjà confirmés VF ne sont pas re-interrogés dans Plex.
    Retourne une liste de dicts : {"id", "found", "has_vf", "category", "episode_status"?}.
    """
    known_vf_by_id = known_vf_by_id or {}
    state = state if state is not None else vff_scan_state
    try:
        plex = vff.connect(plex_url, plex_token)
    except Exception as exc:
        logger.warning(f"VFF : connexion Plex impossible : {exc}")
        return []

    movie_libs = [lib["name"] for lib in libs if lib["kind"] == "movie"]
    show_libs = [(lib["name"], lib["kind"]) for lib in libs if lib["kind"] in ("series", "anime")]

    results: list[dict] = []
    for c in candidates:
        try:
            res = vff.scan_media_vf(
                plex,
                c["media_type"],
                movie_libs,
                show_libs,
                c["title"],
                c["year"],
                c["tmdb_id"],
                c["tvdb_id"],
                c["imdb_id"],
                plex_guid=c.get("plex_guid"),
                known_vf=known_vf_by_id.get(c["id"]),
            )
            results.append({"id": c["id"], **res})
        except Exception as exc:
            logger.warning(f"VFF : erreur analyse '{c.get('title')}' : {exc}")
            results.append({"id": c["id"], "found": False})
        finally:
            state["items_scanned"] += 1
    return results


def _resolve_vf_arr_instance(db: Session, req: MediaRequest, arr_type: str) -> ArrInstance | None:
    """Résout l'instance Sonarr/Radarr à utiliser pour l'auto-search VFF d'une demande."""
    if req.arr_instance_id:
        inst = (
            db.query(ArrInstance)
            .filter(ArrInstance.id == req.arr_instance_id, ArrInstance.arr_type == arr_type, ArrInstance.enabled)
            .first()
        )
        if inst:
            return inst
    return (
        db.query(ArrInstance)
        .filter(ArrInstance.arr_type == arr_type, ArrInstance.enabled, ArrInstance.is_default)
        .first()
    )


async def _prefetch_season_aired_counts(db: Session, requests: list[MediaRequest]) -> dict[int, dict[int, int]]:
    """Précharge, pour chaque série Sonarr, le nombre d'épisodes déjà diffusés par saison.

    Référence utilisée par `_series_language_milestones` pour ne pas confondre "tous les
    épisodes déjà repérés dans Plex correspondent" avec "la saison est réellement complète"
    (voir docstring de `sonarr.get_season_aired_episode_counts`). Best-effort : une série
    dont Sonarr est injoignable ou introuvable retombe sur l'ancien comportement (pas de
    référence disponible).
    """
    counts: dict[int, dict[int, int]] = {}
    for req in requests:
        if req.media_type != "show" or not req.arr_id or req.source == "seer" or req.id in counts:
            continue
        inst = _resolve_vf_arr_instance(db, req, "sonarr")
        if not inst:
            continue
        try:
            counts[req.id] = await get_season_aired_episode_counts(inst.url, inst.api_key, req.arr_id)
        except Exception as e:
            logger.warning(f"VFF : compteurs saison Sonarr indisponibles pour '{req.title}': {e}")
    return counts


async def _trigger_vf_search(db: Session, settings: Settings, req: MediaRequest) -> None:
    """Relance une recherche Sonarr/Radarr pour un média détecté en VO seule (auto-search VFF).

    Ignoré si arr_id absent ou si la demande provient de Seer (arr_id = ID Seer, pas Sonarr/Radarr).
    """
    if not req.arr_id or req.source == "seer":
        return
    arr_type = "radarr" if req.media_type == "movie" else "sonarr"
    inst = _resolve_vf_arr_instance(db, req, arr_type)
    if not inst:
        return
    try:
        if arr_type == "radarr":
            ok = await search_movie(inst.url, inst.api_key, req.arr_id)
        else:
            ok = await search_series(inst.url, inst.api_key, req.arr_id)
        if ok:
            logger.info(f"VFF auto-search lancé pour '{req.title}' ({arr_type})")
    except Exception as e:
        logger.warning(f"VFF auto-search échec pour '{req.title}': {e}")


_last_section_refresh: dict[str, datetime] = {}
_SECTION_REFRESH_COOLDOWN = timedelta(seconds=45)

_plex_connector_cache: dict[str, tuple[bool, datetime]] = {}
_PLEX_CONNECTOR_CACHE_TTL = timedelta(minutes=10)


async def has_native_plex_connector(arr_type: str, arr_url: str, arr_api_key: str, cache_key: str) -> bool:
    """Indique si Sonarr/Radarr a déjà un connecteur natif "Plex Media Server" actif.

    Si oui, l'*arr notifie déjà Plex directement (scan ciblé sur le dossier importé) à
    chaque import — notre propre refresh de section deviendrait redondant. Résultat mis
    en cache (`_PLEX_CONNECTOR_CACHE_TTL`) pour ne pas interroger Sonarr/Radarr à chaque
    webhook reçu. En cas d'erreur réseau, on suppose prudemment "non" (mieux vaut un
    refresh en trop qu'un défaut de refresh).
    """
    cached = _plex_connector_cache.get(cache_key)
    now = now_utc()
    if cached and now - cached[1] < _PLEX_CONNECTOR_CACHE_TTL:
        return cached[0]

    client = sonarr if arr_type == "sonarr" else radarr
    try:
        notifications = await client.get_notifications(arr_url, arr_api_key)
        found = client.find_plex_notification(notifications) is not None
    except Exception as e:
        logger.warning(f"Vérification du connecteur Plex natif échouée pour {arr_type}: {e}")
        found = False
    _plex_connector_cache[cache_key] = (found, now)
    return found


async def trigger_plex_library_refresh(
    settings: Settings,
    media_type: str,
    *,
    arr_type: str | None = None,
    arr_url: str | None = None,
    arr_api_key: str | None = None,
    cache_key: str | None = None,
) -> None:
    """Déclenche un scan Plex immédiat de la bibliothèque concernée par un import *arr.

    Appelé depuis le webhook Sonarr/Radarr (Download/Import), au lieu d'attendre le
    calendrier de scan de Plex — réduit la latence avant que `has_vf` soit détectable par
    le scan eager (`scan_and_notify_availability`) ou le scan léger. Anti-rebond : ignore
    les sections déjà rafraîchies récemment (import groupé, ex. pack de saison qui
    déclenche plusieurs webhooks Download en quelques secondes).

    Si `arr_type`/`arr_url`/`arr_api_key`/`cache_key` sont fournis, court-circuite d'abord
    si Sonarr/Radarr a déjà un connecteur natif "Plex Media Server" actif — cet *arr
    notifie alors déjà Plex directement, plus précisément (scan ciblé) que notre refresh
    de section complète.
    """
    if arr_type and arr_url and arr_api_key and cache_key:
        arr_label = arr_type.capitalize()
        if await has_native_plex_connector(arr_type, arr_url, arr_api_key, cache_key):
            logger.info(f"Plex : refresh actif ignoré, {arr_label} gère déjà nativement le scan Plex")
            return
        logger.info(f"Plex : refresh actif, {arr_label} ne gère pas le scan Plex")

    if not settings.vff_enabled or not settings.plex_url or not settings.plex_token:
        return
    libs = _parse_vff_libraries(settings)
    kinds = ("movie",) if media_type == "movie" else ("series", "anime")
    names = [lib["name"] for lib in libs if lib["kind"] in kinds]
    if not names:
        return

    now = now_utc()
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    due = [n for n in names if now - _last_section_refresh.get(n, epoch) > _SECTION_REFRESH_COOLDOWN]
    if not due:
        return
    for n in due:
        _last_section_refresh[n] = now

    try:
        await asyncio.to_thread(vff.refresh_sections_blocking, settings.plex_url, settings.plex_token, due)
        logger.info(f"Plex : scan déclenché pour {due}")
    except Exception as e:
        logger.warning(f"Déclenchement du scan Plex échoué : {e}")


def _queue_availability_progress(
    settings: Settings,
    req: MediaRequest,
    db: Session,
    *,
    language: str,
    episode_status: dict | None = None,
    has_vf_full: bool = False,
    season_aired_counts: dict[int, int] | None = None,
) -> int:
    """Point d'entrée unique pour les notifications de progression VO/VF (films et
    séries) — remplace l'ancien `_queue_language_progress_notifications`. Respecte le
    mode "classic" (movie_notify_language/series_notify_language désactivé) et le suivi
    "sans langue" des séries (délégué à `check_episode_tracking`, jamais les deux à la
    fois pour éviter un double suivi du même évènement)."""
    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    if req.media_type != "show":
        if not _resolve_movie_notify_language(settings, user_obj):
            if not req.available_mail_sent:
                _notify("available", settings, req, db)
            return 0
        return int(_queue_milestone(settings, req, db, scope="movie", language=language))

    if not _resolve_series_notify_language(settings, user_obj):
        return 0
    return _queue_show_milestones(
        settings,
        req,
        db,
        language=language,
        episode_status=episode_status,
        has_vf_full=has_vf_full,
        season_aired_counts=season_aired_counts,
    )


def _apply_vf_result(
    req: MediaRequest,
    has_vf: bool,
    category: str | None,
    db: Session,
    settings: Settings,
    now: datetime,
    season_aired_counts: dict[int, int] | None = None,
    episode_status: dict | None = None,
    granularity: str | None = None,
) -> tuple[bool, int, int]:
    """Applique une transition VO/VF à une demande (notifications incluses).

    Extrait du scan périodique (`check_vf_statuses`) pour être réutilisable par le scan
    immédiat déclenché à la disponibilité (`scan_and_notify_availability`).

    `granularity` : si déjà connue (ex: propagée depuis un LibraryItem lié), on
    l'utilise directement — sinon elle est calculée depuis `episode_status`.
    Retourne (trigger_search, vf_delta, vo_delta) — `trigger_search` indique si une
    recherche VFF auto (Sonarr/Radarr) doit être déclenchée par l'appelant (await
    nécessaire, donc hors de cette fonction synchrone) ; `vf_delta`/`vo_delta` sont le
    nombre de notifications effectivement mises en file (pour les compteurs du scan par
    lot — toujours 0 pour un scan immédiat à un seul média).
    """
    was_tracking = req.has_vf is False  # déjà identifié VO au passage précédent
    req.vf_category = category or req.vf_category
    req.vf_checked_at = now
    trigger_search = False
    vf_delta = 0
    vo_delta = 0

    if has_vf:
        req.has_vf = True
        req.vf_granularity = "full"
        if was_tracking:
            # Transition VO → VF : on prévient
            req.vf_available_at = now
            db.commit()
            vf_delta = _queue_availability_progress(
                settings,
                req,
                db,
                language="vf",
                episode_status=episode_status,
                has_vf_full=True,
                season_aired_counts=season_aired_counts,
            )
            logger.info(f"VFF : '{req.title}' est désormais disponible en VF")
        else:
            # Première analyse, VF présente : envoie l'« available » différé
            # (une seule notification — pas de doublon avec vo_only).
            db.commit()
            _notify("available", settings, req, db)
    else:
        # VO uniquement
        req.has_vf = False
        req.vf_granularity = granularity if granularity is not None else vff.compute_vf_granularity(episode_status)
        if not was_tracking:
            if not req.available_mail_sent:
                # Première détection VO : la notification « VO » tient lieu
                # d'annonce de disponibilité. On marque available_mail_sent
                # pour éviter tout doublon « available » ultérieur.
                req.available_mail_sent = True
                db.commit()
                vo_delta = _queue_availability_progress(
                    settings,
                    req,
                    db,
                    language="vo",
                    episode_status=episode_status,
                    has_vf_full=False,
                    season_aired_counts=season_aired_counts,
                )
                logger.info(f"VFF : '{req.title}' disponible en VO uniquement — suivi VF activé")
            else:
                # Dispo déjà notifiée (fallback scan-lag) → suivi silencieux
                db.commit()
            trigger_search = bool(settings.vff_auto_search)
        else:
            db.commit()
            vf_delta = _queue_availability_progress(
                settings,
                req,
                db,
                language="vf",
                episode_status=episode_status,
                has_vf_full=False,
                season_aired_counts=season_aired_counts,
            )
    return trigger_search, vf_delta, vo_delta


async def scan_and_notify_availability(req: MediaRequest, settings: Settings, db: Session) -> bool:
    """Scanne Plex immédiatement pour CE seul média avant d'envoyer le mail de disponibilité.

    Appelé au moment précis où une demande devient disponible (webhook temps réel ou poll
    *arr), pour proposer directement le bon mail (VF / VO / jalon série) plutôt que le
    mail générique "Disponible sur Plex" — sans attendre le prochain scan VFF planifié.

    Retourne True si le scan a tranché (mail déjà géré ci-dessous) — l'appelant ne doit
    alors plus rien envoyer lui-même. Retourne False si le scan n'a pas pu conclure (VFF
    désactivé, mode "classic" de l'utilisateur, Plex non configuré, ou média pas encore
    indexé dans Plex) — l'appelant garde son comportement actuel (mail générique, ou
    attente du prochain scan planifié qui rattrapera le cas via son propre filet de
    sécurité).
    """
    if not settings.vff_enabled or not settings.plex_url or not settings.plex_token:
        return False

    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    series_no_language = False
    if req.media_type == "movie":
        if not _resolve_movie_notify_language(settings, user_obj):
            return False
    else:
        series_no_language = not _resolve_series_notify_language(settings, user_obj)

    libs = _parse_vff_libraries(settings)
    if not libs:
        return False

    candidate = {
        "id": req.id,
        "title": req.title,
        "year": req.year,
        "media_type": req.media_type,
        "tmdb_id": req.tmdb_id,
        "tvdb_id": req.tvdb_id,
        "imdb_id": req.imdb_id,
        "plex_guid": req.plex_guid,
    }
    known_vf = _load_known_vf_episodes(db, "request", [req.id]) if req.media_type == "show" else {}
    try:
        results = await asyncio.to_thread(
            _scan_vf_blocking, settings.plex_url, settings.plex_token, [candidate], libs, known_vf
        )
    except Exception as e:
        logger.warning(f"Scan eager VFF échec pour '{req.title}': {e}")
        return False

    res: dict[str, Any] = results[0] if results else {"found": False}
    if not res.get("found"):
        # Pas encore indexé côté Plex (course avec le scan Sonarr/Radarr → Plex) : on ne
        # force rien, le prochain scan planifié (et son filet de sécurité) prendra le relais.
        return False

    now = now_utc_naive()
    episode_status: dict[int, dict[int, bool]] | None = res.get("episode_status")
    if episode_status:
        _persist_episode_status(db, "request", req.id, episode_status, now, res.get("french_default"))
        db.commit()

    if req.media_type == "show" and series_no_language:
        _queue_show_milestones(settings, req, db, language=None, episode_status=episode_status)
        return True

    season_aired_counts = None
    if req.media_type == "show":
        counts = await _prefetch_season_aired_counts(db, [req])
        season_aired_counts = counts.get(req.id)

    trigger_search, _, _ = _apply_vf_result(
        req,
        res["has_vf"],
        res.get("category"),
        db,
        settings,
        now,
        season_aired_counts=season_aired_counts,
        episode_status=episode_status,
    )
    if trigger_search:
        await _trigger_vf_search(db, settings, req)
    return True


vff_light_scan_state: dict[str, Any] = {
    "status": "idle",  # "idle" | "running" | "failed"
    "started_at": None,
    "finished_at": None,
    "items_scanned": 0,
    "total_items": 0,
    "error": None,
}


async def _run_vf_scan(only_unseen: bool, state: dict[str, Any], label: str, force: bool = False) -> None:
    """Cœur du job VFF : détecte la présence de VF sur les médias disponibles et notifie.

    - Première analyse d'un média (has_vf IS NULL) :
        · VF présente  → has_vf=True (pas de notification, l'« available » a suffi)
        · VO seulement → has_vf=False + notification « disponible en VO » + suivi actif
    - Ré-analyse des médias suivis (has_vf=False), seulement si `only_unseen=False` :
        · VF désormais présente → has_vf=True + notification « VF disponible »

    `only_unseen=True` restreint aux médias jamais analysés (`has_vf IS NULL`) : sous-
    ensemble généralement petit, utilisé par le scan léger et fréquent
    (`check_new_vf_availability`) pour combler le trou laissé par un scan eager raté sans
    attendre le scan complet (`check_vf_statuses`, tous les médias en attente de VF, sur
    un intervalle plus long).

    `force=True` : re-scanne aussi les médias déjà marqués `has_vf=True` (normalement
    exclus, voir `req_has_vf_filter`/`lib_has_vf_filter` ci-dessous) — utilisé quand le
    cache par épisode est suspecté obsolète (faux positif, remplacement de fichier côté
    Plex). L'appelant est responsable d'avoir déjà vidé le cache par épisode
    (`_invalidate_vf_cache`) avant d'appeler cette fonction.

    La détection Plex (plexapi) est bloquante : elle est déportée dans un thread.
    """
    if state["status"] == "running":
        logger.info(f"VFF ({label}) : un scan est déjà en cours, skip")
        return

    state["status"] = "running"
    state["started_at"] = now_utc().isoformat()
    state["finished_at"] = None
    state["items_scanned"] = 0
    state["total_items"] = 0
    state["error"] = None

    db = SessionLocal()
    try:
        settings = db.query(Settings).first()
        if not settings or not settings.vff_enabled:
            state["status"] = "idle"
            return
        if not settings.plex_url or not settings.plex_token:
            logger.info(f"VFF ({label}) : Plex non configuré, skip")
            state["status"] = "idle"
            return

        libs = _parse_vff_libraries(settings)
        if not libs:
            logger.info(f"VFF ({label}) : aucune bibliothèque configurée, skip")
            state["status"] = "idle"
            return

        # --- Réconciliation : demandes jamais passées "available" mais déjà présentes
        # dans Plex. Sonarr/Radarr peut ne jamais détecter le fichier (import manuel,
        # retard d'indexation, média ajouté directement dans Plex sans passer par *arr...),
        # laissant la demande bloquée en pending/sent_to_arr indéfiniment alors que la
        # bibliothèque Plex prouve déjà sa présence réelle. La présence dans LibraryItem
        # devient donc un déclencheur de disponibilité à part entière, indépendant de ce
        # que rapporte *arr.
        pending_q = (
            db.query(MediaRequest)
            .filter(
                MediaRequest.status.notin_([RequestStatus.available, RequestStatus.failed]),
                MediaRequest.library_item_id.is_(None),
            )
            .all()
        )
        promoted = 0
        now_reconcile = now_utc_naive()
        for req in pending_q:
            li = _link_request_to_library_item(db, req)
            if not li:
                continue
            req.status = RequestStatus.available
            req.available_at = now_reconcile
            req.next_release_at = None
            req.next_release_label = None
            promoted += 1
            logger.info(f"VFF : '{req.title}' détecté disponible via la bibliothèque Plex (arr en retard/inconnu)")
            # Pas de notification "available" ici : cette fonction ne tourne que si VFF est
            # actif (garde en tête de fonction), donc has_vf est encore None juste après la
            # promotion -> la demande retombe naturellement dans candidates_q ci-dessous et
            # reçoit "available" (VF présente) ou "vo_only" (VO) selon le résultat du scan,
            # sans jamais doubler la notification.
        if promoted:
            db.commit()
            logger.info(f"VFF ({label}) : {promoted} demande(s) promue(s) 'disponible' via la bibliothèque Plex")

        req_has_vf_filter: ColumnElement[bool]
        lib_has_vf_filter: ColumnElement[bool]
        if force:
            req_has_vf_filter = true()
            lib_has_vf_filter = true()
        else:
            req_has_vf_filter = (
                MediaRequest.has_vf.is_(None)
                if only_unseen
                else (MediaRequest.has_vf.is_(None)) | (MediaRequest.has_vf.is_(False))
            )
            lib_has_vf_filter = (
                LibraryItem.has_vf.is_(None)
                if only_unseen
                else (LibraryItem.has_vf.is_(None)) | (LibraryItem.has_vf.is_(False))
            )
        candidates_q = (
            db.query(MediaRequest).filter(MediaRequest.status == RequestStatus.available, req_has_vf_filter).all()
        )
        lib_q = db.query(LibraryItem).filter(lib_has_vf_filter).all()
        if not candidates_q and not lib_q:
            state["status"] = "idle"
            state["finished_at"] = now_utc().isoformat()
            return

        # Rapprochement demande <-> LibraryItem : une fois liée, une demande n'est plus
        # scannée indépendamment dans Plex — son has_vf est propagé depuis le LibraryItem
        # (source de vérité unique), pour éviter deux scans divergents du même média
        # (ex: Bibliothèque affiche VF alors que Demandes affiche encore VO en attente).
        linked_pairs: list[tuple[MediaRequest, LibraryItem]] = []
        unlinked_candidates_q: list[MediaRequest] = []
        for req in candidates_q:
            li = _link_request_to_library_item(db, req)
            if li:
                linked_pairs.append((req, li))
            else:
                unlinked_candidates_q.append(req)
        if linked_pairs:
            db.commit()  # persiste les nouveaux library_item_id

        def _to_candidate(r):
            return {
                "id": r.id,
                "title": r.title,
                "year": r.year,
                "media_type": r.media_type,
                "tmdb_id": r.tmdb_id,
                "tvdb_id": r.tvdb_id,
                "imdb_id": r.imdb_id,
                "plex_guid": r.plex_guid,
            }

        candidates = [_to_candidate(r) for r in unlinked_candidates_q]
        lib_candidates = [_to_candidate(r) for r in lib_q]
        state["total_items"] = len(candidates) + len(lib_candidates)
        logger.info(
            f"VFF ({label}) : analyse de {len(candidates)} demande(s) non liée(s) + {len(lib_candidates)} média(s) "
            f"de bibliothèque ({len(linked_pairs)} demande(s) liée(s), pas de re-scan)"
        )

        now = now_utc_naive()

        results_by_id = {}
        if candidates:
            known_vf_requests = _load_known_vf_episodes(db, "request", [c["id"] for c in candidates])
            results = await asyncio.to_thread(
                _scan_vf_blocking,
                settings.plex_url,
                settings.plex_token,
                candidates,
                libs,
                known_vf_requests,
                state,
            )
            results_by_id = {r["id"]: r for r in results}
            for r in results:
                episode_status = r.get("episode_status")
                if episode_status:
                    _persist_episode_status(db, "request", r["id"], episode_status, now, r.get("french_default"))
            if any(r.get("episode_status") for r in results):
                db.commit()

        season_counts_by_req_id = await _prefetch_season_aired_counts(
            db, unlinked_candidates_q + [req for req, _ in linked_pairs]
        )

        newly_vo = 0
        newly_vf = 0
        newly_fallback = 0

        for req in unlinked_candidates_q:
            res = results_by_id.get(req.id)

            if not res or not res.get("found"):
                # Média disponible mais pas (encore) indexé dans Plex.
                # Filet de sécurité : si l'« available » a été différé (VFF actif) et
                # jamais envoyé, notifier la disponibilité générique maintenant pour
                # ne pas laisser l'utilisateur sans information. has_vf reste None :
                # un passage ultérieur détectera la VF/VO (suivi silencieux, pas de doublon).
                if req.has_vf is None and not req.available_mail_sent:
                    _notify("available", settings, req, db)
                    newly_fallback += 1
                continue

            trigger_search, vf_delta, vo_delta = _apply_vf_result(
                req,
                res["has_vf"],
                res.get("category"),
                db,
                settings,
                now,
                season_aired_counts=season_counts_by_req_id.get(req.id),
                episode_status=res.get("episode_status"),
            )
            newly_vf += vf_delta
            newly_vo += vo_delta
            if trigger_search:
                await _trigger_vf_search(db, settings, req)

        # --- Médias de bibliothèque : état VF pour affichage (pas de notification) ---
        lib_updated = 0
        if lib_candidates:
            known_vf_lib = _load_known_vf_episodes(db, "library_item", [c["id"] for c in lib_candidates])
            lib_results = await asyncio.to_thread(
                _scan_vf_blocking,
                settings.plex_url,
                settings.plex_token,
                lib_candidates,
                libs,
                known_vf_lib,
                state,
            )
            lib_by_id = {r["id"]: r for r in lib_results}
            for li in lib_q:
                res = lib_by_id.get(li.id)
                if not res or not res.get("found"):
                    continue
                prev = li.has_vf
                li.vf_category = res.get("category") or li.vf_category
                li.vf_checked_at = now
                li.has_vf = bool(res["has_vf"])
                li.vf_granularity = "full" if li.has_vf else vff.compute_vf_granularity(res.get("episode_status"))
                if li.has_vf and prev is False:
                    li.vf_available_at = now
                lib_updated += 1
                episode_status = res.get("episode_status")
                if episode_status:
                    _persist_episode_status(db, "library_item", li.id, episode_status, now, res.get("french_default"))
            db.commit()

        # --- Demandes liées à un LibraryItem : propager son has_vf, pas de re-scan Plex ---
        linked_updated = 0
        linked_episode_status = _load_episode_status_map(db, "library_item", list({li.id for _, li in linked_pairs}))
        for req, li in linked_pairs:
            if li.has_vf is None:
                continue  # LibraryItem pas encore résolu ; réessaiera au prochain cycle
            trigger_search, vf_delta, vo_delta = _apply_vf_result(
                req,
                li.has_vf,
                li.vf_category,
                db,
                settings,
                now,
                season_aired_counts=season_counts_by_req_id.get(req.id),
                episode_status=linked_episode_status.get(li.id),
                granularity=li.vf_granularity,
            )
            newly_vf += vf_delta
            newly_vo += vo_delta
            if trigger_search:
                await _trigger_vf_search(db, settings, req)
            linked_updated += 1

        logger.info(
            f"VFF ({label}) : analyse terminée ({newly_vo} nouveau(x) VO, {newly_vf} VF détectée(s), "
            f"{newly_fallback} dispo notifiée(s) en filet, {lib_updated} média(s) de bibliothèque mis à jour, "
            f"{linked_updated} demande(s) liée(s) synchronisée(s))"
        )
        state["status"] = "idle"
        state["finished_at"] = now_utc().isoformat()
    except Exception as e:
        logger.error(f"Erreur _run_vf_scan ({label}) : {e}")
        state["status"] = "failed"
        state["error"] = str(e)
    finally:
        db.close()


async def check_vf_statuses(force: bool = False) -> None:
    """Scan complet : tous les médias en attente de VF (`has_vf IS NULL` ou `False`),
    sur l'intervalle long (`vff_recheck_interval_minutes`). `force=True` (scan manuel
    "Forcer l'analyse complète") re-scanne aussi les médias déjà marqués VF."""
    await _run_vf_scan(only_unseen=False, state=vff_scan_state, label="complet", force=force)


async def check_new_vf_availability() -> None:
    """Scan léger : uniquement les médias jamais analysés (`has_vf IS NULL`), sur un
    intervalle court (1 min) — comble le trou laissé par un scan eager raté
    (`scan_and_notify_availability`) sans attendre le prochain scan complet."""
    await _run_vf_scan(only_unseen=True, state=vff_light_scan_state, label="léger")


async def check_episode_tracking():
    """Job de suivi épisode/saison "sans langue" (voir `_resolve_series_notify_language`).

    Contrairement à `check_vf_statuses`, ne dépend pas de `settings.vff_enabled` : seules
    les demandes dont `series_notify_language` résolu (global ou par utilisateur) vaut
    False sont scannées. Réutilise le même scanner Plex (`_scan_vf_blocking`) — la présence
    d'un épisode dans `episode_status` (retourné par le scan, indépendamment de sa valeur
    has_vf) suffit à prouver sa présence dans la bibliothèque Plex, langue non prise en
    compte ici. Les jalons sont dédupliqués via `NotificationMilestone` (direction="simple"),
    donc rescanner une série déjà notifiée est sans effet (pas de doublon).
    """
    if episode_scan_state["status"] == "running":
        logger.info("Suivi épisode : un scan est déjà en cours, skip")
        return

    episode_scan_state["status"] = "running"
    episode_scan_state["started_at"] = now_utc().isoformat()
    episode_scan_state["finished_at"] = None
    episode_scan_state["items_scanned"] = 0
    episode_scan_state["total_items"] = 0
    episode_scan_state["error"] = None

    db = SessionLocal()
    try:
        settings = db.query(Settings).first()
        if not settings or not settings.plex_url or not settings.plex_token:
            episode_scan_state["status"] = "idle"
            return

        libs = _parse_vff_libraries(settings)
        if not libs:
            episode_scan_state["status"] = "idle"
            return

        global_no_language = not _resolve_series_notify_language(settings, None)
        candidates_q = (
            db.query(MediaRequest)
            .filter(MediaRequest.status == RequestStatus.available, MediaRequest.media_type == "show")
            .all()
        )
        users_by_id = {u.plex_user_id: u for u in db.query(PlexUser).all()}

        def _wants_no_language(req: MediaRequest) -> bool:
            user_obj = users_by_id.get(req.plex_user_id)
            if user_obj and user_obj.series_notify_language is not None:
                return not user_obj.series_notify_language
            return global_no_language

        candidates_q = [r for r in candidates_q if _wants_no_language(r)]
        if not candidates_q:
            episode_scan_state["status"] = "idle"
            episode_scan_state["finished_at"] = now_utc().isoformat()
            return

        def _to_candidate(r):
            return {
                "id": r.id,
                "title": r.title,
                "year": r.year,
                "media_type": r.media_type,
                "tmdb_id": r.tmdb_id,
                "tvdb_id": r.tvdb_id,
                "imdb_id": r.imdb_id,
                "plex_guid": r.plex_guid,
            }

        candidates = [_to_candidate(r) for r in candidates_q]
        episode_scan_state["total_items"] = len(candidates)
        logger.info(f"Suivi épisode : analyse de {len(candidates)} série(s) en mode simple")

        now = now_utc_naive()
        results = await asyncio.to_thread(
            _scan_vf_blocking, settings.plex_url, settings.plex_token, candidates, libs, None, episode_scan_state
        )
        results_by_id = {r["id"]: r for r in results}
        season_counts_by_req_id = await _prefetch_season_aired_counts(db, candidates_q)

        notified = 0
        for req in candidates_q:
            res = results_by_id.get(req.id)
            if not res or not res.get("found"):
                continue
            episode_status = res.get("episode_status")
            if episode_status:
                _persist_episode_status(db, "request", req.id, episode_status, now, res.get("french_default"))
                db.commit()
            notified += _queue_show_milestones(
                settings,
                req,
                db,
                language=None,
                episode_status=episode_status,
                season_aired_counts=season_counts_by_req_id.get(req.id),
            )

        logger.info(f"Suivi épisode : analyse terminée ({notified} notification(s) déclenchée(s))")
        episode_scan_state["status"] = "idle"
        episode_scan_state["finished_at"] = now_utc().isoformat()
    except Exception as e:
        logger.error(f"Erreur check_episode_tracking : {e}")
        episode_scan_state["status"] = "failed"
        episode_scan_state["error"] = str(e)
    finally:
        db.close()


def trigger_vff_scan_background(force: bool = False):
    if vff_scan_state["status"] == "running":
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(check_vf_statuses(force=force))
    except RuntimeError:
        pass
