"""Base declarative et enumerations metier partagees par tous les modeles."""

import enum

from sqlalchemy.orm import DeclarativeBase


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

class VfCategory(str, enum.Enum):
    """Type de média du point de vue VFF, pour cibler les notifications.

    - movie  : film (bibliothèque de type « movie »)
    - series : série classique
    """

    movie = "movie"
    series = "series"
