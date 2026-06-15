"""
Modèles SQLAlchemy et énumérations métier.

Tables :
- Settings   : configuration globale (Plex, Sonarr, Radarr, SMTP, notifs)
- PlexUser   : utilisateurs Plex surveillés (détectés via RSS ou ajoutés manuellement)
- MediaRequest : demandes de médias issues des watchlists
"""

import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class WatchlistSource(str, enum.Enum):
    api = "api"
    rss = "rss"


class RequestStatus(str, enum.Enum):
    pending = "pending"
    sent_to_arr = "sent_to_arr"
    available = "available"
    failed = "failed"


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)

    # --- Plex ---
    plex_url: Mapped[Optional[str]]
    plex_token: Mapped[Optional[str]]
    plex_rss_url: Mapped[Optional[str]]
    watchlist_source_priority: Mapped[str] = mapped_column(default="api")
    watchlist_fallback_enabled: Mapped[bool] = mapped_column(default=True)
    poll_interval_minutes: Mapped[int] = mapped_column(default=5)

    # --- Sonarr ---
    sonarr_url: Mapped[Optional[str]]
    sonarr_api_key: Mapped[Optional[str]]
    sonarr_quality_profile_id: Mapped[Optional[int]]
    sonarr_root_folder: Mapped[Optional[str]]
    sonarr_enabled: Mapped[bool] = mapped_column(default=True)

    # --- Radarr ---
    radarr_url: Mapped[Optional[str]]
    radarr_api_key: Mapped[Optional[str]]
    radarr_quality_profile_id: Mapped[Optional[int]]
    radarr_root_folder: Mapped[Optional[str]]
    radarr_enabled: Mapped[bool] = mapped_column(default=True)
    radarr_minimum_availability: Mapped[str] = mapped_column(default="released")

    # --- Email (SMTP) ---
    smtp_host: Mapped[Optional[str]]
    smtp_port: Mapped[int] = mapped_column(default=587)
    smtp_user: Mapped[Optional[str]]
    smtp_password: Mapped[Optional[str]]
    smtp_from: Mapped[Optional[str]]
    smtp_tls: Mapped[bool] = mapped_column(default=True)
    admin_notification_email: Mapped[Optional[str]]
    email_on_request: Mapped[bool] = mapped_column(default=True)
    email_on_available: Mapped[bool] = mapped_column(default=True)
    email_request_template: Mapped[Optional[str]] = mapped_column(Text)
    email_available_template: Mapped[Optional[str]] = mapped_column(Text)
    email_request_subject: Mapped[Optional[str]] = mapped_column(default=None)
    email_available_subject: Mapped[Optional[str]] = mapped_column(default=None)

    # --- Notifications avancées ---
    notification_log_retention_days: Mapped[Optional[int]] = mapped_column(default=None)
    digest_enabled: Mapped[bool] = mapped_column(default=False)
    digest_hour: Mapped[int] = mapped_column(default=8)

    # --- Seer ---
    seer_url: Mapped[Optional[str]]
    seer_api_key: Mapped[Optional[str]]
    seer_enabled: Mapped[bool] = mapped_column(default=False)

    # --- Notifications push (Discord / Telegram) ---
    discord_webhook_url: Mapped[Optional[str]]
    telegram_bot_token: Mapped[Optional[str]]
    telegram_chat_id: Mapped[Optional[str]]

    # --- Authentification ---
    auth_username: Mapped[Optional[str]]
    auth_password_hash: Mapped[Optional[str]]
    api_token: Mapped[Optional[str]]


class PlexUser(Base):
    __tablename__ = "plex_users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plex_user_id: Mapped[str] = mapped_column(unique=True)
    display_name: Mapped[Optional[str]]
    plex_email: Mapped[Optional[str]]
    notification_email: Mapped[Optional[str]]
    notify_admin: Mapped[bool] = mapped_column(default=True)
    notify_on_request: Mapped[Optional[bool]] = mapped_column(default=True)
    notify_on_available: Mapped[Optional[bool]] = mapped_column(default=True)
    notify_digest: Mapped[Optional[bool]] = mapped_column(default=False)
    enabled: Mapped[bool] = mapped_column(default=True)
    discord_webhook_url: Mapped[Optional[str]] = mapped_column(default=None)
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(default=None)
    seer_user_id: Mapped[Optional[int]] = mapped_column(default=None)
    seer_active: Mapped[Optional[bool]] = mapped_column(default=None)
    custom_name: Mapped[Optional[str]] = mapped_column(default=None)
    source: Mapped[Optional[str]] = mapped_column(default=None)
    created_at: Mapped[Optional[datetime]] = mapped_column(default=lambda: datetime.now(timezone.utc))


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sent_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    event: Mapped[str]
    recipient: Mapped[str]
    is_admin: Mapped[bool] = mapped_column(default=False)
    media_title: Mapped[Optional[str]]
    media_type: Mapped[Optional[str]]
    success: Mapped[bool] = mapped_column(default=True)
    error_msg: Mapped[Optional[str]]
    req_id: Mapped[Optional[int]]


class MediaRequest(Base):
    __tablename__ = "media_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plex_user_id: Mapped[str]
    plex_user: Mapped[Optional[str]]
    title: Mapped[str]
    year: Mapped[Optional[int]]
    media_type: Mapped[str]

    tmdb_id: Mapped[Optional[str]]
    tvdb_id: Mapped[Optional[str]]
    imdb_id: Mapped[Optional[str]]
    plex_guid: Mapped[Optional[str]]

    status: Mapped[str] = mapped_column(default=RequestStatus.pending)
    source: Mapped[Optional[str]]
    arr_id: Mapped[Optional[int]]
    arr_slug: Mapped[Optional[str]]

    request_mail_sent: Mapped[bool] = mapped_column(default=False)
    available_mail_sent: Mapped[bool] = mapped_column(default=False)

    requested_at: Mapped[Optional[datetime]] = mapped_column(default=lambda: datetime.now(timezone.utc))
    available_at: Mapped[Optional[datetime]]
    poster_url: Mapped[Optional[str]]
    overview: Mapped[Optional[str]] = mapped_column(Text)
    extra_requesters: Mapped[Optional[str]] = mapped_column(Text)
