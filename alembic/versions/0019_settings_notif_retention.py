"""add notification_log_retention_days to settings

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-15
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("notification_log_retention_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("notification_log_retention_days")
