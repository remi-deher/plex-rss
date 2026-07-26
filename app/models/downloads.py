"""Acquisitions : historique, vagues d'episodes et observation des files *arr."""

from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..utils import now_utc_naive
from .base import Base


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

class RadarrQueueObservation(Base):
    """Dernier etat durable d'un element de queue Radarr observe chaque minute.

    Un film est un item unique (pas de vague multi-episodes comme les series) : pas de
    SeriesAcquisitionBatch associe, l'alerte "import bloque" part directement d'ici une
    fois le blocage confirme (voir services/radarr_queue_monitor.py).
    """

    __tablename__ = "radarr_queue_observations"
    __table_args__ = (
        UniqueConstraint("arr_instance_id", "queue_id", name="uq_radarr_queue_observation"),
        Index("ix_radarr_queue_observation_state", "state", "last_seen_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("media_requests.id", ondelete="SET NULL"), index=True
    )
    arr_instance_id: Mapped[int] = mapped_column(
        ForeignKey("arr_instances.id", ondelete="CASCADE"), index=True
    )
    queue_id: Mapped[int]
    arr_media_id: Mapped[Optional[int]] = mapped_column(index=True)
    title: Mapped[Optional[str]]
    state: Mapped[str] = mapped_column(default="queued", index=True)
    progress: Mapped[float] = mapped_column(default=0.0)
    tracked_state: Mapped[Optional[str]]
    tracked_status: Mapped[Optional[str]]
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    consecutive_blocked_checks: Mapped[int] = mapped_column(default=0)
    first_seen_at: Mapped[datetime] = mapped_column(default=now_utc_naive)
    last_seen_at: Mapped[datetime] = mapped_column(default=now_utc_naive)
    blocked_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    admin_alert_queued_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(default=None)
