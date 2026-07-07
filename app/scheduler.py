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

import asyncio
import json
import logging
import re
import time
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from . import metrics as app_metrics
from .database import SessionLocal
from .models import (
    ArrInstance,
    DownloadClient,
    LibraryItem,
    MediaRequest,
    NotificationLog,
    NotificationMilestone,
    PlexUser,
    PollHistory,
    RequestStatus,
    Settings,
    VfEpisodeStatus,
)
from .notification_queue import enqueue as enqueue_notification
from .services import prowlarr, vff
from .services.download_clients import add_torrent_to_client, delete_torrent, get_torrent_status
from .services.radarr import add_movie, get_all_movies, is_movie_available, lookup_movie, resolve_tmdb_id, search_movie
from .services.seer import _headers as _seer_headers
from .services.seer import _resolve_tmdb_id as _seer_resolve_tmdb_id
from .services.seer import get_user_requests as seer_get_user_requests
from .services.seer import get_users as seer_get_users
from .services.seer import is_request_available as seer_available
from .services.seer import request_media as seer_request
from .services.sonarr import (
    add_series,
    get_all_series,
    get_series_episode_stats,
    is_series_available,
    lookup_series,
    search_series,
)
from .services.watchlist import fetch_watchlist
from .utils import db_session, parse_email_list

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# État en mémoire du scan VFF (partagé)
vff_scan_state = {
    "status": "idle",  # "idle" | "running" | "failed"
    "started_at": None,
    "finished_at": None,
    "items_scanned": 0,
    "total_items": 0,
    "error": None
}

# État en mémoire de la synchronisation Plex (partagé)
plex_sync_state = {
    "status": "idle",  # "idle" | "running" | "failed"
    "started_at": None,
    "finished_at": None,
    "items_synced": 0,
    "total_items": 0,
    "error": None
}


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
    <p style="color:#555;font-size:11px;margin:0">Plexarr — récapitulatif automatique quotidien</p>
  </td></tr>
</table>
</body></html>"""

            subject = f"[Plexarr] Récap du {datetime.now().strftime('%d/%m/%Y')} — {count} demande{plural}"
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
        vff_interval = settings.vff_recheck_interval_minutes if settings and settings.vff_recheck_interval_minutes else 360

    scheduler.add_job(poll_watchlists, "interval", minutes=poll_minutes, id="watchlist_poll", replace_existing=True)
    scheduler.add_job(check_arr_statuses, "interval", minutes=15, id="arr_status_check", replace_existing=True)
    scheduler.add_job(check_torrent_statuses, "interval", minutes=2, id="torrent_status_check", replace_existing=True)
    scheduler.add_job(check_vf_statuses, "interval", minutes=vff_interval, id="vf_status_check", replace_existing=True)
    scheduler.add_job(_seer_full_sync, "interval", minutes=60, id="seer_sync", replace_existing=True)
    scheduler.add_job(_purge_notification_logs, "cron", hour=3, minute=0, id="notif_log_purge", replace_existing=True)
    scheduler.add_job(sync_plex_media, "interval", hours=24, id="plex_library_sync", replace_existing=True)
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

    if settings.seer_send_requests and settings.seer_url and settings.seer_api_key:
        t0 = time.monotonic()
        result = await seer_request(settings.seer_url, settings.seer_api_key, item)
        app_metrics.record_seer_latency((time.monotonic() - t0) * 1000)
        seer_ok = result[0] is not None or result[1]
        app_metrics.record_arr_submission(seer_ok)
        if seer_ok or not settings.seer_fallback_arr:
            return result
        logger.warning("Seer request failed, falling back to Sonarr/Radarr")

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


def _user_wants_vf(user_obj: PlexUser | None, vf_category: str | None) -> bool:
    """Indique si l'utilisateur souhaite les notifications VF pour ce type de média.

    Défauts : films et séries activés, animes désactivés (VO japonaise fréquente
    à la sortie → éviter les faux positifs, mais l'utilisateur peut l'activer).
    """
    if not user_obj or not user_obj.enabled:
        return False
    if vf_category == "movie":
        return user_obj.notify_vf_movie is not False
    if vf_category == "anime":
        return user_obj.notify_vf_anime is True
    return user_obj.notify_vf_series is not False


def _get_vf_recipients(user_obj: PlexUser | None, settings: Settings, vf_category: str | None) -> list[str]:
    """Résout les destinataires email d'une notification VF (respecte les flags par type)."""
    if not _user_wants_vf(user_obj, vf_category):
        return []
    raw = (user_obj.notification_email if user_obj else None) or settings.smtp_from or ""
    recipients = parse_email_list(raw)
    admin_email = (settings.admin_notification_email or "").strip()
    if admin_email and user_obj and getattr(user_obj, "notify_admin", True):
        for addr in parse_email_list(admin_email):
            if addr not in recipients:
                recipients.append(addr)
    return recipients


SERIES_NOTIFY_MODES = {
    "every_episode",
    "season_complete",
    "series_complete",
    "season_start_and_complete",
}


def _valid_series_notify_mode(value: str | None, default: str = "season_start_and_complete") -> str:
    return value if value in SERIES_NOTIFY_MODES else default


def _resolve_movie_notify(direction: str, settings: Settings, user_obj: PlexUser | None) -> bool:
    attr = "movie_vf_notify" if direction == "vf" else "movie_vo_notify"
    user_value = getattr(user_obj, attr, None) if user_obj else None
    if user_value is not None:
        return bool(user_value)
    return getattr(settings, attr, True) is not False


def _resolve_series_notify_mode(direction: str, settings: Settings, user_obj: PlexUser | None) -> str:
    attr = "series_vf_notify_mode" if direction == "vf" else "series_vo_notify_mode"
    user_value = getattr(user_obj, attr, None) if user_obj else None
    return _valid_series_notify_mode(user_value or getattr(settings, attr, None))


def _normalized_episode_status(episode_status: dict | None) -> dict[int, dict[int, bool]]:
    normalized: dict[int, dict[int, bool]] = {}
    for season, eps in (episode_status or {}).items():
        try:
            season_number = int(season)
        except Exception:
            continue
        normalized[season_number] = {}
        for episode, has_vf in (eps or {}).items():
            try:
                episode_number = int(episode)
            except Exception:
                continue
            normalized[season_number][episode_number] = bool(has_vf)
    return normalized


def _series_language_milestones(direction: str, mode: str, episode_status: dict | None, has_vf_full: bool):
    status = _normalized_episode_status(episode_status)

    def matches(has_vf: bool) -> bool:
        return has_vf if direction == "vf" else not has_vf

    milestones = []
    mode = _valid_series_notify_mode(mode)

    if mode == "series_complete":
        if (direction == "vf" and has_vf_full) or (status and direction == "vo" and all(
            matches(v) for eps in status.values() for v in eps.values()
        )):
            milestones.append(("series_complete", None, None))
        return milestones
    if not status:
        return []

    for season, eps in sorted(status.items()):
        matching_eps = sorted(ep for ep, has_vf in eps.items() if matches(has_vf))
        if not matching_eps:
            continue
        if mode == "every_episode":
            milestones.extend(("episode", season, ep) for ep in matching_eps)
            continue
        if mode == "season_start_and_complete":
            milestones.append(("season_start", season, matching_eps[0]))
        if mode in ("season_complete", "season_start_and_complete") and all(matches(v) for v in eps.values()):
            milestones.append(("season_complete", season, None))
    return milestones


def _milestone_reason(direction: str, milestone_type: str, season: int | None, episode: int | None) -> str:
    lang = "VF" if direction == "vf" else "VO"
    if milestone_type == "episode" and season is not None and episode is not None:
        return f"{lang} S{season:02d}E{episode:02d}"
    if milestone_type == "season_start" and season is not None:
        return f"{lang} saison {season} demarree"
    if milestone_type == "season_complete" and season is not None:
        return f"{lang} saison {season} complete"
    if milestone_type == "series_complete":
        return f"{lang} serie complete"
    return lang


def _milestone_exists(db: Session, req: MediaRequest, direction: str, milestone_type: str, season, episode) -> bool:
    q = db.query(NotificationMilestone).filter(
        NotificationMilestone.req_id == req.id,
        NotificationMilestone.plex_user_id == req.plex_user_id,
        NotificationMilestone.direction == direction,
        NotificationMilestone.milestone_type == milestone_type,
    )
    q = q.filter(NotificationMilestone.season_number.is_(None) if season is None else NotificationMilestone.season_number == season)
    q = q.filter(NotificationMilestone.episode_number.is_(None) if episode is None else NotificationMilestone.episode_number == episode)
    return q.first() is not None


def _queue_vf_milestone(
    direction: str,
    settings: Settings,
    req: MediaRequest,
    db: Session,
    milestone_type: str,
    season: int | None = None,
    episode: int | None = None,
) -> bool:
    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    if not _user_wants_vf(user_obj, req.vf_category):
        return False
    if req.media_type == "movie" and not _resolve_movie_notify(direction, settings, user_obj):
        return False
    if _milestone_exists(db, req, direction, milestone_type, season, episode):
        return False

    db.add(
        NotificationMilestone(
            req_id=req.id,
            plex_user_id=req.plex_user_id,
            direction=direction,
            milestone_type=milestone_type,
            season_number=season,
            episode_number=episode,
        )
    )
    db.commit()

    email_flag = settings.email_on_vf_available if direction == "vf" else True
    recipients = _get_vf_recipients(user_obj, settings, req.vf_category) if email_flag else []
    event = "vf_available" if direction == "vf" else "vo_only"
    if req.media_type == "movie" and direction == "vo" and milestone_type == "movie" and req.available_mail_sent:
        event = "available_vo_tracking"
    enqueue_notification(event, req.id, recipients, _milestone_reason(direction, milestone_type, season, episode))
    return True


def _queue_language_progress_notifications(
    direction: str,
    settings: Settings,
    req: MediaRequest,
    db: Session,
    episode_status: dict | None = None,
    has_vf_full: bool = False,
) -> int:
    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    if not _user_wants_vf(user_obj, req.vf_category):
        return 0
    if req.media_type != "show":
        return int(_queue_vf_milestone(direction, settings, req, db, "movie"))

    mode = _resolve_series_notify_mode(direction, settings, user_obj)
    count = 0
    for milestone_type, season, episode in _series_language_milestones(direction, mode, episode_status, has_vf_full):
        if _queue_vf_milestone(direction, settings, req, db, milestone_type, season, episode):
            count += 1
    return count


def _notify_vf(event: str, settings: Settings, req: MediaRequest, db: Session):
    """Empile une notification VF ("vo_only" ou "vf_available") dans la queue.

    Respecte les flags anti-doublon (vo_only_mail_sent / vf_available_mail_sent) et
    les préférences de notification VF par utilisateur et par type de média.
    """
    if event == "vo_only" and req.vo_only_mail_sent:
        return
    if event == "vf_available" and req.vf_available_mail_sent:
        return
    email_flag = settings.email_on_vf_available if event == "vf_available" else True
    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    recipients = _get_vf_recipients(user_obj, settings, req.vf_category) if email_flag else []
    queued_event = event
    if event == "vo_only" and req.media_type == "movie" and req.available_mail_sent:
        queued_event = "available_vo_tracking"
    enqueue_notification(queued_event, req.id, recipients, "")


def _resolve_partial_notify_frequency(settings: Settings, user_obj: PlexUser | None) -> str:
    """Fréquence de notification pour une série en disponibilité partielle.

    Le réglage par utilisateur (PlexUser.partial_notify_frequency) prime sur le
    réglage global (Settings.partial_notify_frequency) s'il est défini.
    """
    if user_obj and user_obj.partial_notify_frequency:
        return user_obj.partial_notify_frequency
    return settings.partial_notify_frequency or "milestones"


def _notify_partial(settings: Settings, req: MediaRequest, db: Session):
    """Empile une notification « disponibilité partielle » (série en cours de diffusion).

    Respecte le flag notify_on_available par utilisateur (même portée que la notif
    « disponible » classique — c'est toujours une annonce de disponibilité, partielle
    ou non).
    """
    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    recipients = _get_recipients(user_obj, settings, "available") if settings.email_on_available else []
    reason = f"{req.episodes_available_count or 0}/{req.episodes_aired_count or 0}"
    enqueue_notification("partially_available", req.id, recipients, reason)


def _handle_show_progress_notification(settings: Settings, req: MediaRequest, db: Session) -> None:
    """Décide et envoie la notification de disponibilité pour une série suivie par
    compteurs d'épisodes (Sonarr direct — pas de suivi partiel via Seer).

    - episodes_available_count >= episodes_total_count : série complète -> notif
      "available" classique (une seule fois, via available_mail_sent).
    - Sinon (encore partielle) selon la fréquence choisie (globale ou par utilisateur) :
        · "milestones" (défaut) : une notif à la 1ère dispo partielle seulement.
        · "every_episode" : une notif à chaque nouvel épisode téléchargé.

    Si aucune donnée de progression n'est disponible (ex: média géré par Seer), la
    demande garde le comportement historique : une notif "available" classique.
    """
    if req.media_type != "show" or not req.episodes_total_count:
        if not req.available_mail_sent:
            _notify("available", settings, req, db)
        return

    is_complete = (req.episodes_available_count or 0) >= req.episodes_total_count
    if is_complete:
        if not req.available_mail_sent:
            _notify("available", settings, req, db)
        return

    if (req.episodes_available_count or 0) <= 0:
        return  # aucun fichier pour l'instant, rien à notifier

    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    frequency = _resolve_partial_notify_frequency(settings, user_obj)

    if frequency == "every_episode":
        if (req.episodes_available_count or 0) > (req.last_notified_episode_count or 0):
            _notify_partial(settings, req, db)
    else:  # "milestones"
        if not req.partial_available_mail_sent:
            _notify_partial(settings, req, db)


def _notify(event: str, settings: Settings, req: MediaRequest, db: Session, reason: str = "", force: bool = False):
    """Empile une notification dans la queue après résolution des destinataires.

    force=True ignore les flags *_mail_sent (renvoi manuel demandé par l'utilisateur).
    """
    if not force:
        if event == "request" and req.request_mail_sent:
            return
        if event == "available" and req.available_mail_sent:
            return
    queued_event = event
    if event == "available" and req.has_vf is True:
        queued_event = "available_vf"
    email_flag = settings.email_on_available if event == "available" else settings.email_on_request
    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    recipients = _get_recipients(user_obj, settings, event) if email_flag else []
    enqueue_notification(queued_event, req.id, recipients, reason)


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


def _load_known_vf_episodes(
    db: Session, source_type: str, source_ids: list[int]
) -> dict[int, dict[int, set[int]]]:
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
            row = existing.get((sn, en))
            if row:
                if row.has_vf != has_vf:
                    row.has_vf = has_vf
                row.checked_at = now
            else:
                db.add(
                    VfEpisodeStatus(
                        source_type=source_type,
                        source_id=source_id,
                        season_number=sn,
                        episode_number=en,
                        has_vf=has_vf,
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
) -> list[dict]:
    """Analyse (bloquante, plexapi) la présence de VF pour chaque candidat.

    Exécutée dans un thread via asyncio.to_thread pour ne pas bloquer la boucle async.
    `known_vf_by_id` (séries) : cache par candidat, voir `_load_known_vf_episodes` —
    les épisodes déjà confirmés VF ne sont pas re-interrogés dans Plex.
    Retourne une liste de dicts : {"id", "found", "has_vf", "category", "episode_status"?}.
    """
    known_vf_by_id = known_vf_by_id or {}
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
                plex, c["media_type"], movie_libs, show_libs,
                c["title"], c["year"], c["tmdb_id"], c["tvdb_id"], c["imdb_id"],
                plex_guid=c.get("plex_guid"),
                known_vf=known_vf_by_id.get(c["id"]),
            )
            results.append({"id": c["id"], **res})
        except Exception as exc:
            logger.warning(f"VFF : erreur analyse '{c.get('title')}' : {exc}")
            results.append({"id": c["id"], "found": False})
        finally:
            vff_scan_state["items_scanned"] += 1
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


async def check_vf_statuses():
    """Job VFF : détecte la présence de VF sur les médias disponibles et notifie.

    - Première analyse d'un média (has_vf IS NULL) :
        · VF présente  → has_vf=True (pas de notification, l'« available » a suffi)
        · VO seulement → has_vf=False + notification « disponible en VO » + suivi actif
    - Ré-analyse des médias suivis (has_vf=False) :
        · VF désormais présente → has_vf=True + notification « VF disponible »

    La détection Plex (plexapi) est bloquante : elle est déportée dans un thread.
    """
    if vff_scan_state["status"] == "running":
        logger.info("VFF : un scan est déjà en cours, skip")
        return

    vff_scan_state["status"] = "running"
    vff_scan_state["started_at"] = datetime.now(timezone.utc).isoformat()
    vff_scan_state["finished_at"] = None
    vff_scan_state["items_scanned"] = 0
    vff_scan_state["total_items"] = 0
    vff_scan_state["error"] = None

    db = SessionLocal()
    try:
        settings = db.query(Settings).first()
        if not settings or not settings.vff_enabled:
            vff_scan_state["status"] = "idle"
            return
        if not settings.plex_url or not settings.plex_token:
            logger.info("VFF : Plex non configuré, skip")
            vff_scan_state["status"] = "idle"
            return

        libs = _parse_vff_libraries(settings)
        if not libs:
            logger.info("VFF : aucune bibliothèque configurée, skip")
            vff_scan_state["status"] = "idle"
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
        now_reconcile = datetime.now(timezone.utc).replace(tzinfo=None)
        for req in pending_q:
            li = _link_request_to_library_item(db, req)
            if not li:
                continue
            req.status = RequestStatus.available
            req.available_at = now_reconcile
            req.next_release_at = None
            req.next_release_label = None
            db.commit()
            promoted += 1
            logger.info(
                f"VFF : '{req.title}' détecté disponible via la bibliothèque Plex (arr en retard/inconnu)"
            )
            # Pas de notification "available" ici : cette fonction ne tourne que si VFF est
            # actif (garde en tête de fonction), donc has_vf est encore None juste après la
            # promotion -> la demande retombe naturellement dans candidates_q ci-dessous et
            # reçoit "available" (VF présente) ou "vo_only" (VO) selon le résultat du scan,
            # sans jamais doubler la notification.
        if promoted:
            logger.info(f"VFF : {promoted} demande(s) promue(s) 'disponible' via la bibliothèque Plex")

        candidates_q = (
            db.query(MediaRequest)
            .filter(
                MediaRequest.status == RequestStatus.available,
                (MediaRequest.has_vf.is_(None)) | (MediaRequest.has_vf.is_(False)),
            )
            .all()
        )
        lib_q = (
            db.query(LibraryItem)
            .filter((LibraryItem.has_vf.is_(None)) | (LibraryItem.has_vf.is_(False)))
            .all()
        )
        if not candidates_q and not lib_q:
            vff_scan_state["status"] = "idle"
            vff_scan_state["finished_at"] = datetime.now(timezone.utc).isoformat()
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
        vff_scan_state["total_items"] = len(candidates) + len(lib_candidates)
        logger.info(
            f"VFF : analyse de {len(candidates)} demande(s) non liée(s) + {len(lib_candidates)} média(s) "
            f"de bibliothèque ({len(linked_pairs)} demande(s) liée(s), pas de re-scan)"
        )

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        results_by_id = {}
        if candidates:
            known_vf_requests = _load_known_vf_episodes(db, "request", [c["id"] for c in candidates])
            results = await asyncio.to_thread(
                _scan_vf_blocking, settings.plex_url, settings.plex_token, candidates, libs, known_vf_requests
            )
            results_by_id = {r["id"]: r for r in results}
            for r in results:
                episode_status = r.get("episode_status")
                if episode_status:
                    _persist_episode_status(db, "request", r["id"], episode_status, now)
            if any(r.get("episode_status") for r in results):
                db.commit()

        newly_vo = 0
        newly_vf = 0
        newly_fallback = 0

        def _apply_vf_result(
            req: MediaRequest,
            has_vf: bool,
            category: str | None,
            episode_status: dict | None = None,
            granularity: str | None = None,
        ) -> bool:
            """Applique une transition VO/VF à une demande (notifications incluses).

            `granularity` : si déjà connue (ex: propagée depuis un LibraryItem lié), on
            l'utilise directement — sinon elle est calculée depuis `episode_status`.
            Renvoie True si une recherche VFF auto (Sonarr/Radarr) doit être déclenchée
            par l'appelant (await nécessaire, donc hors de cette fonction synchrone).
            """
            nonlocal newly_vo, newly_vf
            was_tracking = req.has_vf is False  # déjà identifié VO au passage précédent
            req.vf_category = category or req.vf_category
            req.vf_checked_at = now
            trigger_search = False

            if has_vf:
                req.has_vf = True
                req.vf_granularity = "full"
                if was_tracking:
                    # Transition VO → VF : on prévient
                    req.vf_available_at = now
                    db.commit()
                    newly_vf += _queue_language_progress_notifications(
                        "vf", settings, req, db, episode_status=episode_status, has_vf_full=True
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
                        newly_vo += _queue_language_progress_notifications(
                            "vo", settings, req, db, episode_status=episode_status, has_vf_full=False
                        )
                        logger.info(f"VFF : '{req.title}' disponible en VO uniquement — suivi VF activé")
                    else:
                        # Dispo déjà notifiée (fallback scan-lag) → suivi silencieux
                        db.commit()
                    trigger_search = bool(settings.vff_auto_search)
                else:
                    db.commit()
                    newly_vf += _queue_language_progress_notifications(
                        "vf", settings, req, db, episode_status=episode_status, has_vf_full=False
                    )
            return trigger_search

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

            if _apply_vf_result(req, res["has_vf"], res.get("category"), episode_status=res.get("episode_status")):
                await _trigger_vf_search(db, settings, req)

        # --- Médias de bibliothèque : état VF pour affichage (pas de notification) ---
        lib_updated = 0
        if lib_candidates:
            known_vf_lib = _load_known_vf_episodes(db, "library_item", [c["id"] for c in lib_candidates])
            lib_results = await asyncio.to_thread(
                _scan_vf_blocking, settings.plex_url, settings.plex_token, lib_candidates, libs, known_vf_lib
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
                    _persist_episode_status(db, "library_item", li.id, episode_status, now)
            db.commit()

        # --- Demandes liées à un LibraryItem : propager son has_vf, pas de re-scan Plex ---
        linked_updated = 0
        linked_episode_status = _load_episode_status_map(
            db, "library_item", list({li.id for _, li in linked_pairs})
        )
        for req, li in linked_pairs:
            if li.has_vf is None:
                continue  # LibraryItem pas encore résolu ; réessaiera au prochain cycle
            if _apply_vf_result(
                req,
                li.has_vf,
                li.vf_category,
                episode_status=linked_episode_status.get(li.id),
                granularity=li.vf_granularity,
            ):
                await _trigger_vf_search(db, settings, req)
            linked_updated += 1

        logger.info(
            f"VFF : analyse terminée ({newly_vo} nouveau(x) VO, {newly_vf} VF détectée(s), "
            f"{newly_fallback} dispo notifiée(s) en filet, {lib_updated} média(s) de bibliothèque mis à jour, "
            f"{linked_updated} demande(s) liée(s) synchronisée(s))"
        )
        vff_scan_state["status"] = "idle"
        vff_scan_state["finished_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as e:
        logger.error(f"Erreur check_vf_statuses : {e}")
        vff_scan_state["status"] = "failed"
        vff_scan_state["error"] = str(e)
    finally:
        db.close()


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
        db, item["plex_guid"], item["tmdb_id"], item["tvdb_id"], item["imdb_id"], item["title"], item["year"], item["media_type"]
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


async def sync_plex_media():
    """Tâche planifiée : synchronise les médias Plex configurés avec la base de données.

    Vérifie l'existence de chaque média par GUID Plex ou identifiant externe.
    Enregistre les nouveaux médias en statut disponible avec la source "plex_sync".
    """
    if plex_sync_state["status"] == "running":
        logger.info("VFF Sync : une synchronisation est déjà en cours, skip")
        return

    plex_sync_state["status"] = "running"
    plex_sync_state["started_at"] = datetime.now(timezone.utc).isoformat()
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

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        added_count = 0
        for item in plex_items:
            lib_item = _find_library_item(db, item)

            # Tenter de trouver une correspondance Arr
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
                # Nouvel élément de bibliothèque
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
                # Élément déjà connu : compléter les infos manquantes
                if not lib_item.plex_guid and item["plex_guid"]:
                    lib_item.plex_guid = item["plex_guid"]
                if not lib_item.poster_url and item["poster_url"]:
                    lib_item.poster_url = item["poster_url"]
                if not lib_item.arr_instance_id and arr_match:
                    lib_item.arr_instance_id = arr_instance_id
                    lib_item.arr_id = arr_id
                    lib_item.arr_slug = arr_slug
                lib_item.updated_at = now
            db.commit()

            plex_sync_state["items_synced"] += 1

        if added_count > 0:
            logger.info(f"VFF Sync : {added_count} nouveau(x) média(s) Plex ajouté(s) à la bibliothèque")
            # Déclencher immédiatement une analyse VFF pour les nouveaux médias ajoutés
            asyncio.create_task(check_vf_statuses())
        else:
            logger.info("VFF Sync : aucun nouveau média Plex détecté")

        plex_sync_state["status"] = "idle"
        plex_sync_state["finished_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as e:
        logger.error(f"VFF Sync : erreur synchronisation : {e}")
        plex_sync_state["status"] = "failed"
        plex_sync_state["error"] = str(e)
    finally:
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
                series_stats = None
                try:
                    if settings.seer_enabled and settings.seer_url:
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

                was_already_available = req.status == RequestStatus.available
                if available:
                    if not was_already_available:
                        req.status = RequestStatus.available
                        req.available_at = datetime.now(timezone.utc).replace(tzinfo=None)
                        req.next_release_at = None
                        req.next_release_label = None
                        newly_available += 1
                        logger.info(f"'{req.title}' is now available")
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
                        _notify("available", settings, req, db)
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
            asyncio.create_task(check_vf_statuses())

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
