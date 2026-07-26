"""Instances externes configurees : Sonarr/Radarr/Prowlarr, clients de telechargement, fournisseurs d'email."""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column

from ..crypto import EncryptedText
from .base import Base


class ArrInstance(Base):
    __tablename__ = "arr_instances"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str]  # ex: "Sonarr 4K"
    arr_type: Mapped[str]  # "sonarr" | "radarr" | "prowlarr"
    url: Mapped[str]
    api_key: Mapped[str] = mapped_column(EncryptedText)
    quality_profile_id: Mapped[Optional[int]]
    root_folder: Mapped[Optional[str]]
    minimum_availability: Mapped[str] = mapped_column(default="released")  # radarr only
    enabled: Mapped[bool] = mapped_column(default=True)
    is_default: Mapped[bool] = mapped_column(default=False)
    indexer_ids: Mapped[Optional[str]]  # JSON list d'int, indexeurs à utiliser (null = tous)

class DownloadClient(Base):
    __tablename__ = "download_clients"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str]  # ex: "Seedbox qBittorrent"
    client_type: Mapped[str]  # "qbittorrent" | "transmission"
    url: Mapped[str]
    username: Mapped[Optional[str]]
    password: Mapped[Optional[str]] = mapped_column(EncryptedText)
    category: Mapped[Optional[str]]  # ex: "plex-rss"
    tags: Mapped[Optional[str]]  # comma-separated tags
    is_default: Mapped[bool] = mapped_column(default=False)
    enabled: Mapped[bool] = mapped_column(default=True)

class EmailProvider(Base):
    """Un moyen d'envoyer des emails (SMTP classique, SMTP+OAuth2 Microsoft, ou API Brevo).

    Plusieurs fournisseurs peuvent etre configures et actifs simultanement : l'envoi
    (voir email_providers.py) essaie chaque fournisseur actif par ordre de `priority`
    croissante et bascule sur le suivant en cas d'echec, jusqu'a un envoi reussi.
    """

    __tablename__ = "email_providers"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str]  # ex: "Hotmail perso"
    provider_type: Mapped[str]  # "smtp" | "smtp_oauth2" | "brevo"
    enabled: Mapped[bool] = mapped_column(default=True)
    priority: Mapped[int] = mapped_column(default=0)  # ordre d'essai croissant

    # --- SMTP (provider_type "smtp" et "smtp_oauth2") ---
    smtp_host: Mapped[Optional[str]]
    smtp_port: Mapped[int] = mapped_column(default=587)
    smtp_tls: Mapped[bool] = mapped_column(default=True)
    smtp_user: Mapped[Optional[str]]  # "smtp" uniquement
    smtp_password: Mapped[Optional[str]] = mapped_column(EncryptedText)  # "smtp" uniquement

    # --- SMTP OAuth2 Microsoft ("smtp_oauth2" uniquement) ---
    oauth_tenant: Mapped[str] = mapped_column(default="consumers")
    oauth_client_id: Mapped[Optional[str]]
    oauth_client_secret: Mapped[Optional[str]] = mapped_column(EncryptedText)
    oauth_mailbox: Mapped[Optional[str]]
    oauth_refresh_token: Mapped[Optional[str]] = mapped_column(EncryptedText)
    oauth_access_token: Mapped[Optional[str]] = mapped_column(EncryptedText)
    oauth_token_expires_at: Mapped[Optional[datetime]]

    # --- Brevo ("brevo" uniquement) ---
    brevo_api_key: Mapped[Optional[str]] = mapped_column(EncryptedText)
