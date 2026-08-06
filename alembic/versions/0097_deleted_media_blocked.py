"""add blocked flag to deleted media log

Revision ID: 0097_deleted_media_blocked
Revises: 0096_playback_ip_locations
Create Date: 2026-08-06
"""

import sqlalchemy as sa

from alembic import op

revision = "0097_deleted_media_blocked"
down_revision = "0096_playback_ip_locations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("deleted_media_log") as batch_op:
        batch_op.add_column(sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("deleted_media_log") as batch_op:
        batch_op.drop_column("blocked")
