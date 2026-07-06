"""vf_episode_status: cache par épisode du statut VF

Persiste le statut VF (True/False) de chaque épisode déjà scanné, pour éviter
de re-interroger Plex pour les épisodes déjà confirmés VF à chaque cycle de
re-scan (scheduler VFF ou modale "détail VF").

Revision ID: 0032
Revises: 0031
Create Date: 2026-07-06 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vf_episode_status",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("season_number", sa.Integer(), nullable=False),
        sa.Column("episode_number", sa.Integer(), nullable=False),
        sa.Column("has_vf", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_type", "source_id", "season_number", "episode_number", name="uq_vf_episode"
        ),
    )
    op.create_index(
        "ix_vf_episode_status_source", "vf_episode_status", ["source_type", "source_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_vf_episode_status_source", table_name="vf_episode_status")
    op.drop_table("vf_episode_status")
