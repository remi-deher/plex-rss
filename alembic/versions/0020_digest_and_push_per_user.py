"""add digest settings and per-user push/digest flags

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-15
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("digest_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("digest_hour", sa.Integer(), nullable=False, server_default="8"))

    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.add_column(sa.Column("notify_digest", sa.Boolean(), nullable=True, server_default=sa.false()))
        batch_op.add_column(sa.Column("discord_webhook_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("telegram_chat_id", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("digest_hour")
        batch_op.drop_column("digest_enabled")

    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.drop_column("telegram_chat_id")
        batch_op.drop_column("discord_webhook_url")
        batch_op.drop_column("notify_digest")
