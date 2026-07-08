"""Add TMDB API key for the discovery catalog

Revision ID: 0042_tmdb_api_key
Revises: 0041_poll_interval_seconds
Create Date: 2026-07-08
"""

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0042_tmdb_api_key"
down_revision: Union[str, None] = "0041_poll_interval_seconds"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("tmdb_api_key", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("tmdb_api_key")
