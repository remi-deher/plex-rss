"""Persiste le dernier snapshot des insights médiathèque."""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0088_library_analytics_snapshot"
down_revision: Union[str, None] = "0087_tautulli_engagement"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "library_analytics_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("library_analytics_snapshots")
