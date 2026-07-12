import json
import logging
import time
from dataclasses import dataclass
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
            if not settings or not settings.digest_enabled or not settings.email_enabled:
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

            from .download_history import purge_old_entries

            purge_old_entries(db)
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

    - Canal email désactivé globalement (`email_enabled`) : aucune notification.
    - Si l'utilisateur est inactif (enabled=False) : aucune notification.
    - Adresse(s) de l'utilisateur (séparées par virgules), ou smtp_from par défaut.
    - Si notify_admin=True sur l'utilisateur, ajoute admin_notification_email en copie.
    - Respecte les flags notify_on_request / notify_on_available par utilisateur.
    """
    if not settings.email_enabled:
        return []
    if user_obj and not user_obj.enabled:
        return []

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
    """Résout les destinataires email d'une notification de disponibilité avec suivi de langue."""
    if not settings.email_enabled:
        return []
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


# ---------------------------------------------------------------------------
# Réglages de disponibilité — 2 axes (voir migration 0055_simplify_notify_settings) :
# notify_language (VO/VF distingués ou non) × notify_granularity (séries uniquement :
# minimal/jalons/tout). Remplace l'ancien enchevêtrement tracking_mode "language"/
# "simple"/"classic" + 4 modes de fréquence par direction.
# ---------------------------------------------------------------------------

GRANULARITY_MODES = {"minimal", "jalons", "tout"}


@dataclass(frozen=True)
class AvailabilityCandidate:
    """Jalon de disponibilite detecte pendant un cycle de scan."""

    scope: str
    language: str | None = None
    is_upgrade: bool = False
    season_number: int | None = None
    episode_number: int | None = None


_AVAILABILITY_PRIORITY = {
    "episode": 50,
    "season_start": 40,
    "season_complete": 40,
    "series_complete": 30,
    "movie": 20,
}


def _valid_granularity(value: str | None, default: str = "jalons") -> str:
    return value if value in GRANULARITY_MODES else default


def _resolve_movie_notify_language(settings: Settings, user_obj: PlexUser | None) -> bool:
    user_value = getattr(user_obj, "movie_notify_language", None) if user_obj else None
    if user_value is not None:
        return bool(user_value)
    return getattr(settings, "movie_notify_language", True) is not False


def _resolve_series_notify_language(settings: Settings, user_obj: PlexUser | None) -> bool:
    user_value = getattr(user_obj, "series_notify_language", None) if user_obj else None
    if user_value is not None:
        return bool(user_value)
    return getattr(settings, "series_notify_language", True) is not False


def _resolve_series_granularity(settings: Settings, user_obj: PlexUser | None) -> str:
    user_value = getattr(user_obj, "series_notify_granularity", None) if user_obj else None
    return _valid_granularity(user_value or getattr(settings, "series_notify_granularity", None))


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


def _series_milestones(
    granularity: str,
    episode_status: dict | None,
    has_vf_full: bool,
    language: str | None,
    season_aired_counts: dict[int, int] | None = None,
) -> list[tuple[str, int | None, int | None]]:
    """Calcule les jalons (episode/season_start/season_complete/series_complete) à notifier.

    `language` : "vf"/"vo" (suivi par langue — seuls les épisodes correspondant à cette
    langue comptent) ou None (suivi indépendant de la langue — tout épisode présent compte).

    `season_aired_counts` : nombre d'épisodes Sonarr déjà diffusés par saison. Sans cette
    référence, un début de saison (1 seul épisode sorti) déclencherait à tort "saison
    complète" en même temps que "saison démarrée", faute de savoir que d'autres épisodes
    diffusés restent encore à charger.
    """
    status = _normalized_episode_status(episode_status)
    granularity = _valid_granularity(granularity)

    def matches(has_vf: bool) -> bool:
        if language is None:
            return True
        return has_vf if language == "vf" else not has_vf

    milestones: list[tuple[str, int | None, int | None]] = []

    if granularity == "minimal":
        if (language == "vf" and has_vf_full) or (
            status and language in ("vo", None) and all(matches(v) for eps in status.values() for v in eps.values())
        ):
            milestones.append(("series_complete", None, None))
        return milestones
    if not status:
        return []

    for season, eps in sorted(status.items()):
        matching_eps = sorted(ep for ep, has_vf in eps.items() if matches(has_vf))
        if not matching_eps:
            continue
        if granularity == "tout":
            milestones.extend(("episode", season, ep) for ep in matching_eps)
            continue
        # "jalons" : début + fin de saison
        milestones.append(("season_start", season, matching_eps[0]))
        if all(matches(v) for v in eps.values()):
            expected = season_aired_counts.get(season) if season_aired_counts else None
            if expected is None or len(eps) >= expected:
                milestones.append(("season_complete", season, None))
    return milestones


def _milestone_exists(db: Session, req: MediaRequest, direction: str, scope: str, season, episode) -> bool:
    q = db.query(NotificationMilestone).filter(
        NotificationMilestone.req_id == req.id,
        NotificationMilestone.plex_user_id == req.plex_user_id,
        NotificationMilestone.direction == direction,
        NotificationMilestone.milestone_type == scope,
    )
    q = q.filter(
        NotificationMilestone.season_number.is_(None)
        if season is None
        else NotificationMilestone.season_number == season
    )
    q = q.filter(
        NotificationMilestone.episode_number.is_(None)
        if episode is None
        else NotificationMilestone.episode_number == episode
    )
    return q.first() is not None


def _candidate_key(candidate: AvailabilityCandidate) -> tuple:
    return (
        candidate.language or "simple",
        candidate.scope,
        candidate.season_number,
        candidate.episode_number,
        candidate.language,
        bool(candidate.is_upgrade),
    )


def _candidate_priority(candidate: AvailabilityCandidate) -> tuple[int, int, int]:
    language_score = 2 if candidate.language == "vf" else 1 if candidate.language == "vo" else 0
    return (_AVAILABILITY_PRIORITY.get(candidate.scope, 10), language_score, 1 if candidate.is_upgrade else 0)


def resolve_and_notify_availability(
    settings: Settings,
    req: MediaRequest,
    db: Session,
    *,
    candidates: list[AvailabilityCandidate],
) -> bool:
    """Record all detected availability milestones and enqueue at most one notification."""
    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    unique_candidates = list({_candidate_key(candidate): candidate for candidate in candidates}.values())
    if not unique_candidates:
        return False

    eligible: list[AvailabilityCandidate] = []
    for candidate in unique_candidates:
        if candidate.language is not None:
            if not _user_wants_vf(user_obj, req.vf_category):
                continue
            if req.media_type == "movie" and not _resolve_movie_notify_language(settings, user_obj):
                continue
            
            # --- INVARIANTS CENTRAUX (Audit) ---
            if candidate.language == "vf":
                # Un film notifié en VF doit être officiellement marqué has_vf = True
                if req.media_type == "movie" and req.has_vf is not True:
                    continue
                # Une série notifiée en VF est autorisée même si has_vf=False car le statut peut être partiel.
            
            if candidate.is_upgrade and req.media_type == "movie" and req.has_vf is False:
                continue
                
        eligible.append(candidate)
    if not eligible:
        return False

    new_candidates: list[AvailabilityCandidate] = []
    for candidate in eligible:
        direction = candidate.language or "simple"
        if _milestone_exists(db, req, direction, candidate.scope, candidate.season_number, candidate.episode_number):
            continue
        db.add(
            NotificationMilestone(
                req_id=req.id,
                plex_user_id=req.plex_user_id,
                direction=direction,
                milestone_type=candidate.scope,
                language=candidate.language,
                is_upgrade=bool(candidate.is_upgrade),
                season_number=candidate.season_number,
                episode_number=candidate.episode_number,
            )
        )
        new_candidates.append(candidate)
    db.commit()

    if not new_candidates:
        return False

    winner = max(new_candidates, key=_candidate_priority)
    email_flag = settings.email_on_vf_available if winner.is_upgrade else settings.email_on_available
    if winner.language is not None:
        recipients = _get_vf_recipients(user_obj, settings, req.vf_category) if email_flag else []
    else:
        recipients = _get_recipients(user_obj, settings, "available") if email_flag else []

    enqueue_notification(
        "available",
        req.id,
        recipients,
        {
            "scope": winner.scope,
            "language": winner.language,
            "is_upgrade": bool(winner.is_upgrade),
            "season_number": winner.season_number,
            "episode_number": winner.episode_number,
        },
    )
    return True


def _queue_milestone(
    settings: Settings,
    req: MediaRequest,
    db: Session,
    *,
    scope: str,
    language: str | None = None,
    season: int | None = None,
    episode: int | None = None,
) -> bool:
    """Empile UNE notification de disponibilité pour un jalon précis, avec dédup par
    NotificationMilestone (clé : req + destinataire + langue + jalon + saison/épisode).

    `language` None = suivi sans distinction de langue (granularité seule, remplace
    l'ancien mode "simple"). `scope="movie"|"episode"|"season_start"|"season_complete"|
    "series_complete"`. C'est le point de passage UNIQUE pour toute notification de
    disponibilité avec jalon — garantit qu'un seul mail part par jalon réel, jamais un
    générique "available" en plus (voir _notify, qui ne sert plus que de repli quand
    aucun suivi fin n'est actif pour ce média).
    """
    return resolve_and_notify_availability(
        settings,
        req,
        db,
        candidates=[
            AvailabilityCandidate(
                scope=scope,
                language=language,
                is_upgrade=language == "vf",
                season_number=season,
                episode_number=episode,
            )
        ],
    )


def _queue_show_milestones(
    settings: Settings,
    req: MediaRequest,
    db: Session,
    *,
    language: str | None,
    episode_status: dict | None = None,
    has_vf_full: bool = False,
    season_aired_counts: dict[int, int] | None = None,
) -> int:
    """Calcule et empile les jalons d'une série selon la granularité configurée.

    `language` : "vf"/"vo" si l'appelant vient du scan VF (audio Plex), ou None si
    l'appelant vient du suivi "sans langue" (présence d'épisode seule, indépendant de
    vff_enabled — voir check_episode_tracking).
    """
    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    if language is not None and not _user_wants_vf(user_obj, req.vf_category):
        return 0
    granularity = _resolve_series_granularity(settings, user_obj)
    candidates = [
        AvailabilityCandidate(
            scope=scope,
            language=language,
            is_upgrade=language == "vf",
            season_number=season,
            episode_number=episode,
        )
        for scope, season, episode in _series_milestones(
            granularity, episode_status, has_vf_full, language, season_aired_counts
        )
    ]
    return int(resolve_and_notify_availability(settings, req, db, candidates=candidates))


def _notify(event: str, settings: Settings, req: MediaRequest, db: Session, reason: str = "", force: bool = False):
    """Notification générique (repli) : pas de jalon précis, ou évènement simple
    (request/failed). Ne doit JAMAIS être appelée en plus d'un `_queue_milestone` pour le
    même changement d'état — c'est le rôle de l'appelant (vff_scanner/webhook/arr_tracker)
    de choisir l'un ou l'autre selon qu'un suivi fin est actif pour ce média.

    force=True ignore les flags *_mail_sent (renvoi manuel demandé par l'utilisateur).
    """
    if not force:
        if event == "request" and req.request_mail_sent:
            return
        if event == "available" and req.available_mail_sent:
            return
    if event in ("failed", "failure"):
        email_flag = getattr(settings, "email_on_failure", True)
    elif event == "request":
        email_flag = settings.email_on_request
    else:
        email_flag = settings.email_on_available
    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    recipients = _get_recipients(user_obj, settings, event) if email_flag else []

    if event in ("failed", "failure"):
        enqueue_notification("failed", req.id, recipients, {"reason": reason})
        return
    if event == "request":
        enqueue_notification("request", req.id, recipients, None)
        return

    # "available" générique : aucun jalon précis (mode sans langue à granularité "minimal",
    # ou média sans suivi fin possible pour l'instant). language déduit du dernier état connu.
    language = "vf" if req.has_vf is True else ("vo" if req.has_vf is False else None)
    scope = "movie" if req.media_type == "movie" else "series_complete"
    resolve_and_notify_availability(
        settings,
        req,
        db,
        candidates=[AvailabilityCandidate(scope=scope, language=language, is_upgrade=False)],
    )


def _notify_partial(settings: Settings, req: MediaRequest, db: Session):
    """Notification « disponibilité partielle » via les compteurs Sonarr (VFF désactivé,
    pas de scan Plex possible — seul filet de sécurité restant, sans langue)."""
    resolve_and_notify_availability(
        settings,
        req,
        db,
        candidates=[AvailabilityCandidate(scope="episode", language=None, is_upgrade=False)],
    )


async def _handle_show_progress_notification(settings: Settings, req: MediaRequest, db: Session) -> None:
    """Décide et envoie la notification de disponibilité pour une série.

    Le suivi fin (jalons épisode/saison, avec ou sans langue) tourne dès que Plex est
    configuré (`vff_enabled`) — la granularité "minimal" y compris, qui se traduit
    simplement par un seul jalon "series_complete". Seul un `vff_enabled=False` bascule
    sur les compteurs Sonarr bruts (aucun scan Plex possible, donc aucune langue connue).
    """
    from .vff_scanner import scan_and_notify_availability

    if req.media_type != "show" or not req.episodes_total_count:
        if not req.available_mail_sent:
            _notify("available", settings, req, db)
        return

    if settings.vff_enabled:
        # Tente un scan Plex immédiat pour envoyer maintenant plutôt que d'attendre le
        # prochain scan planifié ; sans effet si le média n'est pas encore indexé (le
        # prochain scan planifié prend le relais, jamais de mail générique en secours ici
        # pour éviter tout doublon avec le jalon qui finira par partir).
        await scan_and_notify_availability(req, settings, db)
        return

    # VFF désactivé : pas de scan Plex possible, repli sur les compteurs Sonarr seuls.
    is_complete = (req.episodes_available_count or 0) >= req.episodes_total_count
    if is_complete:
        if not req.available_mail_sent:
            _notify("available", settings, req, db)
        return
    if (req.episodes_available_count or 0) <= 0:
        return

    user_obj = db.query(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id).first()
    granularity = _resolve_series_granularity(settings, user_obj)
    if granularity == "tout":
        if (req.episodes_available_count or 0) > (req.last_notified_episode_count or 0):
            _notify_partial(settings, req, db)
    else:  # "jalons"/"minimal" : une notif à la 1ère dispo partielle seulement
        if not req.partial_available_mail_sent:
            _notify_partial(settings, req, db)


# ---------------------------------------------------------------------------
# Jobs planifiés
# ---------------------------------------------------------------------------
