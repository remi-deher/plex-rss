"""episode_availability: cache Sonarr (fichier + date de diffusion) par episode

Persiste la disponibilite Sonarr de chaque episode, alimentee en arriere-plan, pour
eviter un appel Sonarr en direct a chaque affichage de la fiche detail (meme principe
que vf_episode_status pour le VF).

Revision ID: 0066_episode_availability
Revises: 0065_deleted_media_log
Create Date: 2026-07-18

"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0066_episode_availability"
down_revision: Union[str, None] = "0065_deleted_media_log"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "episode_availability",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("season_number", sa.Integer(), nullable=False),
        sa.Column("episode_number", sa.Integer(), nullable=False),
        sa.Column("has_file", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("air_date_utc", sa.String(), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_type", "source_id", "season_number", "episode_number", name="uq_episode_availability"),
    )
    op.create_index("ix_episode_availability_source", "episode_availability", ["source_type", "source_id"])


def downgrade() -> None:
    op.drop_index("ix_episode_availability_source", table_name="episode_availability")
    op.drop_table("episode_availability")
