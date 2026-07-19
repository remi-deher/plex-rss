"""Add sub-minute watchlist poll interval (poll_interval_seconds)

Revision ID: 0041_poll_interval_seconds
Revises: 0040_episode_tracking_mode
Create Date: 2026-07-08
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0041_poll_interval_seconds"
down_revision: Union[str, None] = "0040_episode_tracking_mode"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("poll_interval_seconds", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("poll_interval_seconds")
