import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..database import AsyncSessionLocal
from ..models import MediaRequest, NotificationLog, NotificationMilestone, PlexUser, PollHistory, Settings
from ..notification_queue import enqueue
from ..utils import now_utc, now_utc_naive, parse_email_list

logger = logging.getLogger(__name__)


async def _send_digest():
    """Envoie le récapitulatif quotidien aux utilisateurs ayant notify_digest=True."""
    from .email_service import _send as smtp_send

    try:
        async with AsyncSessionLocal() as db:
            settings = (await db.execute(select(Settings))).scalars().first()
            if not settings or not settings.digest_enabled or not settings.email_enabled:
                return
            if not all([settings.smtp_host, settings.smtp_user, settings.smtp_password, settings.smtp_from]):
                logger.warning("Digest : SMTP non configuré, skip")
                return

            cutoff = now_utc_naive() - timedelta(hours=24)
            recent = (await db.execute(
                select(MediaRequest)
                .filter(MediaRequest.requested_at >= cutoff)
                .order_by(MediaRequest.requested_at.desc())
            )).scalars().all()
            if not recent:
                logger.info("Digest : aucune demande dans les 24h, skip")
                return

            users = (await db.execute(
                select(PlexUser).filter(
                    PlexUser.enabled.is_(True),
                    PlexUser.notify_digest.is_(True),
                )
            )).scalars().all()
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

            subject = f"[Plexarr] Récap du {now_utc_naive().strftime('%d/%m/%Y')} — {count} demande{plural}"
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


async def _purge_notification_logs():
    """Supprime les logs de notifications et l'historique de poll plus anciens que la rétention configurée."""
    try:
        async with AsyncSessionLocal() as db:
            settings = (await db.execute(select(Settings))).scalars().first()
            if not settings:
                return
            days = settings.notification_log_retention_days
            if days:
                cutoff = now_utc_naive() - timedelta(days=days)
                result = await db.execute(sqlalchemy.delete(NotificationLog).filter(NotificationLog.sent_at < cutoff))
                deleted = int(result.rowcount or 0)
                if deleted:
                    await db.commit()
                    logger.info(f"Purge logs notifications : {deleted} entrées supprimées (>{days}j)")

            poll_days = settings.poll_history_retention_days
            if poll_days:
                poll_cutoff = now_utc_naive() - timedelta(days=poll_days)
                result = await db.execute(sqlalchemy.delete(PollHistory).filter(PollHistory.started_at < poll_cutoff))
                deleted_polls = int(result.rowcount or 0)
                if deleted_polls:
                    await db.commit()

            from .download_history import purge_old_entries

            await purge_old_entries(db)
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


async def resolve_and_notify_availability(
    settings: Settings,
    req: MediaRequest,
    db: AsyncSession,
    *,
    candidates: list[AvailabilityCandidate],
) -> bool:
    """Version AsyncSession du flux de jalons de disponibilité.

    Les scanners historiques utilisent encore la version synchrone ci-dessus;
    les routes et webhooks, eux, ne doivent jamais retomber sur ``db.query``.
    """
    if req.notify_suppressed:
        return False
    user_obj = (
        await db.execute(select(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id))
    ).scalars().first()
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
            if candidate.language == "vf" and req.media_type == "movie" and req.has_vf is not True:
                continue
            if candidate.is_upgrade and req.media_type == "movie" and req.has_vf is False:
                continue
        eligible.append(candidate)
    if not eligible:
        return False

    new_candidates: list[AvailabilityCandidate] = []
    for candidate in eligible:
        direction = candidate.language or "simple"
        existing = (
            await db.execute(
                select(NotificationMilestone).filter(
                    NotificationMilestone.req_id == req.id,
                    NotificationMilestone.plex_user_id == req.plex_user_id,
                    NotificationMilestone.direction == direction,
                    NotificationMilestone.milestone_type == candidate.scope,
                    NotificationMilestone.season_number.is_(None)
                    if candidate.season_number is None
                    else NotificationMilestone.season_number == candidate.season_number,
                    NotificationMilestone.episode_number.is_(None)
                    if candidate.episode_number is None
                    else NotificationMilestone.episode_number == candidate.episode_number,
                )
            )
        ).scalars().first()
        if existing:
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
    await db.commit()
    if not new_candidates:
        return False

    winner = max(new_candidates, key=_candidate_priority)
    email_flag = settings.email_on_vf_available if winner.is_upgrade else settings.email_on_available
    if winner.language is not None:
        recipients = _get_vf_recipients(user_obj, settings, req.vf_category) if email_flag else []
    else:
        recipients = _get_recipients(user_obj, settings, "available") if email_flag else []
    await enqueue(
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


async def _queue_milestone(
    settings: Settings,
    req: MediaRequest,
    db: AsyncSession,
    *,
    scope: str,
    language: str | None = None,
    season: int | None = None,
    episode: int | None = None,
    is_upgrade: bool | None = None,
) -> bool:
    # Par défaut, une notification VF est traitée comme une "amélioration" (mail
    # dédié) — sauf appel explicite indiquant qu'il ne s'agit pas d'une vraie
    # transition VO→VF (ex: tout premier scan d'une demande qui tombe directement
    # sur du VF, sans période VO connue avant).
    resolved_upgrade = (language == "vf") if is_upgrade is None else is_upgrade
    return await resolve_and_notify_availability(
        settings,
        req,
        db,
        candidates=[
            AvailabilityCandidate(
                scope=scope,
                language=language,
                is_upgrade=resolved_upgrade,
                season_number=season,
                episode_number=episode,
            )
        ],
    )


async def _queue_show_milestones(
    settings: Settings,
    req: MediaRequest,
    db: AsyncSession,
    *,
    language: str | None,
    episode_status: dict | None = None,
    has_vf_full: bool = False,
    season_aired_counts: dict[int, int] | None = None,
) -> int:
    user_obj = (await db.execute(
        select(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id)
    )).scalars().first()
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
    return int(await resolve_and_notify_availability(settings, req, db, candidates=candidates))


async def _notify(
    event: str,
    settings: Settings,
    req: MediaRequest,
    db: AsyncSession,
    reason: str = "",
    force: bool = False,
    triggered_by: str = "auto",
) -> None:
    """Version async de la notification générique utilisée par les routes."""
    if not force:
        if req.notify_suppressed:
            # Vieil item de watchlist ressorti dans le flux RSS (> 24h à la détection) —
            # décision prise une fois pour toutes à la création (watchlist_poller.py).
            # Un renvoi manuel (force=True) reste toujours possible.
            return
        if event == "request" and req.request_mail_sent:
            return
        if event == "available" and req.available_mail_sent:
            return
        # Flag persisté plutôt qu'un état recalculé à la volée par l'appelant (l'ancien
        # garde-fou `was_failed` de watchlist_poller.py pouvait racer entre deux process —
        # voir le correctif du verrou distribué sur poll_watchlists). Remis à False par les
        # endpoints de retry (requests_api.py) et à la resoumission réussie, pour qu'un
        # nouvel échec après un retry redéclenche bien une notification.
        if event in ("failed", "failure") and req.failure_mail_sent:
            return
    email_flag = (
        getattr(settings, "email_on_failure", True)
        if event in ("failed", "failure")
        else settings.email_on_request
        if event == "request"
        else settings.email_on_available
    )
    user_obj = (
        await db.execute(select(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id))
    ).scalars().first()
    recipients = _get_recipients(user_obj, settings, event) if email_flag else []
    if event in ("failed", "failure"):
        await enqueue("failed", req.id, recipients, {"reason": reason}, triggered_by=triggered_by)
        return
    if event == "request":
        await enqueue("request", req.id, recipients, None, triggered_by=triggered_by)
        return
    language = "vf" if req.has_vf is True else ("vo" if req.has_vf is False else None)
    scope = "movie" if req.media_type == "movie" else "series_complete"
    if triggered_by != "auto":
        # Renvoi manuel (fiche détail) : envoi direct et prévisible, sans passer par le
        # système de jalons (resolve_and_notify_availability) — celui-ci applique des
        # règles d'éligibilité par langue pensées pour le scan VF automatique et pourrait
        # silencieusement ne rien envoyer selon les préférences VF de l'utilisateur, ce
        # qui serait surprenant pour une action explicite déclenchée par un admin.
        await enqueue(
            "available", req.id, recipients, {"scope": scope, "language": language, "is_upgrade": False},
            triggered_by=triggered_by,
        )
        return
    await resolve_and_notify_availability(
        settings,
        req,
        db,
        candidates=[AvailabilityCandidate(scope=scope, language=language, is_upgrade=False)],
    )


async def _handle_show_progress_notification(settings: Settings, req: MediaRequest, db: AsyncSession) -> None:
    """Décide et envoie la notification de disponibilité pour une série.

    Le suivi fin (jalons épisode/saison, avec ou sans langue) tourne dès que Plex est
    configuré (`vff_enabled`) — la granularité "minimal" y compris, qui se traduit
    simplement par un seul jalon "series_complete". Seul un `vff_enabled=False` bascule
    sur les compteurs Sonarr bruts (aucun scan Plex possible, donc aucune langue connue).
    """
    from .vff_scanner import scan_and_notify_availability

    if req.media_type != "show" or not req.episodes_total_count:
        if not req.available_mail_sent:
            await _notify("available", settings, req, db)
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
            await _notify("available", settings, req, db)
        return
    if (req.episodes_available_count or 0) <= 0:
        return

    user_obj = (await db.execute(select(PlexUser).filter(PlexUser.plex_user_id == req.plex_user_id))).scalars().first()
    granularity = _resolve_series_granularity(settings, user_obj)
    if granularity == "tout":
        if (req.episodes_available_count or 0) > (req.last_notified_episode_count or 0):
            await resolve_and_notify_availability(
                settings, req, db, candidates=[AvailabilityCandidate(scope="episode", language=None, is_upgrade=False)]
            )
    else:  # "jalons"/"minimal" : une notif à la 1ère dispo partielle seulement
        if not req.partial_available_mail_sent:
            await resolve_and_notify_availability(
                settings, req, db, candidates=[AvailabilityCandidate(scope="episode", language=None, is_upgrade=False)]
            )


# ---------------------------------------------------------------------------
# Jobs planifiés
# ---------------------------------------------------------------------------
