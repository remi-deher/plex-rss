"""Ajoute le cache persistant des localisations par IP.

Revision ID: 0096_playback_ip_locations
Revises: 0095_playback_geolocation
"""

import sqlalchemy as sa

from alembic import op

revision = "0096_playback_ip_locations"
down_revision = "0095_playback_geolocation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playback_ip_locations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("address_hash", sa.String(), nullable=False),
        sa.Column("geo_status", sa.String(), nullable=False),
        sa.Column("geo_city", sa.String(), nullable=True),
        sa.Column("geo_region", sa.String(), nullable=True),
        sa.Column("geo_country", sa.String(), nullable=True),
        sa.Column("geo_country_code", sa.String(), nullable=True),
        sa.Column("geo_lat", sa.Float(), nullable=True),
        sa.Column("geo_lon", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_playback_ip_locations_address_hash",
        "playback_ip_locations",
        ["address_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_playback_ip_locations_address_hash",
        table_name="playback_ip_locations",
    )
    op.drop_table("playback_ip_locations")
