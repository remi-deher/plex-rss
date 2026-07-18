"""Ajoute settings.plex_recent_sync_last_at : filigrane persiste du dernier scan Plex
incremental reussi (job "plex-sync-recent"), pour survivre a un redemarrage du worker.

Revision ID: 0068_plex_recent_sync
Revises: 0067_plex_sync_hour
Create Date: 2026-07-19

"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0068_plex_recent_sync"
down_revision: Union[str, None] = "0067_plex_sync_hour"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column("settings", sa.Column("plex_recent_sync_last_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("settings", "plex_recent_sync_last_at")
