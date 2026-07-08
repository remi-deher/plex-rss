import json
import logging
import re
import time
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import MediaRequest, NotificationLog, NotificationMilestone, PlexUser, PollHistory, Settings
from ..notification_queue import enqueue as enqueue_notification
from ..utils import db_session, now_utc, now_utc_naive, parse_email_list

logger = logging.getLogger(__name__)


async def _send_digest():
    """Envoie le récapitulatif quotidien aux utilisateurs ayant notify_digest=True."""
    from .email_service import _send as smtp_send

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


def _resolve_series_tracking_mode(settings: Settings, user_obj: PlexUser | None) -> str:
    """"language" (VF/VO, historique) ou "simple" (épisodes/saisons, sans langue).

    Réglage par utilisateur (PlexUser.series_tracking_mode) prioritaire sur le réglage
    global (Settings.series_tracking_mode) s'il est défini. Les deux modes sont
    mutuellement exclusifs pour une série donnée.
    """
    user_value = getattr(user_obj, "series_tracking_mode", None) if user_obj else None
    value = user_value or getattr(settings, "series_tracking_mode", None)
    return value if value in ("language", "simple") else "language"


def _resolve_episode_notify_mode(settings: Settings, user_obj: PlexUser | None) -> str:
    user_value = getattr(user_obj, "series_episode_notify_mode", None) if user_obj else None
    return _valid_series_notify_mode(user_value or getattr(settings, "series_episode_notify_mode", None))


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
    """Calcule les jalons (episode/season_start/season_complete/series_complete) à notifier.

    `direction` : "vf"/"vo" (suivi par langue) ou "simple" (suivi épisode indépendant de
    la langue — `episode_status` ne sert alors qu'à connaître la présence des épisodes sur
    Plex, `matches` est donc toujours vrai : tout épisode connu de Plex "correspond").
    """
    status = _normalized_episode_status(episode_status)

    def matches(has_vf: bool) -> bool:
        if direction == "simple":
            return True
        return has_vf if direction == "vf" else not has_vf

    milestones = []
    mode = _valid_series_notify_mode(mode)

    if mode == "series_complete":
        if (direction == "vf" and has_vf_full) or (status and direction in ("vo", "simple") and all(
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
    lang = "VF" if direction == "vf" else ("VO" if direction == "vo" else "")
    prefix = f"{lang} " if lang else ""
    if milestone_type == "episode" and season is not None and episode is not None:
        return f"{prefix}S{season:02d}E{episode:02d}"
    if milestone_type == "season_start" and season is not None:
        return f"{prefix}saison {season} demarree"
    if milestone_type == "season_complete" and season is not None:
        return f"{prefix}saison {season} complete"
    if milestone_type == "series_complete":
        return f"{prefix}serie complete"
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

    if direction == "simple":
        # Suivi épisode indépendant de la langue : pas de gate VF (notify_vf_*), on
        # respecte simplement le flag standard "disponibilité" de l'utilisateur.
        if req.media_type != "show":
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
        recipients = _get_recipients(user_obj, settings, "available") if settings.email_on_available else []
        enqueue_notification(
            "episode_track", req.id, recipients, _milestone_reason(direction, milestone_type, season, episode)
        )
        return True

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


def _queue_episode_progress_notifications(settings: Settings, req: MediaRequest, db: Session, episode_status: dict | None) -> int:
    """Équivalent de `_queue_language_progress_notifications` pour le mode "simple"
    (suivi épisode/saison indépendant de la langue, voir `_resolve_series_tracking_mode`).
    """
    if req.media_type != "show":
        return 0
    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    mode = _resolve_episode_notify_mode(settings, user_obj)
    count = 0
    for milestone_type, season, episode in _series_language_milestones("simple", mode, episode_status, False):
        if _queue_vf_milestone("simple", settings, req, db, milestone_type, season, episode):
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

    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    tracking_mode = _resolve_series_tracking_mode(settings, user_obj)
    # Un suivi de série est "actif" s'il va effectivement tourner et notifier la complétion
    # via son propre jalon "série complète" : le mode "simple" tourne toujours
    # (check_episode_tracking, indépendant de vff_enabled) ; le mode "langue" ne tourne
    # que si VFF est activé (check_vf_statuses). Sinon, aucun autre mécanisme ne préviendra
    # jamais l'utilisateur — il ne faut alors pas supprimer le mail "Disponible" classique.
    tracking_active = tracking_mode == "simple" or (tracking_mode == "language" and settings.vff_enabled)

    is_complete = (req.episodes_available_count or 0) >= req.episodes_total_count
    if is_complete:
        if tracking_active:
            # Le suivi de série annonce déjà la complétion via son jalon "série complète" —
            # éviter le doublon avec le mail "Disponible" classique.
            return
        if not req.available_mail_sent:
            _notify("available", settings, req, db)
        return

    if (req.episodes_available_count or 0) <= 0:
        return  # aucun fichier pour l'instant, rien à notifier

    if tracking_mode == "simple":
        # Le suivi "simple" (check_episode_tracking) couvre déjà "nouvel épisode" /
        # "saison complète" à partir du scan Plex — la notif "disponibilité partielle"
        # (issue des compteurs Sonarr) ferait doublon pour le même événement.
        return

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


