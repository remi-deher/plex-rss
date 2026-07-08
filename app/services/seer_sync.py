import logging
import re
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import MediaRequest, PlexUser, RequestStatus, Settings
from ..utils import now_utc, now_utc_naive
from . import watchlist_poller
from .notification_orchestrator import _add_co_requester, _notify
from .seer import _headers as _seer_headers
from .seer import _resolve_tmdb_id as _seer_resolve_tmdb_id
from .seer import get_user_requests as seer_get_user_requests
from .seer import get_users as seer_get_users
from .seer import is_request_available as seer_available
from .seer import request_media as seer_request

logger = logging.getLogger(__name__)

_DEFAULT_SESSION_LOCAL = SessionLocal


def _open_session():
    if SessionLocal is not _DEFAULT_SESSION_LOCAL:
        return SessionLocal()
    return watchlist_poller.SessionLocal()


def _parse_seer_dt(iso: str | None) -> datetime | None:
    """Convertit une chaîne ISO 8601 Seer en datetime UTC naïf."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return None


async def sync_seer_users():
    """Synchronise seer_user_id et seer_active sur chaque PlexUser.

    Stratégie d'automatch par ordre de priorité (s'arrête au premier succès) :
    1. Email exact (plex_email == seer.email)
    2. plexUsername Seer == display_name Plex (case-insensitive)

    Met à jour seer_user_id, seer_active. Ne touche pas aux liaisons
    déjà faites manuellement sauf si l'email correspond (plus fiable).

    Tous les comptes Seer sans équivalent RSS sont importés (source='seer'),
    même sans demande (seer_active=False dans ce cas) — un compte Plex visible
    dans Seer mais jamais utilisé doit pouvoir apparaître dans l'app.
    """
    db = _open_session()
    try:
        settings = db.query(Settings).first()
        if not settings or not settings.seer_enabled or not settings.seer_url or not settings.seer_api_key:
            return

        seer_users = await seer_get_users(settings.seer_url, settings.seer_api_key)
        if not seer_users:
            return

        # Index secondaire : plexUsername (lowercase) → info Seer
        by_plex_username: dict[str, dict] = {}
        for info in seer_users.values():
            pu = (info.get("plex_username") or "").lower().strip()
            if pu:
                by_plex_username[pu] = info

        updated = 0
        # Les utilisateurs source="seer" sont gérés en passe 4, pas ici
        matched_seer_ids: set[int] = {
            u.seer_user_id for u in db.query(PlexUser).all() if u.seer_user_id and u.source != "seer"
        }

        all_plex_users = db.query(PlexUser).all()

        for user in all_plex_users:
            info = None
            method = None

            # 1. Match par email
            email = (user.plex_email or "").lower().strip()
            if email and email in seer_users:
                info = seer_users[email]
                method = "email"

            # 2. Match par plexUsername ↔ display_name (seulement si pas déjà lié)
            if not info and not user.seer_user_id:
                name = (user.display_name or "").lower().strip()
                if name and name in by_plex_username:
                    candidate = by_plex_username[name]
                    if candidate["id"] not in matched_seer_ids:
                        info = candidate
                        method = "plex_username"

            if not info:
                continue

            active = info["request_count"] > 0
            changed = False
            if user.seer_user_id != info["id"]:
                user.seer_user_id = info["id"]
                matched_seer_ids.add(info["id"])
                changed = True
                logger.info(
                    f"Seer automatch [{method}]: {user.display_name or user.plex_user_id} → {info['display_name']} ({info['id']})"
                )
            if user.seer_active != active:
                user.seer_active = active
                changed = True
            if changed:
                updated += 1

        # 3. Match par médias communs (≥ 2 tmdb_id en commun)
        seer_by_id = {info["id"]: info for info in seer_users.values()}
        unmatched_plex = [u for u in all_plex_users if not u.seer_user_id]
        unmatched_seer_infos = [info for info in seer_users.values() if info["id"] not in matched_seer_ids]

        if unmatched_plex and unmatched_seer_infos:
            # Récupérer les demandes de chaque utilisateur Seer non matché (1 appel API par user)
            seer_media_map: dict[int, set[str]] = {}
            for seer_info in unmatched_seer_infos:
                reqs = await seer_get_user_requests(settings.seer_url, settings.seer_api_key, seer_info["id"])
                tmdb_ids = {r["tmdb_id"] for r in reqs if r.get("tmdb_id")}
                if tmdb_ids:
                    seer_media_map[seer_info["id"]] = tmdb_ids

            for user in unmatched_plex:
                rows = (
                    db.query(MediaRequest.tmdb_id)
                    .filter(
                        MediaRequest.plex_user_id == user.plex_user_id,
                        MediaRequest.tmdb_id.isnot(None),
                    )
                    .all()
                )
                user_tmdb_ids = {r[0] for r in rows}
                if len(user_tmdb_ids) < 2:
                    continue

                best_seer_id = None
                best_count = 0
                for seer_id, seer_tmdb_ids in seer_media_map.items():
                    if seer_id in matched_seer_ids:
                        continue
                    common = len(user_tmdb_ids & seer_tmdb_ids)
                    if common >= 2 and common > best_count:
                        best_count = common
                        best_seer_id = seer_id

                if best_seer_id:
                    info = seer_by_id[best_seer_id]
                    user.seer_user_id = best_seer_id
                    matched_seer_ids.add(best_seer_id)
                    user.seer_active = info["request_count"] > 0
                    updated += 1
                    logger.info(
                        f"Seer automatch [media/{best_count}]: {user.display_name or user.plex_user_id} → {info['display_name']} ({best_seer_id})"
                    )

        # 4. Créer les utilisateurs Seer sans équivalent RSS (Seer-only)
        created = 0
        for info in seer_users.values():
            if info["id"] in matched_seer_ids:
                continue
            synthetic_id = f"seer:{info['id']}"
            existing = db.query(PlexUser).filter(PlexUser.plex_user_id == synthetic_id).first()
            if existing:
                # Mettre à jour les infos si elles ont changé
                changed = False
                if existing.display_name != info["display_name"]:
                    existing.display_name = info["display_name"]
                    changed = True
                if existing.seer_active != (info["request_count"] > 0):
                    existing.seer_active = info["request_count"] > 0
                    changed = True
                if changed:
                    updated += 1
                matched_seer_ids.add(info["id"])
                continue

            email = next((e for e in seer_users if seer_users[e]["id"] == info["id"]), None)
            new_user = PlexUser(
                plex_user_id=synthetic_id,
                display_name=info["display_name"],
                plex_email=email,
                seer_user_id=info["id"],
                seer_active=info["request_count"] > 0,
                source="seer",
                enabled=True,
                notify_admin=True,
                notify_on_request=False,
                notify_on_available=False,
            )
            db.add(new_user)
            matched_seer_ids.add(info["id"])
            created += 1
            logger.info(f"Seer-only user créé : {info['display_name']} (seer:{info['id']})")

        if updated or created:
            db.commit()
            logger.info(f"Seer sync users: {updated} mis à jour, {created} créé(s)")
    except Exception:
        logger.exception("Seer sync users échouée")
    finally:
        db.close()


async def sync_seer_requests():
    """Importe toutes les demandes Seer dans MediaRequest.

    Pour chaque PlexUser avec un seer_user_id connu, récupère l'historique
    complet des demandes Seer et upserte dans MediaRequest (source='seer').
    Statut : available si media.status 4 ou 5, sinon sent_to_arr.
    Cela permet d'outrepasser la limite des 50 items du flux RSS.
    """
    db = _open_session()
    try:
        settings = db.query(Settings).first()
        if not settings or not settings.seer_enabled or not settings.seer_url or not settings.seer_api_key:
            return

        matched_users = db.query(PlexUser).filter(PlexUser.seer_user_id.isnot(None)).all()
        if not matched_users:
            logger.info("Seer sync requests: aucun utilisateur associé à Seer")
            return

        total_upserted = 0
        for user in matched_users:
            requests = await seer_get_user_requests(settings.seer_url, settings.seer_api_key, user.seer_user_id)
            for req in requests:
                # Dédup global : cherche par tmdb_id tous utilisateurs confondus
                existing = watchlist_poller._find_global_request(
                    db, req["media_type"], req["tmdb_id"], req["title"], req.get("tvdb_id")
                )

                seer_requested_at = _parse_seer_dt(req.get("requested_at"))
                seer_updated_at = _parse_seer_dt(req.get("updated_at"))
                is_available = req["status"] == "available"

                if existing:
                    changed = False
                    # Enrichir les identifiants manquants (ex : entrée RSS tvdb-only enrichie par Seer tmdb)
                    if req.get("tmdb_id") and not existing.tmdb_id:
                        existing.tmdb_id = req["tmdb_id"]
                        changed = True
                    if req.get("tvdb_id") and not existing.tvdb_id:
                        existing.tvdb_id = req["tvdb_id"]
                        changed = True
                    # Si demande appartient à un autre utilisateur, ajouter comme co-demandeur
                    if existing.plex_user_id != user.plex_user_id:
                        if _add_co_requester(existing, user.plex_user_id, user.display_name or user.plex_user_id):
                            changed = True
                    # Hybride : Seer a réellement traité la demande → corriger source
                    is_hybrid = user.seer_user_id and user.source != "seer"
                    if is_hybrid and existing.source != "seer":
                        existing.source = "seer"
                        changed = True
                    # Enrichir les champs manquants / corriger placeholder
                    if req["title"] and (not existing.title or existing.title.startswith("[Seer #")):
                        existing.title = req["title"]
                        changed = True
                    if req.get("poster_url") and not existing.poster_url:
                        existing.poster_url = req["poster_url"]
                        changed = True
                    if req.get("overview") and not existing.overview:
                        existing.overview = req["overview"]
                        changed = True
                    # Date de demande :
                    # - source='seer'            : toujours corriger (createdAt Seer est la vraie date)
                    # - source='rss' + hybride   : corriger aussi — le poll RSS ne donne que l'heure
                    #                              de détection, Seer connaît la vraie date de demande
                    # - source='rss' + RSS-only  : conserver (pas de date Seer disponible)
                    if seer_requested_at:
                        if existing.source == "seer" or is_hybrid:
                            # Garder la date la plus ancienne (première demande tous utilisateurs confondus)
                            should_update = existing.requested_at is None or seer_requested_at < existing.requested_at
                            if should_update:
                                logger.info(
                                    f"Date corrigée pour '{existing.title}': "
                                    f"{existing.requested_at} → {seer_requested_at}"
                                )
                                existing.requested_at = seer_requested_at
                                changed = True
                    elif existing.source == "seer" or is_hybrid:
                        logger.warning(
                            f"'{existing.title}' (seer_req #{req.get('seer_request_id')}): "
                            f"createdAt absent — requested_at non corrigé (valeur actuelle: {existing.requested_at})"
                        )
                    if is_available and existing.status != RequestStatus.available:
                        existing.status = RequestStatus.available
                        existing.arr_id = existing.arr_id or req["seer_request_id"]
                        existing.available_at = seer_updated_at or now_utc_naive()
                        changed = True
                    elif is_available and seer_updated_at and existing.available_at != seer_updated_at:
                        # Déjà disponible mais available_at provient de notre polling — Seer est plus précis
                        existing.available_at = seer_updated_at
                        changed = True
                    if changed:
                        total_upserted += 1
                else:
                    db.add(
                        MediaRequest(
                            plex_user_id=user.plex_user_id,
                            plex_user=user.display_name or user.plex_user_id,
                            title=req["title"],
                            media_type=req["media_type"],
                            tmdb_id=req["tmdb_id"],
                            tvdb_id=req["tvdb_id"],
                            imdb_id=req["imdb_id"],
                            arr_id=req["seer_request_id"],
                            poster_url=req.get("poster_url"),
                            source="seer",
                            status=req["status"],
                            requested_at=seer_requested_at,
                            available_at=seer_updated_at if is_available else None,
                        )
                    )
                    total_upserted += 1

            db.commit()

        logger.info(f"Seer sync requests: {total_upserted} demande(s) importée(s)/mise(s) à jour")
    except Exception:
        logger.exception("Seer sync requests échouée")
    finally:
        db.close()


async def _seer_full_sync():
    """Job planifié : sync utilisateurs puis demandes Seer."""
    await sync_seer_users()
    await sync_seer_requests()


