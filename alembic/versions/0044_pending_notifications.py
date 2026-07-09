"""pending notifications (persisted notification queue)

Revision ID: 0044_pending_notifications
Revises: 0043_notification_event_filters
Create Date: 2026-07-09
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0044_pending_notifications"
down_revision: Union[str, None] = "0043_notification_event_filters"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "pending_notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("req_id", sa.Integer(), nullable=False),
        sa.Column("recipients", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("pending_notifications")
