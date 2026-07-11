"""
Modèles SQLAlchemy et énumérations métier.

Tables :
- Settings   : configuration globale (Plex, Sonarr, Radarr, SMTP, notifs)
- PlexUser   : utilisateurs Plex surveillés (détectés via RSS ou ajoutés manuellement)
- MediaRequest : demandes de médias issues des watchlists
"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Text, UniqueConstraint, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .crypto import EncryptedText
from .utils import now_utc


class Base(DeclarativeBase):
    pass


class WatchlistSource(str, enum.Enum):
    api = "api"
    rss = "rss"


class RequestStatus(str, enum.Enum):
    pending_approval = "pending_approval"  # demande d'un utilisateur en attente de validation admin
    rejected = "rejected"  # demande refusée par un admin (conservée pour l'historique)
    pending = "pending"
    sent_to_arr = "sent_to_arr"
    available = "available"
    failed = "failed"


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)

    # --- Plex ---
    plex_url: Mapped[Optional[str]]
    plex_token: Mapped[Optional[str]] = mapped_column(EncryptedText)
    plex_rss_url: Mapped[Optional[str]]
    watchlist_source_priority: Mapped[str] = mapped_column(default="api")
    watchlist_fallback_enabled: Mapped[bool] = mapped_column(default=True)
    poll_interval_minutes: Mapped[int] = mapped_column(default=5)
    # Intervalle de polling de la watchlist en secondes (prioritaire sur poll_interval_minutes
    # s'il est défini). Permet un rafraîchissement sous la minute. None → poll_interval_minutes*60.
    poll_interval_seconds: Mapped[Optional[int]] = mapped_column(default=None)

    # --- Sonarr ---
    sonarr_url: Mapped[Optional[str]]
    sonarr_api_key: Mapped[Optional[str]] = mapped_column(EncryptedText)
    sonarr_quality_profile_id: Mapped[Optional[int]]
    sonarr_root_folder: Mapped[Optional[str]]
    sonarr_enabled: Mapped[bool] = mapped_column(default=True)

    # --- Radarr ---
    radarr_url: Mapped[Optional[str]]
    radarr_api_key: Mapped[Optional[str]] = mapped_column(EncryptedText)
    radarr_quality_profile_id: Mapped[Optional[int]]
    radarr_root_folder: Mapped[Optional[str]]
    radarr_enabled: Mapped[bool] = mapped_column(default=True)
    radarr_minimum_availability: Mapped[str] = mapped_column(default="released")

    # --- Email (SMTP) ---
    smtp_host: Mapped[Optional[str]]
    smtp_port: Mapped[int] = mapped_column(default=587)
    smtp_user: Mapped[Optional[str]]
    smtp_password: Mapped[Optional[str]] = mapped_column(EncryptedText)
    smtp_from: Mapped[Optional[str]]
    smtp_tls: Mapped[bool] = mapped_column(default=True)
    admin_notification_email: Mapped[Optional[str]]
    email_on_request: Mapped[bool] = mapped_column(default=True)
    email_on_available: Mapped[bool] = mapped_column(default=True)
    email_on_failure: Mapped[bool] = mapped_column(default=True)
    # 3 templates (un par évènement du catalogue simplifié — voir notification_catalog.py) :
    # "available" fusionne les 10 anciens templates de disponibilité (available_vf,
    # available_vo_tracking, vo_only, vf_available, language_*, partially_available) en un
    # seul, paramétré par le contexte structuré (scope/language/is_upgrade/season/episode)
    # assemblé par email_service._build_subject_phrase()/_build_status_phrase().
    email_request_template: Mapped[Optional[str]] = mapped_column(Text)
    email_available_template: Mapped[Optional[str]] = mapped_column(Text)
    email_upgrade_template: Mapped[Optional[str]] = mapped_column(Text)
    email_failure_template: Mapped[Optional[str]] = mapped_column(Text)
    email_request_subject: Mapped[Optional[str]] = mapped_column(default=None)
    email_available_subject: Mapped[Optional[str]] = mapped_column(default=None)
    email_upgrade_subject: Mapped[Optional[str]] = mapped_column(default=None)
    email_failure_subject: Mapped[Optional[str]] = mapped_column(default=None)
    email_templates_backup: Mapped[Optional[str]] = mapped_column(Text)
    # Coquille email : parties communes (header/footer) + bandeau par évènement
    # (couleur/badge/titre/synopsis), tous éditables via /templates. None = valeur
    # par défaut codée en dur (voir email_service.get_shared_email_parts/get_event_visuals).
    email_header_brand: Mapped[Optional[str]] = mapped_column(default=None)
    email_header_subtitle: Mapped[Optional[str]] = mapped_column(default=None)
    email_footer_template: Mapped[Optional[str]] = mapped_column(Text)
    email_request_accent_color: Mapped[Optional[str]] = mapped_column(default=None)
    email_request_badge_text: Mapped[Optional[str]] = mapped_column(default=None)
    email_request_headline_text: Mapped[Optional[str]] = mapped_column(default=None)
    email_request_show_synopsis: Mapped[Optional[bool]] = mapped_column(default=None)
    email_available_accent_color: Mapped[Optional[str]] = mapped_column(default=None)
    email_available_badge_text: Mapped[Optional[str]] = mapped_column(default=None)
    email_available_headline_text: Mapped[Optional[str]] = mapped_column(default=None)
    email_available_show_synopsis: Mapped[Optional[bool]] = mapped_column(default=None)
    email_upgrade_accent_color: Mapped[Optional[str]] = mapped_column(default=None)
    email_upgrade_badge_text: Mapped[Optional[str]] = mapped_column(default=None)
    email_upgrade_headline_text: Mapped[Optional[str]] = mapped_column(default=None)
    email_upgrade_show_synopsis: Mapped[Optional[bool]] = mapped_column(default=None)
    email_failure_accent_color: Mapped[Optional[str]] = mapped_column(default=None)
    email_failure_badge_text: Mapped[Optional[str]] = mapped_column(default=None)
    email_failure_headline_text: Mapped[Optional[str]] = mapped_column(default=None)
    email_failure_show_synopsis: Mapped[Optional[bool]] = mapped_column(default=None)
    # Bloc affiche/titre/tags/"Demandé par" : mise en page, partagée entre tous les templates
    # (contrairement au bandeau, ce n'est pas du contenu qui varie par évènement).
    email_show_poster: Mapped[Optional[bool]] = mapped_column(default=None)
    email_show_genres: Mapped[Optional[bool]] = mapped_column(default=None)
    email_show_requester: Mapped[Optional[bool]] = mapped_column(default=None)
    email_requester_label: Mapped[Optional[str]] = mapped_column(default=None)
    email_brand_color: Mapped[Optional[str]] = mapped_column(default=None)
    email_show_header_subtitle: Mapped[Optional[bool]] = mapped_column(default=None)
    email_poster_width: Mapped[Optional[int]] = mapped_column(default=None)
    email_media_layout: Mapped[Optional[str]] = mapped_column(default=None)
    email_bg_color: Mapped[Optional[str]] = mapped_column(default=None)
    email_card_bg_color: Mapped[Optional[str]] = mapped_column(default=None)
    email_font_family: Mapped[Optional[str]] = mapped_column(default=None)
    email_card_width: Mapped[Optional[int]] = mapped_column(default=None)
    email_card_border_radius: Mapped[Optional[int]] = mapped_column(default=None)
    email_synopsis_font_size: Mapped[Optional[str]] = mapped_column(default=None)
    email_show_tmdb_link: Mapped[Optional[bool]] = mapped_column(default=None)
    email_show_plex_button: Mapped[Optional[bool]] = mapped_column(default=None)

    # --- Notifications avancées ---
    notification_log_retention_days: Mapped[Optional[int]] = mapped_column(default=None)
    digest_enabled: Mapped[bool] = mapped_column(default=False)
    digest_hour: Mapped[int] = mapped_column(default=8)

    # --- TMDB (catalogue de découverte) ---
    tmdb_api_key: Mapped[Optional[str]] = mapped_column(EncryptedText)

    # --- Seer ---
    seer_url: Mapped[Optional[str]]
    seer_api_key: Mapped[Optional[str]] = mapped_column(EncryptedText)
    seer_enabled: Mapped[bool] = mapped_column(default=False)  # legacy, remplacé par seer_send_requests
    seer_send_requests: Mapped[bool] = mapped_column(default=False)
    seer_fallback_arr: Mapped[bool] = mapped_column(default=True)

    # --- Notifications push (Discord / Telegram) ---
    discord_enabled: Mapped[bool] = mapped_column(default=True)
    discord_webhook_url: Mapped[Optional[str]] = mapped_column(EncryptedText)
    discord_send_request: Mapped[bool] = mapped_column(default=True)
    discord_send_available: Mapped[bool] = mapped_column(default=True)
    discord_send_failure: Mapped[bool] = mapped_column(default=True)
    telegram_enabled: Mapped[bool] = mapped_column(default=True)
    telegram_bot_token: Mapped[Optional[str]] = mapped_column(EncryptedText)
    telegram_chat_id: Mapped[Optional[str]]
    telegram_send_request: Mapped[bool] = mapped_column(default=True)
    telegram_send_available: Mapped[bool] = mapped_column(default=True)
    telegram_send_failure: Mapped[bool] = mapped_column(default=True)

    # --- Notifications push (ntfy / Gotify) ---
    ntfy_enabled: Mapped[bool] = mapped_column(default=True)
    ntfy_url: Mapped[Optional[str]]
    ntfy_token: Mapped[Optional[str]] = mapped_column(EncryptedText)
    ntfy_send_request: Mapped[bool] = mapped_column(default=True)
    ntfy_send_available: Mapped[bool] = mapped_column(default=True)
    ntfy_send_failure: Mapped[bool] = mapped_column(default=True)
    gotify_enabled: Mapped[bool] = mapped_column(default=True)
    gotify_url: Mapped[Optional[str]]
    gotify_token: Mapped[Optional[str]] = mapped_column(EncryptedText)
    gotify_send_request: Mapped[bool] = mapped_column(default=True)
    gotify_send_available: Mapped[bool] = mapped_column(default=True)
    gotify_send_failure: Mapped[bool] = mapped_column(default=True)

    # --- Poll history retention ---
    poll_history_retention_days: Mapped[Optional[int]] = mapped_column(default=None)

    # --- Authentification ---
    auth_username: Mapped[Optional[str]]
    auth_password_hash: Mapped[Optional[str]]
    api_token: Mapped[Optional[str]] = mapped_column(EncryptedText)
    api_token_scopes: Mapped[Optional[str]] = mapped_column(Text, default=None)
    webhook_secret: Mapped[Optional[str]] = mapped_column(EncryptedText)
    totp_secret: Mapped[Optional[str]] = mapped_column(EncryptedText)
    totp_enabled: Mapped[bool] = mapped_column(default=False)
    default_locale: Mapped[str] = mapped_column(default="fr")

    # --- Approbation des demandes ---
    # Si True, une demande d'un utilisateur 'user' non auto-approuvé attend la validation
    # d'un admin (statut pending_approval) avant d'être envoyée à *arr. Les admins et les
    # utilisateurs avec auto_approve=True ne sont jamais bloqués.
    require_approval: Mapped[bool] = mapped_column(default=False)

    # --- Sécurité réseau ---
    plex_verify_ssl: Mapped[bool] = mapped_column(default=True)

    # --- Torrent settings ---
    torrent_required_keywords: Mapped[Optional[str]]
    torrent_forbidden_keywords: Mapped[Optional[str]]
    torrent_min_size_gb: Mapped[Optional[float]]
    torrent_max_size_gb: Mapped[Optional[float]]
    torrent_ratio_limit: Mapped[Optional[float]]
    torrent_seed_time_limit_hours: Mapped[Optional[int]]
    torrent_auto_delete_files: Mapped[bool] = mapped_column(default=True)

    # --- VFF (audit / suivi des pistes françaises) ---
    # Actif par défaut : le suivi VO/VF est la priorité par défaut (voir plan de session),
    # le mail générique "Disponible sur Plex" devient l'exception (forçage par utilisateur).
    vff_enabled: Mapped[bool] = mapped_column(default=True)
    # Bibliothèques Plex à inspecter, JSON: [{"name": "Films", "kind": "movie"},
    # {"name": "Animes", "kind": "series"}]. Null → auto-détection des sections.
    vff_libraries: Mapped[Optional[str]] = mapped_column(Text)
    # Intervalle du re-scan des médias suivis en VO (minutes)
    vff_recheck_interval_minutes: Mapped[int] = mapped_column(default=360)
    # Déclencher une recherche Sonarr/Radarr quand un média est suivi en VO seule
    vff_auto_search: Mapped[bool] = mapped_column(default=False)
    email_on_vf_available: Mapped[bool] = mapped_column(default=True)

    # --- Disponibilité : réglages simplifiés à 2 axes (remplace l'ancien enchevêtrement
    # tracking_mode "language"/"simple"/"classic" + 3 modes de notif séparés + fréquence
    # partielle — voir migration 0055_simplify_notify_settings) ---
    # notify_language : suit la distinction VO/VF (True) ou notification générique sans
    # distinction de langue (False, remplace l'ancien mode "classic"/"simple").
    movie_notify_language: Mapped[bool] = mapped_column(default=True)
    series_notify_language: Mapped[bool] = mapped_column(default=True)
    # notify_granularity (séries uniquement) : "minimal" (une seule notif à la disponibilité
    # finale), "jalons" (début/fin de saison + améliorations VF — défaut), "tout" (chaque
    # épisode individuellement).
    series_notify_granularity: Mapped[str] = mapped_column(default="jalons")


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
    created_at: Mapped[Optional[datetime]] = mapped_column(default=now_utc)

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
    # puis quand la VF arrive. Distinction par type pour éviter les faux positifs
    # (ex : animes japonais en VO à leur sortie).
    notify_vf_movie: Mapped[Optional[bool]] = mapped_column(default=True)
    notify_vf_series: Mapped[Optional[bool]] = mapped_column(default=True)
    notify_vf_anime: Mapped[Optional[bool]] = mapped_column(default=False)

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
    created_at: Mapped[datetime] = mapped_column(default=now_utc)


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sent_at: Mapped[datetime] = mapped_column(default=now_utc, index=True)
    event: Mapped[str] = mapped_column(index=True)
    recipient: Mapped[str]
    is_admin: Mapped[bool] = mapped_column(default=False)
    media_title: Mapped[Optional[str]]
    media_type: Mapped[Optional[str]]
    success: Mapped[bool] = mapped_column(default=True)
    error_msg: Mapped[Optional[str]]
    req_id: Mapped[Optional[int]]

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
    created_at: Mapped[datetime] = mapped_column(default=now_utc)
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
    created_at: Mapped[datetime] = mapped_column(default=now_utc)
    event: Mapped[str]
    req_id: Mapped[int] = mapped_column(index=True)
    recipients: Mapped[str]  # JSON list[str]
    reason: Mapped[str] = mapped_column(default="")


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ip_address: Mapped[str]
    username: Mapped[Optional[str]] = mapped_column(default=None)
    attempted_at: Mapped[datetime] = mapped_column(default=now_utc)
    success: Mapped[bool] = mapped_column(default=False)
    reason: Mapped[Optional[str]] = mapped_column(default=None)


class MediaIssue(Base):
    __tablename__ = "media_issues"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(default=now_utc)
    status: Mapped[str] = mapped_column(default="open")
    issue_type: Mapped[str]
    message: Mapped[Optional[str]] = mapped_column(Text, default=None)
    reporter_plex_user_id: Mapped[Optional[str]] = mapped_column(default=None)
    reporter_name: Mapped[Optional[str]] = mapped_column(default=None)
    library_item_id: Mapped[Optional[int]] = mapped_column(default=None)
    request_id: Mapped[Optional[int]] = mapped_column(default=None)
    title: Mapped[str]
    media_type: Mapped[str]
    tmdb_id: Mapped[Optional[str]] = mapped_column(default=None)
    tvdb_id: Mapped[Optional[str]] = mapped_column(default=None)
    imdb_id: Mapped[Optional[str]] = mapped_column(default=None)
    admin_note: Mapped[Optional[str]] = mapped_column(Text, default=None)


class PollHistory(Base):
    __tablename__ = "poll_history"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job: Mapped[str]  # "watchlist" | "arr_status"
    started_at: Mapped[datetime]
    duration_ms: Mapped[Optional[int]]
    items_processed: Mapped[int] = mapped_column(default=0)
    new_requests: Mapped[int] = mapped_column(default=0)
    newly_available: Mapped[int] = mapped_column(default=0)
    errors: Mapped[int] = mapped_column(default=0)
    error_detail: Mapped[Optional[str]]


class DownloadHistory(Base):
    """Trace un téléchargement terminé et importé (Sonarr/Radarr/Plex/torrent direct).

    Contrairement à la file d'attente *arr (transitoire, un item en disparaît dès qu'il
    est importé), cette table conserve un historique consultable des téléchargements
    passés. Alimentée aux points de détection de disponibilité existants (webhook temps
    réel, poll périodique `check_arr_statuses`, suivi torrent direct) — pas de scan dédié.
    """

    __tablename__ = "download_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str]
    year: Mapped[Optional[int]]
    media_type: Mapped[str]
    # Origine de la détection : "sonarr" | "radarr" | "plex" | "torrent"
    source: Mapped[str]
    instance_name: Mapped[Optional[str]]
    poster_url: Mapped[Optional[str]]
    request_id: Mapped[Optional[int]]
    completed_at: Mapped[datetime] = mapped_column(default=now_utc)


class MediaRequest(Base):
    __tablename__ = "media_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plex_user_id: Mapped[str] = mapped_column(index=True)
    plex_user: Mapped[Optional[str]]
    title: Mapped[str]
    year: Mapped[Optional[int]]
    media_type: Mapped[str]

    tmdb_id: Mapped[Optional[str]] = mapped_column(index=True)
    tvdb_id: Mapped[Optional[str]] = mapped_column(index=True)
    imdb_id: Mapped[Optional[str]]
    plex_guid: Mapped[Optional[str]]

    status: Mapped[str] = mapped_column(default=RequestStatus.pending, index=True)
    source: Mapped[Optional[str]]
    arr_id: Mapped[Optional[int]]
    arr_slug: Mapped[Optional[str]]

    request_mail_sent: Mapped[bool] = mapped_column(default=False)
    available_mail_sent: Mapped[bool] = mapped_column(default=False)

    requested_at: Mapped[Optional[datetime]] = mapped_column(default=now_utc)
    available_at: Mapped[Optional[datetime]]
    poster_url: Mapped[Optional[str]]
    overview: Mapped[Optional[str]] = mapped_column(Text)
    extra_requesters: Mapped[Optional[str]] = mapped_column(Text)

    # Cache de la prochaine date de sortie connue (rempli par check_arr_statuses,
    # consommé par /api/upcoming sans appel réseau supplémentaire).
    next_release_at: Mapped[Optional[datetime]]
    next_release_label: Mapped[Optional[str]]

    # --- Approbation (demandes des utilisateurs 'user') ---
    # Renseignés quand une demande passe par la file de validation admin.
    approved_by: Mapped[Optional[str]] = mapped_column(default=None)  # plex_user_id de l'admin
    approved_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    rejected_reason: Mapped[Optional[str]] = mapped_column(default=None)

    # Instance tracking
    arr_instance_id: Mapped[Optional[int]] = mapped_column(index=True)
    download_client_id: Mapped[Optional[int]]
    torrent_hash: Mapped[Optional[str]] = mapped_column(index=True)

    # --- VFF : état de la piste française au moment de la disponibilité ---
    # None = pas encore analysé ; True = VF présente ; False = VO uniquement (suivi actif)
    has_vf: Mapped[Optional[bool]] = mapped_column(default=None, index=True)
    # Catégorie VFF ("movie" | "series" | "anime") déterminée par la bibliothèque Plex
    vf_category: Mapped[Optional[str]] = mapped_column(default=None)
    vf_checked_at: Mapped[Optional[datetime]]
    vf_available_at: Mapped[Optional[datetime]]
    vf_available_mail_sent: Mapped[bool] = mapped_column(default=False)
    vo_only_mail_sent: Mapped[bool] = mapped_column(default=False)

    # Granularité VF pour les séries (non pertinent pour les films) : distingue une
    # série sans aucun épisode VF d'une série avec quelques épisodes VF épars, ou avec
    # au moins une saison entière en VF (sans être complète pour autant). Calculé à
    # partir du cache par épisode (vf_episode_status) à chaque scan.
    # Valeurs : None (film/pas encore analysé) | "none" | "episode_partial" | "season_partial"
    vf_granularity: Mapped[Optional[str]] = mapped_column(default=None)

    # Lien vers le LibraryItem correspondant, une fois synchronisé depuis Plex (pas de
    # contrainte FK, convention du reste du modèle). Une fois lié, has_vf n'est plus
    # scanné indépendamment : il est propagé depuis le LibraryItem (source de vérité
    # unique), pour éviter deux scans Plex divergents du même média.
    library_item_id: Mapped[Optional[int]] = mapped_column(index=True)

    # --- Disponibilité partielle (séries en cours de diffusion, Sonarr uniquement) ---
    # episodes_available_count : épisodes avec un fichier sur disque (episodeFileCount)
    # episodes_aired_count     : épisodes déjà diffusés à ce jour (episodeCount Sonarr)
    # episodes_total_count     : total de la série, diffusés + à venir (totalEpisodeCount)
    # Une série est "complète" quand episodes_available_count >= episodes_total_count.
    episodes_available_count: Mapped[Optional[int]] = mapped_column(default=None)
    episodes_aired_count: Mapped[Optional[int]] = mapped_column(default=None)
    episodes_total_count: Mapped[Optional[int]] = mapped_column(default=None)
    # Anti-doublon "milestones" : une seule notif à la 1ère dispo partielle.
    partial_available_mail_sent: Mapped[bool] = mapped_column(default=False)
    # Dernier episodes_available_count notifié en mode "every_episode" (évite de
    # renvoyer une notif si le compte n'a pas progressé depuis le dernier cycle).
    last_notified_episode_count: Mapped[Optional[int]] = mapped_column(default=None)

    # Présent dans la file de téléchargement Sonarr/Radarr au dernier cycle de poll
    # (check_arr_statuses). Sert à distinguer un vrai bug d'indexation Plex ("anomalie")
    # d'un média encore en cours de téléchargement/import (ex: série avec des épisodes
    # déjà disponibles pendant que d'autres sont encore en file de téléchargement).
    is_downloading: Mapped[bool] = mapped_column(default=False)


class LibraryItem(Base):
    """Média réellement présent dans la bibliothèque Plex (issu de la synchronisation).

    Séparé de `MediaRequest` : un élément de bibliothèque n'a pas de demandeur ni de
    flux de demande — il est simplement *présent*. Porte l'état VF/VFF du média.
    Le rapprochement avec les demandes se fait à l'affichage (vue Bibliothèque = union).
    """

    __tablename__ = "library_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str]
    year: Mapped[Optional[int]]
    media_type: Mapped[str]

    tmdb_id: Mapped[Optional[str]]
    tvdb_id: Mapped[Optional[str]]
    imdb_id: Mapped[Optional[str]]
    plex_guid: Mapped[Optional[str]]

    poster_url: Mapped[Optional[str]]
    overview: Mapped[Optional[str]] = mapped_column(Text)
    added_at: Mapped[Optional[datetime]]

    # Rapprochement Sonarr / Radarr (badges de suivi)
    arr_instance_id: Mapped[Optional[int]]
    arr_id: Mapped[Optional[int]]
    arr_slug: Mapped[Optional[str]]

    # --- État VF / VFF ---
    # None = pas encore analysé ; True = VF présente ; False = VO uniquement
    has_vf: Mapped[Optional[bool]] = mapped_column(default=None)
    vf_category: Mapped[Optional[str]] = mapped_column(default=None)
    vf_checked_at: Mapped[Optional[datetime]]
    vf_available_at: Mapped[Optional[datetime]]
    # Granularité VF pour les séries — voir MediaRequest.vf_granularity.
    vf_granularity: Mapped[Optional[str]] = mapped_column(default=None)

    created_at: Mapped[Optional[datetime]] = mapped_column(default=now_utc)
    updated_at: Mapped[Optional[datetime]] = mapped_column(default=now_utc)


class VfEpisodeStatus(Base):
    """Cache du statut VF par épisode, pour éviter de re-scanner Plex à chaque cycle.

    Une série suivie (MediaRequest ou LibraryItem) peut avoir des saisons entières en VO,
    d'autres complètes en VF, et une saison en cours de doublage (VF qui sort épisode par
    épisode, en retard sur la sortie VO). Sans ce cache, chaque re-scan (scheduler ou
    modale "détail VF") interroge Plex pour TOUS les épisodes, y compris ceux déjà
    confirmés VF lors d'un scan précédent — une fois qu'un épisode a une VF, elle ne
    disparaît pas, donc il n'y a jamais besoin de le re-vérifier.

    `source_type` + `source_id` référencent soit une MediaRequest ("request"), soit un
    LibraryItem ("library_item") — pas de vraie FK car un même épisode ne peut être
    rattaché qu'à une seule des deux tables à un instant donné, et la relation se fait
    par titre/identifiants externes plutôt que par clé étrangère stricte.
    """

    __tablename__ = "vf_episode_status"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", "season_number", "episode_number", name="uq_vf_episode"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_type: Mapped[str]
    source_id: Mapped[int]
    season_number: Mapped[int]
    episode_number: Mapped[int]
    has_vf: Mapped[bool] = mapped_column(default=False)
    checked_at: Mapped[Optional[datetime]]


class VfCategory(str, enum.Enum):
    """Type de média du point de vue VFF, pour cibler les notifications.

    - movie  : film (bibliothèque de type « movie »)
    - series : série classique
    - anime  : série d'une bibliothèque marquée comme animes (VO japonaise fréquente)
    """

    movie = "movie"
    series = "series"
    anime = "anime"


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


class SearchCache(Base):
    __tablename__ = "search_cache"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    query: Mapped[str]
    category: Mapped[Optional[str]]  # "movie" | "tv"
    results_json: Mapped[str] = mapped_column(Text)
    cached_at: Mapped[datetime] = mapped_column(default=now_utc)
