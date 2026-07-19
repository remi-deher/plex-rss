"""Add language-independent episode/season tracking mode

Revision ID: 0040_episode_tracking_mode
Revises: 0039_email_templates_backup
Create Date: 2026-07-07
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0040_episode_tracking_mode"
down_revision: Union[str, None] = "0039_email_templates_backup"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("series_tracking_mode", sa.String(), nullable=False, server_default="language"))
        batch_op.add_column(
            sa.Column(
                "series_episode_notify_mode", sa.String(), nullable=False, server_default="season_start_and_complete"
            )
        )
    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.add_column(sa.Column("series_tracking_mode", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("series_episode_notify_mode", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.drop_column("series_episode_notify_mode")
        batch_op.drop_column("series_tracking_mode")
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("series_episode_notify_mode")
        batch_op.drop_column("series_tracking_mode")
