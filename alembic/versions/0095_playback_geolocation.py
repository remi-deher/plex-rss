"""Ajoute la geolocalisation approximative des lectures Plex.

Revision ID: 0095_playback_geolocation
Revises: 0094_discovery_region
"""

import sqlalchemy as sa

from alembic import op

revision = "0095_playback_geolocation"
down_revision = "0094_discovery_region"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("playback_sessions") as batch_op:
        batch_op.add_column(sa.Column("geo_status", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("geo_city", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("geo_region", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("geo_country", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("geo_country_code", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("geo_lat", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("geo_lon", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("playback_sessions") as batch_op:
        batch_op.drop_column("geo_lon")
        batch_op.drop_column("geo_lat")
        batch_op.drop_column("geo_country_code")
        batch_op.drop_column("geo_country")
        batch_op.drop_column("geo_region")
        batch_op.drop_column("geo_city")
        batch_op.drop_column("geo_status")
