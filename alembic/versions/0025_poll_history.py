"""create poll_history table and add poll_history_retention_days to settings

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-17
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0025"
down_revision: str = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create poll_history table
    op.create_table(
        "poll_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("items_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("newly_available", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_detail", sa.String(), nullable=True),
    )

    # 2. Add poll_history_retention_days to settings
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("poll_history_retention_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    # Drop column from settings
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("poll_history_retention_days")

    # Drop table
    op.drop_table("poll_history")
