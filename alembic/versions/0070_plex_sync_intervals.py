"""Remplace settings.plex_sync_hour/plex_sync_minute (heure murale fixe) par des
intervalles periodiques : plex_sync_interval_hours (scan complet) et
plex_sync_recent_interval_minutes (scan incremental, jusqu'ici fige a 5 min en dur).

Revision ID: 0070_plex_sync_intervals
Revises: 0069_digest_plex_sync_minute
Create Date: 2026-07-20

"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0070_plex_sync_intervals"
down_revision: Union[str, None] = "0069_digest_plex_sync_minute"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column("settings", sa.Column("plex_sync_interval_hours", sa.Integer(), nullable=False, server_default="24"))
    op.add_column(
        "settings", sa.Column("plex_sync_recent_interval_minutes", sa.Integer(), nullable=False, server_default="5")
    )
    op.drop_column("settings", "plex_sync_hour")
    op.drop_column("settings", "plex_sync_minute")


def downgrade() -> None:
    op.add_column("settings", sa.Column("plex_sync_hour", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("settings", sa.Column("plex_sync_minute", sa.Integer(), nullable=False, server_default="0"))
    op.drop_column("settings", "plex_sync_recent_interval_minutes")
    op.drop_column("settings", "plex_sync_interval_hours")
