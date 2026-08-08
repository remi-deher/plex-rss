"""drop notify_vf_anime (anime category removed app-wide)

Revision ID: 0098_drop_notify_vf_anime
Revises: 0097_deleted_media_blocked
Create Date: 2026-08-08
"""

import sqlalchemy as sa

from alembic import op

revision = "0098_drop_notify_vf_anime"
down_revision = "0097_deleted_media_blocked"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.drop_column("notify_vf_anime")


def downgrade() -> None:
    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.add_column(sa.Column("notify_vf_anime", sa.Boolean(), nullable=True, server_default=sa.false()))
