"""add notify_on_request and notify_on_available per user

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-15
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.add_column(sa.Column("notify_on_request", sa.Boolean(), nullable=True, server_default=sa.true()))
        batch_op.add_column(sa.Column("notify_on_available", sa.Boolean(), nullable=True, server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.drop_column("notify_on_available")
        batch_op.drop_column("notify_on_request")
