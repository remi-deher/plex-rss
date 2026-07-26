"""Conserve les métriques d'engagement natives de Tautulli."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0087_tautulli_engagement"
down_revision: Union[str, None] = "0086_playback_analytics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("playback_sessions") as batch_op:
        batch_op.add_column(sa.Column("progress_percent", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("watched_status", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("group_count", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("source_group_ids", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("playback_sessions") as batch_op:
        batch_op.drop_column("source_group_ids")
        batch_op.drop_column("group_count")
        batch_op.drop_column("watched_status")
        batch_op.drop_column("progress_percent")
