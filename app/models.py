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

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, validates

from .crypto import EncryptedText
from .utils import now_utc_naive


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
    # Série en cours de diffusion (Sonarr) : au moins un épisode a un fichier, mais pas
    # tous — distinct de `available` (série complète) pour ne pas afficher un badge
    # "Disponible" trompeur tant qu'il manque des épisodes. Jamais utilisé pour les films.
    partially_available = "partially_available"
    failed = "failed"


class FulfillmentStatus(str, enum.Enum):
    """Etat technique d'execution, distinct de la decision metier de la demande."""

    not_submitted = "not_submitted"
    awaiting_submission = "awaiting_submission"
    submitted = "submitted"
    queued = "queued"
    downloading = "downloading"
    importing = "importing"
    awaiting_plex = "awaiting_plex"
    partially_available = "partially_available"
    completed = "completed"
    failed = "failed"
    removed = "removed"


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
    # Intervalle du cycle de vérification de disponibilité *arr (check_arr_statuses), en
    # secondes — réglable en heures/minutes/secondes depuis l'onglet Taches planifiees.
    # Existait auparavant comme "arr_poll_interval_hours" côté API/UI sans colonne réelle
    # derrière (setattr silencieusement perdu au commit) — jamais branché sur le job, qui
    # tournait toujours toutes les 15 min en dur (voir app/jobs.py:job_arr_statuses).
    arr_poll_interval_seconds: Mapped[int] = mapped_column(default=900)

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
    email_enabled: Mapped[bool] = mapped_column(default=True)
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
    email_correction_template: Mapped[Optional[str]] = mapped_column(Text)
    email_request_subject: Mapped[Optional[str]] = mapped_column(default=None)
    email_available_subject: Mapped[Optional[str]] = mapped_column(default=None)
    email_episode_available_template: Mapped[Optional[str]] = mapped_column(Text)
    email_episode_available_subject: Mapped[Optional[str]] = mapped_column(default=None)
    email_season_started_template: Mapped[Optional[str]] = mapped_column(Text)
    email_season_started_subject: Mapped[Optional[str]] = mapped_column(default=None)
    email_season_partial_template: Mapped[Optional[str]] = mapped_column(Text)
    email_season_partial_subject: Mapped[Optional[str]] = mapped_column(default=None)
    email_season_complete_template: Mapped[Optional[str]] = mapped_column(Text)
    email_season_complete_subject: Mapped[Optional[str]] = mapped_column(default=None)
    email_series_partial_template: Mapped[Optional[str]] = mapped_column(Text)
    email_series_partial_subject: Mapped[Optional[str]] = mapped_column(default=None)
    email_series_complete_template: Mapped[Optional[str]] = mapped_column(Text)
    email_series_complete_subject: Mapped[Optional[str]] = mapped_column(default=None)
    email_upgrade_subject: Mapped[Optional[str]] = mapped_column(default=None)
    email_failure_subject: Mapped[Optional[str]] = mapped_column(default=None)
    email_correction_subject: Mapped[Optional[str]] = mapped_column(default=None)
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
    email_correction_accent_color: Mapped[Optional[str]] = mapped_column(default=None)
    email_correction_badge_text: Mapped[Optional[str]] = mapped_column(default=None)
    email_correction_headline_text: Mapped[Optional[str]] = mapped_column(default=None)
    email_correction_show_synopsis: Mapped[Optional[bool]] = mapped_column(default=None)
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
    # Suspension globale durable, y compris sans Redis.
    notification_hold_enabled: Mapped[bool] = mapped_column(default=False)
    digest_hour: Mapped[int] = mapped_column(default=8)
    digest_minute: Mapped[int] = mapped_column(default=0)

    # Frequence (en heures) du scan Plex complet ("plex-sync") -- un intervalle
    # periodique plutot qu'une heure murale fixe (abandonnee : plus simple a régler,
    # coherent avec les autres taches planifiees de type "toutes les N").
    plex_sync_interval_hours: Mapped[int] = mapped_column(default=24)
    # Frequence (en minutes) du scan Plex incremental ("plex-sync-recent", medias
    # recemment ajoutes).
    plex_sync_recent_interval_minutes: Mapped[int] = mapped_column(default=5)

    # Filigrane (watermark) du dernier scan Plex incremental reussi ("plex-sync-recent",
    # voir sync_plex_media_recent) -- persiste en base pour survivre a un redemarrage du
    # worker (sinon on perdrait la trace et on re-scannerait tout, ou pire, on sauterait
    # une fenetre de temps).
    plex_recent_sync_last_at: Mapped[Optional[datetime]] = mapped_column(default=None)

    # --- TMDB (catalogue de découverte) ---
    tmdb_api_key: Mapped[Optional[str]] = mapped_column(EncryptedText)
    tmdb_enabled: Mapped[bool] = mapped_column(default=True)

    # --- Seer ---
    seer_url: Mapped[Optional[str]]
    seer_api_key: Mapped[Optional[str]] = mapped_column(EncryptedText)
    # Switch général : False = Seer totalement ignoré (aucune API appelée).
    seer_enabled: Mapped[bool] = mapped_column(default=False)
    # "observer" : Seer n'est qu'une source d'information (sync users/demandes, statut
    # affiché) — la soumission et la disponibilité restent 100 % pilotées par *arr/Plex.
    # "actor" : Seer est en plus la cible de soumission prioritaire et son statut
    # participe à la détection de disponibilité.
    seer_mode: Mapped[str] = mapped_column(default="observer")
    # Dérivé (= seer_enabled and seer_mode == "actor"), maintenu en écriture par
    # settings_api pour les consommateurs existants (library_api, users_api, metrics…).
    seer_send_requests: Mapped[bool] = mapped_column(default=False)
    seer_fallback_arr: Mapped[bool] = mapped_column(default=True)
    seer_suppress_notifications: Mapped[bool] = mapped_column(default=True)

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

    # URL publique de l'instance (ex: https://plexarr.mondomaine.fr), utilisee pour
    # construire des liens absolus dans des contextes sans requete HTTP entrante (les
    # jobs planifies qui envoient les emails n'ont pas de "page courante" dont deriver
    # une URL) -- typiquement le lien vers /privacy dans le pied de page des emails.
    public_base_url: Mapped[Optional[str]] = mapped_column(default=None)

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
    # La suppression des donnees est explicitement opt-in : le fichier peut etre celui
    # que Plex lit directement, particulierement pour la voie torrent sans *arr.
    torrent_auto_delete_files: Mapped[bool] = mapped_column(default=False)
    # "arr" | "plex" | "hybrid" (Plex puis repli *arr apres delai).
    availability_confirmation_mode: Mapped[str] = mapped_column(default="hybrid")
    availability_confirmation_timeout_minutes: Mapped[int] = mapped_column(default=30)

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
    created_at: Mapped[datetime] = mapped_column(default=now_utc_naive)


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


class AdminActionLog(Base):
    __tablename__ = "admin_action_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(default=now_utc_naive, index=True)
    action: Mapped[str] = mapped_column(index=True)
    actor_user_id: Mapped[Optional[int]] = mapped_column(default=None)
    actor_name: Mapped[Optional[str]] = mapped_column(default=None)
    summary: Mapped[str]
    target_count: Mapped[int] = mapped_column(default=0)
    details: Mapped[Optional[str]] = mapped_column(Text, default=None)


class DeletedMediaLog(Base):
    """Trace d'une suppression volontaire par un admin (demande ou orpheline arr).

    Sert de garde-fou contre le retour silencieux d'un média qu'un admin a
    délibérément retiré : tant qu'une entrée existe ici pour un tmdb_id/tvdb_id/
    imdb_id donné, toute nouvelle demande pour ce média (watchlist, requête
    manuelle) est forcée en `pending_approval`, même si l'auto-approbation est
    activée — voir `requests_api.was_deleted_by_admin` et ses appelants.

    Volontairement absent de `MediaRequest` (suppression physique, pas de soft
    delete) : convertir toute la table en soft-delete aurait exigé de retoucher
    toutes les requêtes existantes qui supposent une ligne active (liste,
    compteurs, arr_tracker...) pour un gain limité au seul cas visé ici.
    """

    __tablename__ = "deleted_media_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    media_type: Mapped[str]
    tmdb_id: Mapped[Optional[str]] = mapped_column(index=True)
    tvdb_id: Mapped[Optional[str]] = mapped_column(index=True)
    imdb_id: Mapped[Optional[str]] = mapped_column(index=True)
    title: Mapped[str]
    deleted_at: Mapped[datetime] = mapped_column(default=now_utc_naive)
    deleted_by: Mapped[Optional[str]] = mapped_column(default=None)


class DiagnosticEvent(Base):
    """Événement persistant du parcours Demande → Arr → Plex → Notification."""

    __tablename__ = "diagnostic_events"
    __table_args__ = (
        Index("ix_diagnostic_events_request_created", "request_id", "created_at"),
        Index("ix_diagnostic_events_category_created", "category", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(default=now_utc_naive, index=True)
    request_id: Mapped[Optional[int]] = mapped_column(index=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(index=True)
    category: Mapped[str] = mapped_column(index=True)
    action: Mapped[str]
    status: Mapped[str] = mapped_column(default="success")
    title: Mapped[Optional[str]]
    media_type: Mapped[Optional[str]]
    source: Mapped[Optional[str]]
    message: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[Optional[str]] = mapped_column(Text, default=None)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ip_address: Mapped[str]
    username: Mapped[Optional[str]] = mapped_column(default=None)
    attempted_at: Mapped[datetime] = mapped_column(default=now_utc_naive)
    success: Mapped[bool] = mapped_column(default=False)
    reason: Mapped[Optional[str]] = mapped_column(default=None)


class MediaIssue(Base):
    __tablename__ = "media_issues"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(default=now_utc_naive)
    updated_at: Mapped[datetime] = mapped_column(default=now_utc_naive)
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


class JobRunLog(Base):
    """Historique générique d'exécution des tâches planifiées (app/jobs.py:_run).

    Contrairement à `PollHistory` (spécifique à watchlist/arr_status, avec des colonnes
    métier dédiées), cette table couvre TOUTES les tâches planifiées de façon uniforme
    (nom + statut + durée + erreur) — alimente l'onglet Réglages > Tâches planifiées.
    Un run "not_due" (verrou Redis d'intervalle non expiré) n'est PAS journalisé ici :
    seules les exécutions réelles (succès ou échec) le sont, sans quoi cette table
    grossirait à chaque tick de cron plutôt qu'à chaque exécution effective.
    """

    __tablename__ = "job_run_logs"
    __table_args__ = (Index("ix_job_run_logs_job_started", "job", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job: Mapped[str]
    started_at: Mapped[datetime]
    duration_ms: Mapped[Optional[int]]
    status: Mapped[str]  # "complete" | "failed"
    error: Mapped[Optional[str]]


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
    completed_at: Mapped[datetime] = mapped_column(default=now_utc_naive)


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
    diagnostic_context: Mapped[Optional[str]] = mapped_column(Text, default=None)

    status: Mapped[str] = mapped_column(default=RequestStatus.pending, index=True)
    # Etat technique du traitement. `status` reste l'etat metier/API historique : les
    # deux colonnes sont volontairement separees afin que "demande acceptee" ne soit
    # plus confondu avec "telechargement en cours" ou "attente d'indexation Plex".
    fulfillment_status: Mapped[str] = mapped_column(
        default=FulfillmentStatus.not_submitted, index=True
    )
    fulfillment_updated_at: Mapped[Optional[datetime]] = mapped_column(default=now_utc_naive)
    fulfillment_error: Mapped[Optional[str]] = mapped_column(Text, default=None)
    source: Mapped[Optional[str]]
    arr_id: Mapped[Optional[int]]
    arr_slug: Mapped[Optional[str]]
    # Horodatage de la première transition vers "sent_to_arr" (validation par Radarr/
    # Sonarr) — distinct de `requested_at` (création de la demande, peut être bien plus
    # tôt si elle a d'abord attendu une approbation admin). Rempli automatiquement via
    # `_stamp_arr_processed` ci-dessous plutôt qu'à chaque site d'assignation de statut
    # (une dizaine, dispersés dans webhook/watchlist_poller/arr_api/seer_sync/...).
    arr_processed_at: Mapped[Optional[datetime]] = mapped_column(default=None)

    request_mail_sent: Mapped[bool] = mapped_column(default=False)
    available_mail_sent: Mapped[bool] = mapped_column(default=False)
    # Contrairement à request_mail_sent/available_mail_sent, ce flag doit être remis à False
    # quand la demande repart en pending (retry manuel/auto) : une nouvelle tentative qui
    # échoue à nouveau doit pouvoir renotifier. Voir requests_api.py (retry*) et
    # watchlist_poller.py (reset au succès).
    failure_mail_sent: Mapped[bool] = mapped_column(default=False)

    # True si `requested_at` (date réelle d'ajout à la watchlist Plex, via <pubDate> RSS ou
    # l'API) dépassait déjà 24h au moment où l'app a détecté cet item — cas d'un vieil item
    # qui ressort dans le flux RSS (fenêtre limitée à 50 entrées, voir plex_rss.py) longtemps
    # après son ajout réel. Décidé une seule fois à la création : évite de couper les mails
    # "disponible" de téléchargements légitimes qui prennent simplement plus de 24h.
    notify_suppressed: Mapped[bool] = mapped_column(default=False)

    requested_at: Mapped[Optional[datetime]] = mapped_column(default=now_utc_naive)
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
    torrent_name: Mapped[Optional[str]] = mapped_column(default=None)
    torrent_content_path: Mapped[Optional[str]] = mapped_column(Text, default=None)
    torrent_completed_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    torrent_import_verified_at: Mapped[Optional[datetime]] = mapped_column(default=None)

    # --- VFF : état de la piste française au moment de la disponibilité ---
    # None = pas encore analysé ; True = VF présente ; False = VO uniquement (suivi actif)
    has_vf: Mapped[Optional[bool]] = mapped_column(default=None, index=True)
    # Catégorie VFF ("movie" | "series" | "anime") déterminée par la bibliothèque Plex
    vf_category: Mapped[Optional[str]] = mapped_column(default=None)
    vf_checked_at: Mapped[Optional[datetime]]
    vf_available_at: Mapped[Optional[datetime]]
    vf_available_mail_sent: Mapped[bool] = mapped_column(default=False)
    vo_only_mail_sent: Mapped[bool] = mapped_column(default=False)
    # True = ne plus jamais rescanner cette demande pour une éventuelle VF (posé
    # explicitement en clôturant une demande VO — voir requests_api.mark_request_processed).
    # Sans ce flag, une demande VO reste indéfiniment candidate au scan périodique
    # (check_vf_statuses) tant que has_vf n'est pas True.
    vf_tracking_disabled: Mapped[bool] = mapped_column(default=False)

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

    @validates("status")
    def _stamp_arr_processed(self, key, value):
        if value == RequestStatus.sent_to_arr and self.status != RequestStatus.sent_to_arr:
            self.arr_processed_at = now_utc_naive()
        # Filet de compatibilite pour les imports/constructeurs historiques. Les
        # transitions applicatives passent par request_lifecycle, mais une ligne creee
        # avec un statut explicite ne doit jamais naitre avec un etat technique incoherent.
        compatibility = {
            RequestStatus.pending_approval: FulfillmentStatus.not_submitted,
            RequestStatus.pending: FulfillmentStatus.awaiting_submission,
            RequestStatus.sent_to_arr: FulfillmentStatus.submitted,
            RequestStatus.partially_available: FulfillmentStatus.partially_available,
            RequestStatus.available: FulfillmentStatus.completed,
            RequestStatus.failed: FulfillmentStatus.failed,
            RequestStatus.rejected: FulfillmentStatus.removed,
        }
        normalized = RequestStatus(value) if isinstance(value, str) else value
        if normalized in compatibility:
            self.fulfillment_status = compatibility[normalized]
            self.fulfillment_updated_at = now_utc_naive()
        return value


class SeriesAcquisitionBatch(Base):
    """Vague d'acquisition d'une serie, independante des futurs emails agreges."""

    __tablename__ = "series_acquisition_batches"
    __table_args__ = (
        Index("ix_series_acquisition_batch_lookup", "arr_instance_id", "arr_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("media_requests.id", ondelete="SET NULL"), index=True
    )
    arr_instance_id: Mapped[int] = mapped_column(
        ForeignKey("arr_instances.id", ondelete="CASCADE"), index=True
    )
    arr_id: Mapped[int] = mapped_column(index=True)
    source: Mapped[Optional[str]]
    # all_seasons : API/RSS, monitored_seasons : autres points d'entree.
    expected_scope: Mapped[str] = mapped_column(default="monitored_seasons")
    expected_seasons: Mapped[Optional[str]] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(default="open", index=True)
    opened_at: Mapped[datetime] = mapped_column(default=now_utc_naive)
    last_sonarr_activity_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    last_plex_change_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    stabilization_started_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    pending_events: Mapped[Optional[str]] = mapped_column(Text, default="[]")
    summary_queued_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    closed_at: Mapped[Optional[datetime]] = mapped_column(default=None)


class SonarrQueueObservation(Base):
    """Dernier etat durable d'un element de queue Sonarr observe chaque minute."""

    __tablename__ = "sonarr_queue_observations"
    __table_args__ = (
        UniqueConstraint("arr_instance_id", "queue_id", name="uq_sonarr_queue_observation"),
        Index("ix_sonarr_queue_observation_state", "state", "last_seen_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("series_acquisition_batches.id", ondelete="SET NULL"), index=True
    )
    request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("media_requests.id", ondelete="SET NULL"), index=True
    )
    arr_instance_id: Mapped[int] = mapped_column(
        ForeignKey("arr_instances.id", ondelete="CASCADE"), index=True
    )
    queue_id: Mapped[int]
    download_id: Mapped[Optional[str]] = mapped_column(index=True)
    arr_media_id: Mapped[Optional[int]] = mapped_column(index=True)
    season_number: Mapped[Optional[int]]
    episode_number: Mapped[Optional[int]]
    title: Mapped[Optional[str]]
    state: Mapped[str] = mapped_column(default="queued", index=True)
    progress: Mapped[float] = mapped_column(default=0.0)
    tracked_state: Mapped[Optional[str]]
    tracked_status: Mapped[Optional[str]]
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    status_messages: Mapped[Optional[str]] = mapped_column(Text)
    consecutive_blocked_checks: Mapped[int] = mapped_column(default=0)
    first_seen_at: Mapped[datetime] = mapped_column(default=now_utc_naive)
    last_seen_at: Mapped[datetime] = mapped_column(default=now_utc_naive)
    blocked_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    admin_alert_queued_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(default=None)


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

    created_at: Mapped[Optional[datetime]] = mapped_column(default=now_utc_naive)
    updated_at: Mapped[Optional[datetime]] = mapped_column(default=now_utc_naive)


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
    fr_is_default: Mapped[Optional[bool]] = mapped_column(default=None)
    checked_at: Mapped[Optional[datetime]]


class EpisodeAvailability(Base):
    """Cache de la disponibilité Sonarr (fichier présent + date de diffusion) par
    épisode, alimenté en arrière-plan par `services/episode_availability.py`.

    Même principe que `VfEpisodeStatus` mais pour la disponibilité brute plutôt que le
    VF : sans ce cache, la fiche détail devait interroger Sonarr en direct à chaque
    affichage (auparavant mitigé par un cache de 90s seulement, insuffisant pour un
    rendu "instantané" façon Seerr, qui ne fait jamais d'appel *arr live dans le chemin
    de la requête).
    """

    __tablename__ = "episode_availability"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", "season_number", "episode_number", name="uq_episode_availability"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_type: Mapped[str]
    source_id: Mapped[int]
    season_number: Mapped[int]
    episode_number: Mapped[int]
    has_file: Mapped[bool] = mapped_column(default=False)
    air_date_utc: Mapped[Optional[str]]
    checked_at: Mapped[Optional[datetime]]


class RequestSeasonStatus(Base):
    """Disponibilité brute (fichier présent ou non côté Sonarr) par saison d'une demande.

    Distinct de `VfEpisodeStatus` : celui-ci suit la présence d'une piste VF par épisode
    (scan Plex), celui-là suit simplement si Sonarr a un fichier pour l'épisode, saison
    par saison — alimenté directement par `seasons[]` dans la réponse Sonarr (déjà
    récupérée par ailleurs, aucun appel réseau supplémentaire). Permet d'afficher un
    détail par saison même sans VFF/Plex configuré, et sert de base aux jalons de
    notification "saison démarrée"/"saison complète" (voir notification_orchestrator).

    Une vraie FK vers MediaRequest est possible ici (contrairement à VfEpisodeStatus) car
    une saison n'appartient qu'à une seule demande.
    """

    __tablename__ = "request_season_status"
    __table_args__ = (
        UniqueConstraint("request_id", "season_number", name="uq_request_season"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("media_requests.id", ondelete="CASCADE"), index=True)
    season_number: Mapped[int]
    episodes_available_count: Mapped[int] = mapped_column(default=0)
    episodes_total_count: Mapped[int] = mapped_column(default=0)
    # "pending" | "partially_available" | "available"
    status: Mapped[str] = mapped_column(default="pending")
    updated_at: Mapped[Optional[datetime]] = mapped_column(default=now_utc_naive)


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
    cached_at: Mapped[datetime] = mapped_column(default=now_utc_naive)
