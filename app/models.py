"""
Modèles SQLAlchemy et énumérations métier.

Tables :
- Settings   : configuration globale (Plex, Sonarr, Radarr, SMTP, notifs)
- PlexUser   : utilisateurs Plex surveillés (détectés via RSS ou ajoutés manuellement)
- MediaRequest : demandes de médias issues des watchlists
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Enum
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime
import enum


class Base(DeclarativeBase):
    pass


class WatchlistSource(str, enum.Enum):
    api = "api"
    rss = "rss"


class RequestStatus(str, enum.Enum):
    pending = "pending"          # en attente d'envoi à Sonarr/Radarr
    sent_to_arr = "sent_to_arr"  # transmis, en attente de disponibilité
    available = "available"      # fichier présent dans Sonarr/Radarr
    failed = "failed"            # échec de transmission


class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, default=1)

    # --- Plex ---
    plex_url = Column(String, nullable=True)
    plex_token = Column(String, nullable=True)
    plex_rss_url = Column(String, nullable=True)
    watchlist_source_priority = Column(String, default="api")  # "api" ou "rss"
    watchlist_fallback_enabled = Column(Boolean, default=True)
    poll_interval_minutes = Column(Integer, default=5)

    # --- Sonarr ---
    sonarr_url = Column(String, nullable=True)
    sonarr_api_key = Column(String, nullable=True)
    sonarr_quality_profile_id = Column(Integer, nullable=True)
    sonarr_root_folder = Column(String, nullable=True)
    sonarr_enabled = Column(Boolean, default=True)

    # --- Radarr ---
    radarr_url = Column(String, nullable=True)
    radarr_api_key = Column(String, nullable=True)
    radarr_quality_profile_id = Column(Integer, nullable=True)
    radarr_root_folder = Column(String, nullable=True)
    radarr_enabled = Column(Boolean, default=True)

    # --- Email (SMTP) ---
    smtp_host = Column(String, nullable=True)
    smtp_port = Column(Integer, default=587)
    smtp_user = Column(String, nullable=True)
    smtp_password = Column(String, nullable=True)
    smtp_from = Column(String, nullable=True)
    smtp_tls = Column(Boolean, default=True)
    email_on_request = Column(Boolean, default=True)
    email_on_available = Column(Boolean, default=True)
    email_request_template = Column(Text, nullable=True)    # template Jinja2 HTML custom
    email_available_template = Column(Text, nullable=True)  # template Jinja2 HTML custom

    # --- Notifications push (Discord / Telegram) ---
    # Si l'URL/token est renseigné, les notifications sont envoyées automatiquement.
    discord_webhook_url = Column(String, nullable=True)
    telegram_bot_token = Column(String, nullable=True)
    telegram_chat_id = Column(String, nullable=True)

    # --- Authentification ---
    # Si auth_username est NULL, l'app affiche le wizard de configuration initiale.
    auth_username = Column(String, nullable=True)
    auth_password_hash = Column(String, nullable=True)  # bcrypt hash


class PlexUser(Base):
    __tablename__ = "plex_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plex_user_id = Column(String, unique=True, nullable=False)  # ID hex issu du champ <author> du RSS
    display_name = Column(String, nullable=True)                # nom lisible défini par l'admin
    plex_email = Column(String, nullable=True)
    notification_email = Column(String, nullable=True)          # surcharge l'email SMTP par défaut
    enabled = Column(Boolean, default=True)                     # False = demandes ignorées
    created_at = Column(DateTime, default=datetime.utcnow)


class MediaRequest(Base):
    __tablename__ = "media_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plex_user_id = Column(String, nullable=False)  # ID hex issu du RSS
    plex_user = Column(String, nullable=True)       # display_name résolu au moment de la création
    title = Column(String, nullable=False)
    year = Column(Integer, nullable=True)
    media_type = Column(String, nullable=False)     # "movie" ou "show"

    # Identifiants externes — utilisés pour le lookup dans Sonarr/Radarr
    tmdb_id = Column(String, nullable=True)
    tvdb_id = Column(String, nullable=True)
    imdb_id = Column(String, nullable=True)
    plex_guid = Column(String, nullable=True)

    status = Column(String, default=RequestStatus.pending)
    source = Column(String, nullable=True)    # "api" ou "rss" selon la source du polling
    arr_id = Column(Integer, nullable=True)   # ID interne Sonarr ou Radarr
    arr_slug = Column(String, nullable=True)  # titleSlug (Sonarr) ou tmdbId string (Radarr) pour construire des liens directs

    request_mail_sent = Column(Boolean, default=False)    # évite les doublons d'email de demande
    available_mail_sent = Column(Boolean, default=False)  # évite les doublons d'email de disponibilité

    requested_at = Column(DateTime, default=datetime.utcnow)
    available_at = Column(DateTime, nullable=True)
    poster_url = Column(String, nullable=True)
    overview = Column(Text, nullable=True)
