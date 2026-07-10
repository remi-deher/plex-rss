"""Historique des téléchargements terminés (Sonarr/Radarr/Plex/torrent direct).

Appelé depuis chaque point de détection de disponibilité existant (webhook temps réel,
poll périodique `check_arr_statuses`, suivi torrent direct) au moment précis où une
demande bascule à "available" — pas de scan dédié, pas de log en double pour un même
événement grâce aux garde-fous déjà en place à chaque appelant.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import DownloadHistory, Settings
from ..utils import now_utc_naive

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 90


def record_completed(
    db: Session,
    *,
    title: str,
    year: int | None,
    media_type: str,
    source: str,
    instance_name: str | None = None,
    poster_url: str | None = None,
    request_id: int | None = None,
) -> None:
    db.add(
        DownloadHistory(
            title=title,
            year=year,
            media_type=media_type,
            source=source,
            instance_name=instance_name,
            poster_url=poster_url,
            request_id=request_id,
            completed_at=now_utc_naive(),
        )
    )
    db.commit()


def purge_old_entries(db: Session) -> int:
    settings = db.query(Settings).first()
    days = (settings.notification_log_retention_days if settings else None) or DEFAULT_RETENTION_DAYS
    cutoff = datetime.now() - timedelta(days=days)
    deleted = db.query(DownloadHistory).filter(DownloadHistory.completed_at < cutoff).delete()
    if deleted:
        db.commit()
        logger.info(f"Purge historique téléchargements : {deleted} entrées supprimées (>{days}j)")
    return deleted
