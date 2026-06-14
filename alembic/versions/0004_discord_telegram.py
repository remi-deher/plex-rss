"""add discord and telegram notification settings

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("discord_webhook_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("telegram_bot_token", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("telegram_chat_id", sa.String(), nullable=True))


def downgrade():
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("discord_webhook_url")
        batch_op.drop_column("telegram_bot_token")
        batch_op.drop_column("telegram_chat_id")
