"""Disponibilité partielle pour les séries en cours de diffusion

Une série pouvait passer en statut "available" dès qu'un seul épisode avait un
fichier (Sonarr episodeFileCount > 0), même si la série est encore en cours de
diffusion. Ajoute le suivi des compteurs d'épisodes (disponibles / diffusés /
total) pour distinguer une disponibilité partielle d'une disponibilité complète,
et les réglages de fréquence de notification associés (global + par utilisateur).

Revision ID: 0034
Revises: 0033
Create Date: 2026-07-06 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("media_requests", sa.Column("episodes_available_count", sa.Integer(), nullable=True))
    op.add_column("media_requests", sa.Column("episodes_aired_count", sa.Integer(), nullable=True))
    op.add_column("media_requests", sa.Column("episodes_total_count", sa.Integer(), nullable=True))
    op.add_column(
        "media_requests",
        sa.Column("partial_available_mail_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("media_requests", sa.Column("last_notified_episode_count", sa.Integer(), nullable=True))

    op.add_column(
        "settings",
        sa.Column("partial_notify_frequency", sa.String(), nullable=False, server_default="milestones"),
    )
    op.add_column("plex_users", sa.Column("partial_notify_frequency", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("plex_users", "partial_notify_frequency")
    op.drop_column("settings", "partial_notify_frequency")
    op.drop_column("media_requests", "last_notified_episode_count")
    op.drop_column("media_requests", "partial_available_mail_sent")
    op.drop_column("media_requests", "episodes_total_count")
    op.drop_column("media_requests", "episodes_aired_count")
    op.drop_column("media_requests", "episodes_available_count")
