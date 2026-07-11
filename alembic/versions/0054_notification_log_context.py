"""notification structured milestone context

Revision ID: 0054_notification_log_context
Revises: 0053_notification_perf_indexes
Create Date: 2026-07-11
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0054_notification_log_context"
down_revision: Union[str, None] = "0053_notification_perf_indexes"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("notification_logs") as batch_op:
        batch_op.add_column(sa.Column("scope", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("language", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("is_upgrade", sa.Boolean(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("season_number", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("episode_number", sa.Integer(), nullable=True))

    with op.batch_alter_table("notification_milestones") as batch_op:
        batch_op.add_column(sa.Column("language", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("is_upgrade", sa.Boolean(), nullable=False, server_default="0"))

    op.execute("UPDATE notification_milestones SET language = NULL WHERE direction = 'simple'")
    op.execute("UPDATE notification_milestones SET language = direction WHERE direction IN ('vo', 'vf')")
    op.execute("UPDATE notification_milestones SET is_upgrade = 1 WHERE direction = 'vf'")


def downgrade() -> None:
    with op.batch_alter_table("notification_milestones") as batch_op:
        batch_op.drop_column("is_upgrade")
        batch_op.drop_column("language")

    with op.batch_alter_table("notification_logs") as batch_op:
        batch_op.drop_column("episode_number")
        batch_op.drop_column("season_number")
        batch_op.drop_column("is_upgrade")
        batch_op.drop_column("language")
        batch_op.drop_column("scope")
