"""add admin action logs

Revision ID: 0064_admin_action_logs
Revises: 0063_email_enabled
Create Date: 2026-07-12
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0064_admin_action_logs"
down_revision: Union[str, None] = "0063_email_enabled"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "admin_action_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_name", sa.String(), nullable=True),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("details", sa.Text(), nullable=True),
    )
    op.create_index("ix_admin_action_logs_created_at", "admin_action_logs", ["created_at"])
    op.create_index("ix_admin_action_logs_action", "admin_action_logs", ["action"])


def downgrade() -> None:
    op.drop_index("ix_admin_action_logs_action", table_name="admin_action_logs")
    op.drop_index("ix_admin_action_logs_created_at", table_name="admin_action_logs")
    op.drop_table("admin_action_logs")
