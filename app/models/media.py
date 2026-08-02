"""Demandes de medias, bibliotheque Plex et suivi VF par saison/episode."""

from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint, desc, text
from sqlalchemy.orm import Mapped, mapped_column, validates

from ..utils import now_utc_naive
from .base import Base, FulfillmentStatus, RequestStatus


class MediaRequest(Base):
    __tablename__ = "media_requests"
    __table_args__ = (
        Index("ix_media_requests_requested_id", "requested_at", "id"),
        Index("ix_media_requests_status_requested", "status", "requested_at"),
        Index("ix_media_requests_type_status", "media_type", "status"),
        Index("ix_media_requests_arr_identity", "arr_instance_id", "arr_id"),
        Index(
            "ix_media_requests_next_release_at",
            "next_release_at",
            postgresql_where=text("next_release_at IS NOT NULL"),
            sqlite_where=text("next_release_at IS NOT NULL"),
        ),
    )

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

class LibraryItem(Base):
    """Média réellement présent dans la bibliothèque Plex (issu de la synchronisation).

    Séparé de `MediaRequest` : un élément de bibliothèque n'a pas de demandeur ni de
    flux de demande — il est simplement *présent*. Porte l'état VF/VFF du média.
    Le rapprochement avec les demandes se fait à l'affichage (vue Bibliothèque = union).
    """

    __tablename__ = "library_items"
    __table_args__ = (
        Index("ix_library_items_added_id", desc("added_at"), "title", "id"),
        Index("ix_library_items_arr_identity", "arr_instance_id", "arr_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str]
    year: Mapped[Optional[int]]
    media_type: Mapped[str] = mapped_column(index=True)

    # Rapprochement demande <-> media Plex (plex_sync._find_library_item_by_ids) : sans
    # index, chaque lookup scanne la table entiere (le seul filtre disponible avant ces
    # colonnes est l'id auto-increment, inutile ici).
    tmdb_id: Mapped[Optional[str]] = mapped_column(index=True)
    tvdb_id: Mapped[Optional[str]] = mapped_column(index=True)
    imdb_id: Mapped[Optional[str]] = mapped_column(index=True)
    plex_guid: Mapped[Optional[str]] = mapped_column(index=True)

    poster_url: Mapped[Optional[str]]
    overview: Mapped[Optional[str]] = mapped_column(Text)
    added_at: Mapped[Optional[datetime]]

    # Rapprochement Sonarr / Radarr (badges de suivi)
    arr_instance_id: Mapped[Optional[int]] = mapped_column(index=True)
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
