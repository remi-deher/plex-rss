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
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from . import metrics as app_metrics
from .database import SessionLocal
from .models import (
    ArrInstance,
    DownloadClient,
    MediaRequest,
    NotificationLog,
    PlexUser,
    PollHistory,
    RequestStatus,
    Settings,
)
from .notification_queue import enqueue as enqueue_notification
from .services import prowlarr
from .services.download_clients import add_torrent_to_client, delete_torrent, get_torrent_status
from .services.radarr import add_movie, get_all_movies, is_movie_available, lookup_movie, resolve_tmdb_id
from .services.seer import _headers as _seer_headers
from .services.seer import _resolve_tmdb_id as _seer_resolve_tmdb_id
from .services.seer import get_user_requests as seer_get_user_requests
from .services.seer import get_users as seer_get_users
from .services.seer import is_request_available as seer_available
from .services.seer import request_media as seer_request
from .services.sonarr import add_series, get_all_series, is_series_available, lookup_series
from .services.watchlist import fetch_watchlist
from .utils import db_session, parse_email_list

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


# ---------------------------------------------------------------------------
# Cycle de vie du scheduler
# ---------------------------------------------------------------------------


async def _send_digest():
    """Envoie le récapitulatif quotidien aux utilisateurs ayant notify_digest=True."""
    from .services.email_service import _send as smtp_send

    try:
        with db_session(SessionLocal) as db:
            settings = db.query(Settings).first()
            if not settings or not settings.digest_enabled:
                return
            if not all([settings.smtp_host, settings.smtp_user, settings.smtp_password, settings.smtp_from]):
                logger.warning("Digest : SMTP non configuré, skip")
                return

            cutoff = datetime.now() - timedelta(hours=24)
            recent = (
                db.query(MediaRequest)
                .filter(MediaRequest.requested_at >= cutoff)
                .order_by(MediaRequest.requested_at.desc())
                .all()
            )
            if not recent:
                logger.info("Digest : aucune demande dans les 24h, skip")
                return

            users = (
                db.query(PlexUser)
                .filter(
                    PlexUser.enabled.is_(True),
                    PlexUser.notify_digest.is_(True),
                )
                .all()
            )
            if not users:
                return

            count = len(recent)
            plural = "s" if count > 1 else ""

            rows = "".join(
                f"<tr>"
                f"<td style='padding:6px 12px;border-bottom:1px solid #333'>{r.title or '—'}"
                f"{'<span style="color:#aaa;font-size:12px"> (' + str(r.year) + ')</span>' if r.year else ''}</td>"
                f"<td style='padding:6px 12px;border-bottom:1px solid #333;color:#aaa'>{'Série' if r.media_type == 'show' else 'Film'}</td>"
                f"<td style='padding:6px 12px;border-bottom:1px solid #333;color:#aaa'>{r.plex_user or r.plex_user_id}</td>"
                f"<td style='padding:6px 12px;border-bottom:1px solid #333'>"
                f"<span style='color:{'#1db954' if r.status == 'available' else '#e5a00d' if r.status == 'sent_to_arr' else '#888'}'>"
                f"{'Disponible' if r.status == 'available' else 'Envoyé' if r.status == 'sent_to_arr' else r.status}"
                f"</span></td>"
                f"</tr>"
                for r in recent
            )
            html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#141414;font-family:Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;margin:auto">
  <tr><td style="background:#e5a00d;padding:20px 24px">
    <h1 style="color:#fff;margin:0;font-size:20px">📋 Récap quotidien Plex</h1>
    <p style="color:#fff9;margin:4px 0 0;font-size:13px">{count} demande{plural} dans les dernières 24h</p>
  </td></tr>
  <tr><td style="background:#1f1f1f;padding:20px 24px">
    <table width="100%" cellpadding="0" cellspacing="0">
      <thead><tr>
        <th style="text-align:left;padding:6px 12px;color:#888;font-weight:normal;border-bottom:1px solid #444">Titre</th>
        <th style="text-align:left;padding:6px 12px;color:#888;font-weight:normal;border-bottom:1px solid #444">Type</th>
        <th style="text-align:left;padding:6px 12px;color:#888;font-weight:normal;border-bottom:1px solid #444">Demandé par</th>
        <th style="text-align:left;padding:6px 12px;color:#888;font-weight:normal;border-bottom:1px solid #444">Statut</th>
      </tr></thead>
      <tbody style="color:#fff">{rows}</tbody>
    </table>
  </td></tr>
  <tr><td style="background:#111;padding:12px 24px">
    <p style="color:#555;font-size:11px;margin:0">Plex RSS Monitor — récapitulatif automatique quotidien</p>
  </td></tr>
</table>
</body></html>"""

            subject = f"[Plex] Récap du {datetime.now().strftime('%d/%m/%Y')} — {count} demande{plural}"
            for user in users:
                recipient = user.notification_email or user.plex_email
                if not recipient:
                    continue
                try:
                    await smtp_send(settings, recipient, subject, html)
                    logger.info(f"Digest envoyé à {recipient}")
                except Exception as e:
                    logger.error(f"Digest échec pour {recipient}: {e}")
    except Exception as e:
        logger.error(f"Erreur job digest : {e}")


def _purge_notification_logs():
    """Supprime les logs de notifications et l'historique de poll plus anciens que la rétention configurée."""
    try:
        with db_session(SessionLocal) as db:
            settings = db.query(Settings).first()
            if not settings:
                return
            days = settings.notification_log_retention_days
            if days:
                cutoff = datetime.now() - timedelta(days=days)
                deleted = db.query(NotificationLog).filter(NotificationLog.sent_at < cutoff).delete()
                if deleted:
                    db.commit()
                    logger.info(f"Purge logs notifications : {deleted} entrées supprimées (>{days}j)")

            poll_days = settings.poll_history_retention_days
            if poll_days:
                poll_cutoff = datetime.now() - timedelta(days=poll_days)
                deleted_polls = db.query(PollHistory).filter(PollHistory.started_at < poll_cutoff).delete()
                if deleted_polls:
                    db.commit()
                    logger.info(f"Purge historique poll : {deleted_polls} entrées supprimées (>{poll_days}j)")
    except Exception as e:
        logger.error(f"Erreur purge logs / historique poll : {e}")


def start_scheduler(poll_minutes: int = 5):
    """Enregistre les jobs et démarre le scheduler."""
    with db_session(SessionLocal) as db:
        settings = db.query(Settings).first()
        digest_hour = settings.digest_hour if settings and settings.digest_enabled else None

    scheduler.add_job(poll_watchlists, "interval", minutes=poll_minutes, id="watchlist_poll", replace_existing=True)
    scheduler.add_job(check_arr_statuses, "interval", minutes=15, id="arr_status_check", replace_existing=True)
    scheduler.add_job(check_torrent_statuses, "interval", minutes=2, id="torrent_status_check", replace_existing=True)
    scheduler.add_job(_seer_full_sync, "interval", minutes=60, id="seer_sync", replace_existing=True)
    scheduler.add_job(_purge_notification_logs, "cron", hour=3, minute=0, id="notif_log_purge", replace_existing=True)
    if digest_hour is not None:
        scheduler.add_job(_send_digest, "cron", hour=digest_hour, minute=0, id="digest", replace_existing=True)
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

    Tous les comptes Seer sans équivalent RSS sont importés (source='seer'),
    même sans demande (seer_active=False dans ce cas) — un compte Plex visible
    dans Seer mais jamais utilisé doit pouvoir apparaître dans l'app.
    """
    db = SessionLocal()
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
    db = SessionLocal()
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
    settings: Settings, item: dict, user_obj: PlexUser | None = None, db: Session | None = None
) -> tuple[int | None, bool, str | None]:
    """Envoie un média à Seer (si activé) ou Sonarr/Radarr/Prowlarr directement.

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

    ctx = db_session(SessionLocal) if db is None else nullcontext(db)
    with ctx as active_db:
        # Resolve ArrInstance
        instance = None
        if user_obj:
            instance_id = user_obj.sonarr_instance_id if item["media_type"] == "show" else user_obj.radarr_instance_id
            if instance_id:
                instance = (
                    active_db.query(ArrInstance).filter(ArrInstance.id == instance_id, ArrInstance.enabled).first()
                )

        if not instance:
            target_arr_type = "sonarr" if item["media_type"] == "show" else "radarr"
            instance = (
                active_db.query(ArrInstance)
                .filter(ArrInstance.arr_type == target_arr_type, ArrInstance.enabled, ArrInstance.is_default)
                .first()
            )

        if not instance or instance.arr_type not in ("sonarr", "radarr"):
            info_hash, already_existed, arr_slug, client_id = await _submit_to_torrent(active_db, settings, item)
            if info_hash:
                item["_torrent_hash"] = info_hash
                item["_download_client_id"] = client_id
                return None, already_existed, arr_slug
            logger.warning(
                "No enabled Sonarr/Radarr instance found for submission and Torrent automation did not succeed"
            )
            return None, False, None

        item["_arr_instance_id"] = instance.id

        if instance.arr_type == "prowlarr":
            indexer_ids = None
            if instance.indexer_ids:
                try:
                    indexer_ids = json.loads(instance.indexer_ids)
                except Exception:
                    pass
            results = await prowlarr.search(
                instance.url, instance.api_key, item["title"], item["media_type"], indexer_ids
            )
            if results:
                return None, False, f"prowlarr:{len(results)}"
            raise Exception("No search results found in Prowlarr")

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
            now = datetime.now(timezone.utc)
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
    recipients = parse_email_list(raw)

    admin_email = (settings.admin_notification_email or "").strip()
    if admin_email and user_obj and getattr(user_obj, "notify_admin", True):
        for addr in parse_email_list(admin_email):
            if addr not in recipients:
                recipients.append(addr)

    return recipients


def _notify(event: str, settings: Settings, req: MediaRequest, db: Session, reason: str = "", force: bool = False):
    """Empile une notification dans la queue après résolution des destinataires.

    force=True ignore les flags *_mail_sent (renvoi manuel demandé par l'utilisateur).
    """
    if not force:
        if event == "request" and req.request_mail_sent:
            return
        if event == "available" and req.available_mail_sent:
            return
    email_flag = settings.email_on_available if event == "available" else settings.email_on_request
    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    recipients = _get_recipients(user_obj, settings, event) if email_flag else []
    enqueue_notification(event, req.id, recipients, reason)


# ---------------------------------------------------------------------------
# Jobs planifiés
# ---------------------------------------------------------------------------


def _check_and_seed_instances_from_settings(db: Session, settings: Settings):
    """Fallback / compatibilité pour les tests unitaires et les premières exécutions."""
    if db.query(ArrInstance).count() == 0 and settings:
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
        db.commit()


async def _submit_to_torrent(
    db: Session, settings: Settings, item: dict
) -> tuple[str | None, bool, str | None, int | None]:
    """Recherche un média sur Prowlarr et l'envoie au client torrent par défaut si Sonarr/Radarr sont inactifs."""
    prowlarr_inst = db.query(ArrInstance).filter(ArrInstance.arr_type == "prowlarr", ArrInstance.enabled).first()
    if not prowlarr_inst:
        logger.warning("Torrent automation: Aucune instance Prowlarr active trouvée")
        return None, False, None, None

    client = db.query(DownloadClient).filter(DownloadClient.enabled, DownloadClient.is_default).first()
    if not client:
        client = db.query(DownloadClient).filter(DownloadClient.enabled).first()
    if not client:
        logger.warning("Torrent automation: Aucun client de téléchargement actif trouvé")
        return None, False, None, None

    query = item["title"]
    if item.get("year"):
        query = f"{query} {item['year']}"

    try:
        results = await prowlarr.search(
            url=prowlarr_inst.url,
            api_key=prowlarr_inst.api_key,
            query=query,
            media_type=item["media_type"],
            indexer_ids=None,
        )
    except Exception as e:
        logger.error(f"Torrent automation: Erreur lors de la recherche Prowlarr : {e}")
        return None, False, None, None

    if not results:
        logger.info(f"Torrent automation: Aucun résultat de recherche pour '{query}'")
        return None, False, None, None

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

    if not filtered_results:
        logger.info(f"Torrent automation: Tous les résultats pour '{query}' ont été filtrés")
        return None, False, None, None

    filtered_results.sort(key=lambda x: x.get("seeders", 0), reverse=True)
    best_release = filtered_results[0]
    download_url = best_release.get("downloadUrl") or best_release.get("magnetUrl")

    if not download_url:
        return None, False, None, None

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
        logger.info(
            f"Torrent automation: Envoyé avec succès au client torrent: {best_release.get('title')} (hash: {info_hash})"
        )
        return info_hash, False, "torrent", client.id
    else:
        logger.error(f"Torrent automation: Erreur lors de l'envoi du torrent: {msg}")
        return None, False, None, None


async def check_torrent_statuses():
    """Tâche périodique de suivi et nettoyage des torrents actifs."""
    logger.info("Checking torrent statuses...")
    db = SessionLocal()
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
                    req.available_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    db.commit()
                    _notify("available", settings, req, db)
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
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    items_processed = 0
    new_requests = 0
    errors_count = 0
    error_detail = None
    db = SessionLocal()
    _poll_error = False
    try:
        settings = db.query(Settings).first()
        if not settings:
            return

        _check_and_seed_instances_from_settings(db, settings)

        items = await fetch_watchlist(settings)
        if not items:
            logger.info("No watchlist items returned")
            return

        items_processed = len(items)
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
            display_name = ((user_obj.custom_name or user_obj.display_name) if user_obj else None) or uid

            # Normalisation sur TMDB avant déduplication : le flux RSS n'apporte qu'un
            # IMDB ID (films) ou un TVDB ID (séries). Sans TMDB, la dédup retombe sur le
            # titre — qui diffère selon la langue → doublons RSS ↔ Seer. On résout donc
            # le TMDB ID pour tous les utilisateurs (pas seulement les hybrides).
            item = await _ensure_tmdb_id(item, settings, user_obj)

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
                errors_count += 1

            db.commit()
            new_count += 1

            if already_existed:
                # Média déjà dans *arr : pas de notification (évite le spam au redémarrage)
                logger.info(f"'{item['title']}' already in arr — skipping notifications")
            elif req.status == RequestStatus.sent_to_arr:
                _notify("request", settings, req, db)
            elif req.status == RequestStatus.failed:
                arr_name = "Sonarr" if req.media_type == "show" else "Radarr"
                _notify(
                    "failed", settings, req, db, f"Impossible de transmettre a {arr_name}. Verifiez la configuration."
                )

        new_requests = new_count
        logger.info(f"Poll complete: {new_count} requests processed")

    except Exception as e:
        logger.error(f"Poll error: {e}")
        _poll_error = True
        error_detail = str(e)
        errors_count += 1
    finally:
        app_metrics.record_poll((time.monotonic() - _poll_start) * 1000, error=_poll_error)
        # Persist PollHistory
        duration_ms = int((time.monotonic() - _poll_start) * 1000)
        poll_db = SessionLocal()
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
            poll_db.commit()
        except Exception as pe:
            logger.error(f"Failed to persist watchlist PollHistory: {pe}")
        finally:
            if poll_db is not db:
                poll_db.close()
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

    En mode hybride (Seer + Sonarr/Radarr), Seer peut ne pas savoir qu'un média
    est disponible si l'import a été fait sans qu'il le détecte. Si Seer répond
    "non disponible", on retente directement Sonarr/Radarr en fallback (lookup
    par tvdb_id/tmdb_id/imdb_id uniquement, car req.arr_id désigne alors l'ID
    Seer et non l'ID Sonarr/Radarr).
    """
    logger.info("Checking arr statuses...")
    _check_start = time.monotonic()
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    items_processed = 0
    newly_available = 0
    errors_count = 0
    error_detail = None
    db = SessionLocal()
    try:
        settings = db.query(Settings).first()
        if not settings:
            return

        _check_and_seed_instances_from_settings(db, settings)

        candidates = (
            db.query(MediaRequest)
            .filter(
                MediaRequest.status == RequestStatus.sent_to_arr,
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
            if inst.arr_type == "sonarr":
                try:
                    series_list = await get_all_series(inst.url, inst.api_key)
                except Exception as e:
                    logger.warning(f"Sonarr series prefetch failed for '{inst.name}': {e}")
                    errors_count += 1
            elif inst.arr_type == "radarr":
                try:
                    movies_list = await get_all_movies(inst.url, inst.api_key)
                except Exception as e:
                    logger.warning(f"Radarr movies prefetch failed for '{inst.name}': {e}")
                    errors_count += 1

            for req in inst_candidates:
                available = False
                new_arr_id = None
                new_slug = None
                seer_checked = False
                try:
                    if settings.seer_enabled and settings.seer_url:
                        seer_checked = True
                        available, new_arr_id, new_slug = await seer_available(
                            settings.seer_url,
                            settings.seer_api_key,
                            seer_request_id=req.arr_id,
                        )
                    elif req.media_type == "show" and inst.arr_type == "sonarr":
                        available, new_arr_id, new_slug = await is_series_available(
                            inst.url,
                            inst.api_key,
                            arr_id=req.arr_id,
                            tvdb_id=req.tvdb_id,
                            series_list=series_list,
                        )
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
                            available, arr_new_id, arr_new_slug = await is_series_available(
                                inst.url,
                                inst.api_key,
                                tvdb_id=req.tvdb_id,
                                series_list=series_list,
                            )
                            new_arr_id = new_arr_id or arr_new_id
                            new_slug = new_slug or arr_new_slug
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
                    continue

                # Mettre à jour arr_id / arr_slug / arr_instance_id si on les découvre maintenant
                if new_arr_id and not req.arr_id:
                    req.arr_id = new_arr_id
                if new_slug and not req.arr_slug:
                    req.arr_slug = new_slug
                if req.arr_instance_id is None:
                    req.arr_instance_id = inst.id

                if available:
                    req.status = RequestStatus.available
                    req.available_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    req.next_release_at = None
                    req.next_release_label = None
                    db.commit()
                    newly_available += 1
                    logger.info(f"'{req.title}' is now available")
                    _notify("available", settings, req, db)
                else:
                    await _refresh_next_release(
                        req, settings, series_list=series_list, movies_list=movies_list, inst=inst
                    )
                    db.commit()

        logger.info("Arr status check complete")

    except Exception as e:
        logger.error(f"check_arr_statuses error: {e}")
        error_detail = str(e)
        errors_count += 1
    finally:
        # Persist PollHistory
        duration_ms = int((time.monotonic() - _check_start) * 1000)
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
