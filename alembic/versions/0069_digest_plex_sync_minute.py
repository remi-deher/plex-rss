"""Ajoute settings.digest_minute et settings.plex_sync_minute : precision minute pour
les reglages "heure murale" digest_hour/plex_sync_hour, qui n'exprimaient jusqu'ici
qu'une heure pleine (0-23).

Revision ID: 0069_digest_plex_sync_minute
Revises: 0068_plex_recent_sync
Create Date: 2026-07-19

"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0069_digest_plex_sync_minute"
down_revision: Union[str, None] = "0068_plex_recent_sync"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column("settings", sa.Column("digest_minute", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("settings", sa.Column("plex_sync_minute", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("settings", "plex_sync_minute")
    op.drop_column("settings", "digest_minute")
