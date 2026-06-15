"""add req_id to notification_logs for resend support

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-15
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("notification_logs") as batch_op:
        batch_op.add_column(sa.Column("req_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("notification_logs") as batch_op:
        batch_op.drop_column("req_id")
