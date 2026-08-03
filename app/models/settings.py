"""Configuration globale de l'application (table singleton)."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..crypto import EncryptedText
from .base import Base

if TYPE_CHECKING:
    from .email_config import EmailBranding, EmailTemplate


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)

    # --- Plex ---
    plex_url: Mapped[Optional[str]]
    plex_token: Mapped[Optional[str]] = mapped_column(EncryptedText)
    plex_rss_url: Mapped[Optional[str]]
    live_activity_enabled: Mapped[bool] = mapped_column(default=True)
    activity_retention_days: Mapped[Optional[int]] = mapped_column(default=365)
    activity_anonymize_ips: Mapped[bool] = mapped_column(default=True)
    tautulli_enabled: Mapped[bool] = mapped_column(default=False)
    tautulli_url: Mapped[Optional[str]]
    tautulli_api_key: Mapped[Optional[str]] = mapped_column(EncryptedText)
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

    # --- Email ---
    # Le "comment" (serveur/methode/identifiants) vit desormais dans EmailProvider
    # (plusieurs fournisseurs possibles, avec ordre de repli) ; Settings ne garde que
    # l'interrupteur global et l'adresse d'expedition, utilisee comme identite
    # d'expedition commune a tous les fournisseurs et comme adresse de repli affichee
    # ailleurs dans l'app (apercus d'email, destinataire par defaut, etc.).
    email_enabled: Mapped[bool] = mapped_column(default=True)
    smtp_from: Mapped[Optional[str]]
    admin_notification_email: Mapped[Optional[str]]
    email_on_request: Mapped[bool] = mapped_column(default=True)
    email_on_available: Mapped[bool] = mapped_column(default=True)
    email_on_failure: Mapped[bool] = mapped_column(default=True)
    # Alerte admin distincte d'un echec de transmission : un import Sonarr reste bloque
    # (fichier telecharge mais non importable). Frequent avec les episodes "TBA" -- bascule
    # dediee pour pouvoir la couper sans desactiver les vraies alertes d'echec de transmission.
    notify_import_blocked: Mapped[bool] = mapped_column(default=True)
    email_branding: Mapped[Optional["EmailBranding"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", uselist=False
    )
    email_templates: Mapped[list["EmailTemplate"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )

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
    # Région ISO 3166-1 utilisée pour les sorties et fournisseurs de streaming.
    tmdb_region: Mapped[str] = mapped_column(default="FR")

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

    # --- Retention RGPD (donnees personnelles / journaux) ---
    # Tentatives de connexion = adresses IP (donnee personnelle) : rétention BORNÉE par
    # défaut (90 j), contrairement aux autres retentions à None=indéfini — conserver des IP
    # sans limite n'est justifiable ni par la finalité anti-abus, ni par le principe de
    # minimisation (Art. 5-1-e). 0/None = conservation indéfinie (déconseillé).
    login_attempt_retention_days: Mapped[Optional[int]] = mapped_column(default=90)
    # Journaux d'audit & diagnostic (admin_action_logs, diagnostic_events, job_run_logs).
    # None = conservation indéfinie (trace d'imputabilité), configurable pour les purger.
    audit_log_retention_days: Mapped[Optional[int]] = mapped_column(default=None)

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

    # --- RGPD / confidentialite (page /privacy) ---
    # Identite du responsable de traitement -- sans ca, les sections "droits" et "base
    # legale" de la page de confidentialite n'ont personne a qui s'adresser concretement.
    gdpr_contact_name: Mapped[Optional[str]] = mapped_column(default=None)
    gdpr_contact_email: Mapped[Optional[str]] = mapped_column(default=None)

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


# Façade temporaire de compatibilité : l'API et les services gardent leurs noms
# `email_<...>` pendant que la persistance est désormais normalisée. Elle évite une
# migration simultanée de tous les appelants et pourra être retirée séparément.
_EMAIL_BRANDING_FIELDS = {
    "email_header_brand": "header_brand",
    "email_header_subtitle": "header_subtitle",
    "email_footer_template": "footer_template",
    "email_templates_backup": "templates_backup",
    "email_show_poster": "show_poster",
    "email_show_genres": "show_genres",
    "email_show_requester": "show_requester",
    "email_requester_label": "requester_label",
    "email_brand_color": "brand_color",
    "email_show_header_subtitle": "show_header_subtitle",
    "email_poster_width": "poster_width",
    "email_media_layout": "media_layout",
    "email_bg_color": "bg_color",
    "email_card_bg_color": "card_bg_color",
    "email_font_family": "font_family",
    "email_card_width": "card_width",
    "email_card_border_radius": "card_border_radius",
    "email_synopsis_font_size": "synopsis_font_size",
    "email_show_tmdb_link": "show_tmdb_link",
    "email_show_plex_button": "show_plex_button",
}
_EMAIL_EVENTS = (
    "request", "available", "upgrade", "failure", "correction",
    "episode_available", "season_started", "season_partial",
    "season_complete", "series_partial", "series_complete",
)


def _branding_property(field):
    def get(self):
        return getattr(self.email_branding, field, None)

    def set_(self, value):
        if self.email_branding is None:
            from .email_config import EmailBranding
            self.email_branding = EmailBranding()
        setattr(self.email_branding, field, value)

    return property(get, set_)


def _template_property(event, field):
    def row(self, create=False):
        found = next((item for item in self.email_templates if item.event == event), None)
        if found is None and create:
            from .email_config import EmailTemplate
            found = EmailTemplate(event=event)
            self.email_templates.append(found)
        return found

    def get(self):
        found = row(self)
        return getattr(found, field, None) if found else None

    def set_(self, value):
        setattr(row(self, create=True), field, value)

    return property(get, set_)


for _legacy_name, _field in _EMAIL_BRANDING_FIELDS.items():
    setattr(Settings, _legacy_name, _branding_property(_field))
for _event in _EMAIL_EVENTS:
    setattr(Settings, f"email_{_event}_template", _template_property(_event, "template"))
    setattr(Settings, f"email_{_event}_subject", _template_property(_event, "subject"))
for _event in ("request", "available", "upgrade", "failure", "correction"):
    for _field in ("accent_color", "badge_text", "headline_text", "show_synopsis"):
        setattr(Settings, f"email_{_event}_{_field}", _template_property(_event, _field))
