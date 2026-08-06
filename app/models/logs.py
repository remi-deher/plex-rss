"""Journaux d'exploitation : audit, diagnostics, suppressions, executions de taches."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..utils import now_utc_naive
from .base import Base


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
    # True quand la demande annulée provenait de la watchlist Plex (voir
    # requests_api.withdraw_request) : au-delà du garde-fou "force l'approbation" que
    # confère toute entrée de ce journal, empêche aussi purement et simplement la
    # recréation automatique via watchlist_poller.is_blocked (l'API Plex ne permet pas de
    # retirer une entrée de la watchlist depuis le serveur).
    blocked: Mapped[bool] = mapped_column(default=False)

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

class PollHistory(Base):
    __tablename__ = "poll_history"
    __table_args__ = (
        Index("ix_poll_history_started_at", "started_at"),
        Index("ix_poll_history_job_started_at", "job", "started_at"),
    )
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
