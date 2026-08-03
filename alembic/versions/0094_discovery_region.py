"""Ajoute la région utilisée par le catalogue TMDB.

Revision ID: 0094_discovery_region
Revises: 0093_playback_big_integers
"""

import sqlalchemy as sa

from alembic import op

revision = "0094_discovery_region"
down_revision = "0093_playback_big_integers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("tmdb_region", sa.String(), nullable=False, server_default="FR"),
    )


def downgrade() -> None:
    op.drop_column("settings", "tmdb_region")
