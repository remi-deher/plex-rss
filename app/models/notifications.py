"""Journal des envois, jalons et file d'attente des notifications."""

from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..utils import now_utc_naive
from .base import Base


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sent_at: Mapped[datetime] = mapped_column(default=now_utc_naive, index=True)
    event: Mapped[str] = mapped_column(index=True)
    # "email" (défaut, valeur historique) | "discord" | "telegram" | "ntfy" | "gotify".
    # Les canaux push n'étaient jusqu'ici ni journalisés, ni retentés en cas d'échec —
    # une seule erreur réseau perdait la notification sans trace.
    channel: Mapped[str] = mapped_column(default="email")
    recipient: Mapped[str]
    is_admin: Mapped[bool] = mapped_column(default=False)
    media_title: Mapped[Optional[str]]
    media_type: Mapped[Optional[str]]
    success: Mapped[bool] = mapped_column(default=True)
    error_msg: Mapped[Optional[str]]
    req_id: Mapped[Optional[int]]
    # "auto" (défaut, cron/webhook) | "manual" (renvoi déclenché depuis la fiche détail) —
    # affiché dans l'UI pour distinguer un envoi planifié d'un renvoi admin explicite.
    triggered_by: Mapped[str] = mapped_column(default="auto")

    # --- Contexte structuré du jalon (remplace le texte libre "reason" reparsé par regex
    # côté email_service.py) : scope = "movie"|"episode"|"season_start"|"season_complete"|
    # "series_complete" ; language = "vo"|"vf"|None ; is_upgrade = VO->VF ou partiel->complet.
    scope: Mapped[Optional[str]] = mapped_column(default=None)
    language: Mapped[Optional[str]] = mapped_column(default=None)
    is_upgrade: Mapped[bool] = mapped_column(default=False)
    season_number: Mapped[Optional[int]] = mapped_column(default=None)
    episode_number: Mapped[Optional[int]] = mapped_column(default=None)

class NotificationMilestone(Base):
    __tablename__ = "notification_milestones"
    __table_args__ = (
        UniqueConstraint(
            "req_id",
            "plex_user_id",
            "direction",
            "milestone_type",
            "season_number",
            "episode_number",
            name="uq_notification_milestone",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(default=now_utc_naive)
    req_id: Mapped[int]
    plex_user_id: Mapped[str]
    direction: Mapped[str]
    milestone_type: Mapped[str]
    language: Mapped[Optional[str]] = mapped_column(default=None)
    is_upgrade: Mapped[bool] = mapped_column(default=False)
    season_number: Mapped[Optional[int]] = mapped_column(default=None)
    episode_number: Mapped[Optional[int]] = mapped_column(default=None)

class PendingNotification(Base):
    """Notification empilée dans la queue asyncio mais pas encore envoyée.

    Persistée en base pour survivre à un redémarrage/crash de l'app : sans cela, toute
    notification en vol au moment d'un arrêt (déploiement, `docker compose restart`) est
    perdue silencieusement — la ligne est supprimée une fois le worker passé dessus.
    """

    __tablename__ = "pending_notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(default=now_utc_naive)
    event: Mapped[str]
    req_id: Mapped[int] = mapped_column(index=True)
    recipients: Mapped[str]  # JSON list[str]
    reason: Mapped[str] = mapped_column(default="")
