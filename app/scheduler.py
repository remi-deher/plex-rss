"""
Scheduler APScheduler gérant les deux tâches périodiques :

- poll_watchlists (défaut : toutes les 5 min)
    Lit les watchlists Plex et envoie les nouvelles demandes à Sonarr/Radarr.
    Retente également les demandes en statut `pending` ou `failed`.

- check_arr_statuses (toutes les 15 min)
    Interroge Sonarr/Radarr pour détecter les médias devenus disponibles.
    Cette approche par polling (sans webhook) est identique à celle d'Overseerr.
    Fallback : si arr_id est absent, recherche par tvdb_id/imdb_id/tmdb_id.
"""

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from . import metrics as app_metrics
from .database import SessionLocal
from .models import MediaRequest, NotificationLog, PlexUser, RequestStatus, Settings
from .notification_queue import enqueue as enqueue_notification
from .services.radarr import add_movie, is_movie_available
from .services.seer import _headers as _seer_headers
from .services.seer import _resolve_tmdb_id as _seer_resolve_tmdb_id
from .services.seer import get_user_requests as seer_get_user_requests
from .services.seer import get_users as seer_get_users
from .services.seer import is_request_available as seer_available
from .services.seer import request_media as seer_request
from .services.sonarr import add_series, is_series_available
from .services.watchlist import fetch_watchlist

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


# ---------------------------------------------------------------------------
# Cycle de vie du scheduler
# ---------------------------------------------------------------------------


def _purge_notification_logs():
    """Supprime les logs de notifications plus anciens que la rétention configurée."""
    db: Session = SessionLocal()
    try:
        settings = db.query(Settings).first()
        days = settings.notification_log_retention_days if settings else None
        if not days:
            return
        cutoff = datetime.now().replace(tzinfo=None) - timedelta(days=days)
        deleted = db.query(NotificationLog).filter(NotificationLog.sent_at < cutoff).delete()
        if deleted:
            db.commit()
            logger.info(f"Purge logs notifications : {deleted} entrées supprimées (>{days}j)")
    except Exception as e:
        logger.error(f"Erreur purge logs notifications : {e}")
    finally:
        db.close()


def start_scheduler(poll_minutes: int = 5):
    """Enregistre les jobs et démarre le scheduler."""
    scheduler.add_job(poll_watchlists, "interval", minutes=poll_minutes, id="watchlist_poll", replace_existing=True)
    scheduler.add_job(check_arr_statuses, "interval", minutes=15, id="arr_status_check", replace_existing=True)
    scheduler.add_job(_seer_full_sync, "interval", minutes=60, id="seer_sync", replace_existing=True)
    scheduler.add_job(_purge_notification_logs, "cron", hour=3, minute=0, id="notif_log_purge", replace_existing=True)
    scheduler.start()
    logger.info(f"Scheduler started (poll every {poll_minutes}m)")


def update_poll_interval(minutes: int):
    """Replanifie le job de polling sans redémarrer le scheduler."""
    scheduler.reschedule_job("watchlist_poll", trigger=IntervalTrigger(minutes=minutes))
    logger.info(f"Poll interval updated to {minutes}m")


# ---------------------------------------------------------------------------
# Fonctions utilitaires partagées
# ---------------------------------------------------------------------------


async def _seer_full_sync():
    """Job planifié : sync utilisateurs puis demandes Seer."""
    await sync_seer_users()
    await sync_seer_requests()


async def sync_seer_users():
    """Synchronise seer_user_id et seer_active sur chaque PlexUser.

    Stratégie d'automatch par ordre de priorité (s'arrête au premier succès) :
    1. Email exact (plex_email == seer.email)
    2. plexUsername Seer == display_name Plex (case-insensitive)

    Met à jour seer_user_id, seer_active. Ne touche pas aux liaisons
    déjà faites manuellement sauf si l'email correspond (plus fiable).
    """
    db: Session = SessionLocal()
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

            if info["request_count"] == 0:
                continue
            email = next((e for e in seer_users if seer_users[e]["id"] == info["id"]), None)
            new_user = PlexUser(
                plex_user_id=synthetic_id,
                display_name=info["display_name"],
                plex_email=email,
                seer_user_id=info["id"],
                seer_active=True,
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


def _clean_title(title: str) -> str:
    """Supprime les suffixes d'année entre parenthèses ajoutés par Plex ex: 'INVINCIBLE (2021)' → 'INVINCIBLE'."""
    return re.sub(r"\s*\(\d{4}\)\s*$", "", title).strip()


def _parse_seer_dt(iso: str | None) -> datetime | None:
    """Convertit une chaîne ISO 8601 Seer en datetime UTC naïf."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return None


async def sync_seer_requests():
    """Importe toutes les demandes Seer dans MediaRequest.

    Pour chaque PlexUser avec un seer_user_id connu, récupère l'historique
    complet des demandes Seer et upserte dans MediaRequest (source='seer').
    Statut : available si media.status 4 ou 5, sinon sent_to_arr.
    Cela permet d'outrepasser la limite des 50 items du flux RSS.
    """
    db: Session = SessionLocal()
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
                existing = _find_global_request(db, req["media_type"], req["tmdb_id"], req["title"], req.get("tvdb_id"))

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
                        existing.available_at = seer_updated_at or datetime.now(timezone.utc).replace(tzinfo=None)
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


async def sync_users_from_feed(items: list[dict], db: Session):
    """Crée automatiquement un PlexUser pour chaque plex_user_id inconnu trouvé dans le flux."""
    known_ids = {u.plex_user_id for u in db.query(PlexUser).all()}
    new_ids = {item["plex_user_id"] for item in items if item.get("plex_user_id")} - known_ids
    for uid in new_ids:
        db.add(PlexUser(plex_user_id=uid, display_name=None, enabled=True))
        logger.info(f"Auto-discovered Plex user: {uid}")
    if new_ids:
        db.commit()


async def _submit_to_arr(
    settings: Settings, item: dict, user_obj: PlexUser | None = None
) -> tuple[int | None, bool, str | None]:
    """Envoie un média à Seer (si activé) ou Sonarr/Radarr directement.

    Si l'utilisateur est actif sur Seer (seer_active=True), la demande
    est ignorée : il la gère lui-même depuis Seer, pas besoin de doublon.

    Returns:
        (arr_id, already_existed, arr_slug)
    """
    if user_obj and user_obj.seer_active is True:
        logger.debug(f"Skip '{item['title']}' — utilisateur actif sur Seer")
        return None, True, None

    if settings.seer_enabled and settings.seer_url and settings.seer_api_key:
        t0 = time.monotonic()
        result = await seer_request(settings.seer_url, settings.seer_api_key, item)
        app_metrics.record_seer_latency((time.monotonic() - t0) * 1000)
        app_metrics.record_arr_submission(result[0] is not None or result[1])
        return result

    if item["media_type"] == "show" and settings.sonarr_enabled and settings.sonarr_url:
        t0 = time.monotonic()
        result = await add_series(
            settings.sonarr_url,
            settings.sonarr_api_key,
            settings.sonarr_quality_profile_id,
            settings.sonarr_root_folder,
            item,
        )
        app_metrics.record_sonarr_latency((time.monotonic() - t0) * 1000)
        app_metrics.record_arr_submission(result[0] is not None or result[1])
        return result

    if item["media_type"] == "movie" and settings.radarr_enabled and settings.radarr_url:
        t0 = time.monotonic()
        result = await add_movie(
            settings.radarr_url,
            settings.radarr_api_key,
            settings.radarr_quality_profile_id,
            settings.radarr_root_folder,
            item,
            minimum_availability=settings.radarr_minimum_availability or "released",
        )
        app_metrics.record_radarr_latency((time.monotonic() - t0) * 1000)
        app_metrics.record_arr_submission(result[0] is not None or result[1])
        return result

    return None, False, None


def _find_global_request(
    db,
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
        found = (
            db.query(MediaRequest)
            .filter(
                MediaRequest.media_type == media_type,
                MediaRequest.tmdb_id == tmdb_id,
            )
            .first()
        )
        if found:
            return found
    if tvdb_id:
        found = (
            db.query(MediaRequest)
            .filter(
                MediaRequest.media_type == media_type,
                MediaRequest.tvdb_id == tvdb_id,
            )
            .first()
        )
        if found:
            return found
    if title:
        return (
            db.query(MediaRequest)
            .filter(
                MediaRequest.media_type == media_type,
                MediaRequest.title == title,
            )
            .first()
        )
    return None


def _add_co_requester(req: MediaRequest, plex_user_id: str, display_name: str) -> bool:
    """Ajoute un co-demandeur à une demande existante. Retourne True si ajouté."""
    extras: list[dict] = json.loads(req.extra_requesters or "[]")
    if req.plex_user_id == plex_user_id:
        return False
    if any(e["plex_user_id"] == plex_user_id for e in extras):
        return False
    extras.append({"plex_user_id": plex_user_id, "display_name": display_name})
    req.extra_requesters = json.dumps(extras, ensure_ascii=False)
    return True


def _get_recipients(user_obj, settings: Settings, event: str = "request") -> list[str]:
    """Résout la liste des destinataires email pour un utilisateur.

    - Si l'utilisateur est inactif (enabled=False) : aucune notification.
    - Adresse(s) de l'utilisateur (séparées par virgules), ou smtp_from par défaut.
    - Si notify_admin=True sur l'utilisateur, ajoute admin_notification_email en copie.
    - Respecte les flags notify_on_request / notify_on_available par utilisateur.
    """
    if user_obj and not user_obj.enabled:
        return []

    # Vérification des flags par utilisateur
    if user_obj:
        if event == "request" and user_obj.notify_on_request is False:
            return []
        if event == "available" and user_obj.notify_on_available is False:
            return []

    raw = (user_obj.notification_email if user_obj else None) or settings.smtp_from or ""
    recipients = [e.strip() for e in raw.split(",") if e.strip()]

    admin_email = (settings.admin_notification_email or "").strip()
    if admin_email and user_obj and getattr(user_obj, "notify_admin", True):
        for addr in [e.strip() for e in admin_email.split(",") if e.strip()]:
            if addr not in recipients:
                recipients.append(addr)

    return recipients


def _notify_request(settings: Settings, req: MediaRequest, db: Session):
    """Empile la notification de nouvelle demande dans la queue."""
    if not req.request_mail_sent:
        user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
        recipients = _get_recipients(user_obj, settings, "request") if settings.email_on_request else []
        enqueue_notification("request", req.id, recipients)


def _notify_failure(settings: Settings, req: MediaRequest, db: Session):
    """Empile la notification d'échec dans la queue."""
    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    recipients = _get_recipients(user_obj, settings, "request") if settings.email_on_request else []
    arr_name = "Sonarr" if req.media_type == "show" else "Radarr"
    enqueue_notification(
        "failed", req.id, recipients, f"Impossible de transmettre a {arr_name}. Verifiez la configuration."
    )


def _notify_available(settings: Settings, req: MediaRequest, db: Session):
    """Empile la notification de disponibilité dans la queue."""
    if not req.available_mail_sent:
        user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
        recipients = _get_recipients(user_obj, settings, "available") if settings.email_on_available else []
        enqueue_notification("available", req.id, recipients)


# ---------------------------------------------------------------------------
# Jobs planifiés
# ---------------------------------------------------------------------------


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
    """
    logger.info("Polling watchlists...")
    _poll_start = time.monotonic()
    db: Session = SessionLocal()
    _poll_error = False
    try:
        settings = db.query(Settings).first()
        if not settings:
            return

        items = await fetch_watchlist(settings)
        if not items:
            logger.info("No watchlist items returned")
            return

        await sync_users_from_feed(items, db)

        all_users = db.query(PlexUser).all()
        users_map = {u.plex_user_id: u for u in all_users}
        enabled_ids = {u.plex_user_id for u in all_users if u.enabled}
        has_filter = len(all_users) > 0

        new_count = 0
        for item in items:
            uid = item.get("plex_user_id") or item.get("plex_user", "unknown")

            # Ignorer les utilisateurs désactivés si la table utilisateurs est renseignée
            if has_filter and uid not in enabled_ids:
                continue

            user_obj = users_map.get(uid)
            display_name = (user_obj.display_name if user_obj else None) or uid

            # Pour utilisateurs hybrides sans tmdb_id NI tvdb_id dans le flux RSS :
            # les séries sont maintenant déduplicées par tvdb_id → appel Seer utile uniquement
            # pour les films sans identifiant (imdb seul, cas rare).
            if (
                not item.get("tmdb_id")
                and not item.get("tvdb_id")
                and user_obj
                and user_obj.seer_user_id
                and user_obj.seer_active
            ):
                if settings and settings.seer_url and settings.seer_api_key:
                    base = settings.seer_url.rstrip("/")
                    headers = _seer_headers(settings.seer_api_key)
                    try:
                        search_item = {**item, "title": _clean_title(item["title"])}
                        resolved = await _seer_resolve_tmdb_id(base, headers, search_item)
                        if resolved:
                            item = {**item, "tmdb_id": resolved}
                            logger.debug(f"tmdb_id résolu via Seer pour '{item['title']}': {resolved}")
                    except Exception:
                        pass

            # Dédup global : même média déjà demandé par un autre utilisateur ?
            global_req = _find_global_request(
                db, item["media_type"], item.get("tmdb_id"), item["title"], item.get("tvdb_id")
            )
            if global_req and global_req.plex_user_id != uid:
                added = _add_co_requester(global_req, uid, display_name)
                if added:
                    db.commit()
                    logger.info(f"Co-demandeur ajouté : {display_name} → '{global_req.title}'")
                continue

            existing = global_req if global_req else None

            # Fallback : même utilisateur, même titre — ancienne demande sans identifiant
            if not existing and item.get("title"):
                existing = (
                    db.query(MediaRequest)
                    .filter(
                        MediaRequest.plex_user_id == uid,
                        MediaRequest.media_type == item["media_type"],
                        MediaRequest.title == item["title"],
                        MediaRequest.tmdb_id.is_(None),
                    )
                    .first()
                )
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
                    continue
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
                db.add(req)
                db.flush()

            # Routage intelligent : si l'utilisateur est Hybride (RSS + Seer actif),
            # vérifier si Seer a déjà traité cette demande.
            # Si oui → skip la soumission arr (Seer l'a déjà faite).
            # Si non → RSS sert de fallback et soumet lui-même.
            if user_obj and user_obj.seer_user_id and user_obj.seer_active:
                tmdb_id = item.get("tmdb_id")
                seer_id_filter = (MediaRequest.tmdb_id == tmdb_id) if tmdb_id else (MediaRequest.title == item["title"])
                seer_handled = (
                    db.query(MediaRequest)
                    .filter(
                        MediaRequest.plex_user_id == uid,
                        MediaRequest.source == "seer",
                        seer_id_filter,
                    )
                    .first()
                )
                if seer_handled:
                    logger.debug(f"Routage Hybride : '{item['title']}' déjà géré par Seer pour {uid}, RSS skip")
                    db.commit()
                    continue

            already_existed = False
            try:
                arr_id, already_existed, arr_slug = await _submit_to_arr(settings, item, user_obj)
                req.status = RequestStatus.sent_to_arr
                req.arr_id = arr_id
                req.arr_slug = arr_slug
            except Exception as e:
                logger.error(f"Failed to send '{item['title']}' to arr: {e}")
                req.status = RequestStatus.failed

            db.commit()
            new_count += 1

            if already_existed:
                # Média déjà dans *arr : pas de notification (évite le spam au redémarrage)
                logger.info(f"'{item['title']}' already in arr — skipping notifications")
            elif req.status == RequestStatus.sent_to_arr:
                _notify_request(settings, req, db)
            elif req.status == RequestStatus.failed:
                _notify_failure(settings, req, db)

        logger.info(f"Poll complete: {new_count} requests processed")

    except Exception as e:
        logger.error(f"Poll error: {e}")
        _poll_error = True
    finally:
        app_metrics.record_poll((time.monotonic() - _poll_start) * 1000, error=_poll_error)
        db.close()


async def check_arr_statuses():
    """Vérifie si des demandes `sent_to_arr` sont désormais disponibles dans *arr.

    Stratégie de lookup (sans webhook) :
    1. Si arr_id connu → GET /api/v3/series/{id} ou /api/v3/movie/{id}
    2. Sinon → scan de la liste complète filtré par tvdb_id/tmdb_id/imdb_id
       (cas des demandes créées avant la configuration de Sonarr/Radarr)

    Disponibilité :
    - Sonarr : statistics.episodeFileCount > 0
    - Radarr : hasFile == true
    """
    logger.info("Checking arr statuses...")
    db: Session = SessionLocal()
    try:
        settings = db.query(Settings).first()
        if not settings:
            return

        candidates = (
            db.query(MediaRequest)
            .filter(
                MediaRequest.status == RequestStatus.sent_to_arr,
            )
            .all()
        )

        if not candidates:
            return

        logger.info(f"Checking {len(candidates)} sent_to_arr requests...")

        for req in candidates:
            available = False
            new_arr_id = None
            new_slug = None
            try:
                if settings.seer_enabled and settings.seer_url:
                    available, new_arr_id, new_slug = await seer_available(
                        settings.seer_url,
                        settings.seer_api_key,
                        seer_request_id=req.arr_id,
                    )
                elif req.media_type == "show" and settings.sonarr_url and settings.sonarr_api_key:
                    available, new_arr_id, new_slug = await is_series_available(
                        settings.sonarr_url,
                        settings.sonarr_api_key,
                        arr_id=req.arr_id,
                        tvdb_id=req.tvdb_id,
                    )
                elif req.media_type == "movie" and settings.radarr_url and settings.radarr_api_key:
                    available, new_arr_id, new_slug = await is_movie_available(
                        settings.radarr_url,
                        settings.radarr_api_key,
                        arr_id=req.arr_id,
                        tmdb_id=req.tmdb_id,
                        imdb_id=req.imdb_id,
                    )
            except Exception as e:
                logger.warning(f"Status check error for '{req.title}': {e}")
                continue

            # Mettre à jour arr_id / arr_slug si on les découvre maintenant
            if new_arr_id and not req.arr_id:
                req.arr_id = new_arr_id
            if new_slug and not req.arr_slug:
                req.arr_slug = new_slug

            if available:
                req.status = RequestStatus.available
                req.available_at = datetime.now(timezone.utc)
                db.commit()
                logger.info(f"'{req.title}' is now available")
                _notify_available(settings, req, db)
            elif new_arr_id or new_slug:
                db.commit()

        logger.info("Arr status check complete")

    except Exception as e:
        logger.error(f"check_arr_statuses error: {e}")
    finally:
        db.close()
