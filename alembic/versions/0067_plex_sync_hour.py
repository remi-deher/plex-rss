"""Ajoute settings.plex_sync_hour : heure murale configurable pour le job de
synchronisation complete de la bibliotheque Plex (auparavant fige a 03h15 UTC, sans
conversion CET/CEST -- voir job_plex_sync dans app/jobs.py).

Revision ID: 0067_plex_sync_hour
Revises: 0066_episode_availability
Create Date: 2026-07-19

"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0067_plex_sync_hour"
down_revision: Union[str, None] = "0066_episode_availability"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column("settings", sa.Column("plex_sync_hour", sa.Integer(), nullable=False, server_default="3"))


def downgrade() -> None:
    op.drop_column("settings", "plex_sync_hour")
