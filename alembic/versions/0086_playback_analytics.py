"""Enrichit les sessions pour les statistiques de qualité et de stockage."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0086_playback_analytics"
down_revision: Union[str, None] = "0085_playback_activity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("playback_sessions") as batch_op:
        batch_op.add_column(sa.Column("container", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("subtitle_decision", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("stream_location", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("media_size_bytes", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("playback_sessions") as batch_op:
        batch_op.drop_column("media_size_bytes")
        batch_op.drop_column("stream_location")
        batch_op.drop_column("subtitle_decision")
        batch_op.drop_column("container")
