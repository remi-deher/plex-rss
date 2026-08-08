"""Utilisateurs Plex, authentification et tentatives de connexion."""

from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..crypto import EncryptedText
from ..utils import now_utc_naive
from .base import Base


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
    created_at: Mapped[Optional[datetime]] = mapped_column(default=now_utc_naive)

    # --- Authentification par utilisateur (login Plex SSO) ---
    # role : "admin" (accès total) ou "user" (Discover + ses propres demandes).
    role: Mapped[str] = mapped_column(default="user")
    # can_login : autorise ce compte Plex à se connecter au portail (gate admin).
    can_login: Mapped[bool] = mapped_column(default=True)
    # UUID stable du compte Plex (plex.tv /api/v2/user → uuid), pour un rattachement
    # fiable indépendant du username (qui peut changer). Null pour les users legacy.
    plex_account_uuid: Mapped[Optional[str]] = mapped_column(default=None)
    avatar_url: Mapped[Optional[str]] = mapped_column(default=None)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    # auto_approve : si True, les demandes de cet utilisateur partent directement
    # vers *arr sans validation admin (même quand require_approval est actif).
    auto_approve: Mapped[bool] = mapped_column(default=False)
    locale: Mapped[Optional[str]] = mapped_column(default=None)

    # Routing
    sonarr_instance_id: Mapped[Optional[int]]
    radarr_instance_id: Mapped[Optional[int]]

    # --- VFF : notifications par type de média ---
    # Prévenir cet utilisateur quand un média devient dispo mais uniquement en VO,
    # puis quand la VF arrive.
    notify_vf_movie: Mapped[Optional[bool]] = mapped_column(default=True)
    notify_vf_series: Mapped[Optional[bool]] = mapped_column(default=True)

    # Surcharge par utilisateur des réglages globaux Settings.movie_notify_language /
    # series_notify_language / series_notify_granularity. None = hérite du réglage global.
    movie_notify_language: Mapped[Optional[bool]] = mapped_column(default=None)
    series_notify_language: Mapped[Optional[bool]] = mapped_column(default=None)
    series_notify_granularity: Mapped[Optional[str]] = mapped_column(default=None)

    # --- Authentification locale & 2FA ---
    password_hash: Mapped[Optional[str]] = mapped_column(default=None)
    totp_secret: Mapped[Optional[str]] = mapped_column(EncryptedText, default=None)
    totp_enabled: Mapped[bool] = mapped_column(default=False)

class PasskeyCredential(Base):
    __tablename__ = "passkey_credentials"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("plex_users.id", ondelete="CASCADE"), nullable=False)
    credential_id: Mapped[str] = mapped_column(unique=True, nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    sign_count: Mapped[int] = mapped_column(default=0, nullable=False)
    name: Mapped[str] = mapped_column(default="Passkey")
    created_at: Mapped[datetime] = mapped_column(default=now_utc_naive)

class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ip_address: Mapped[str]
    username: Mapped[Optional[str]] = mapped_column(default=None)
    attempted_at: Mapped[datetime] = mapped_column(default=now_utc_naive)
    success: Mapped[bool] = mapped_column(default=False)
    reason: Mapped[Optional[str]] = mapped_column(default=None)
