"""notification event filters

Revision ID: 0043_notification_event_filters
Revises: 0042_tmdb_api_key
Create Date: 2026-07-09
"""

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0043_notification_event_filters"
down_revision: Union[str, None] = "0042_tmdb_api_key"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("email_on_failure", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("discord_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("discord_send_request", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("discord_send_available", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("discord_send_failure", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("telegram_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("telegram_send_request", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("telegram_send_available", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("telegram_send_failure", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("ntfy_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("ntfy_send_request", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("ntfy_send_available", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("ntfy_send_failure", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("gotify_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("gotify_send_request", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("gotify_send_available", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("gotify_send_failure", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("gotify_send_failure")
        batch_op.drop_column("gotify_send_available")
        batch_op.drop_column("gotify_send_request")
        batch_op.drop_column("gotify_enabled")
        batch_op.drop_column("ntfy_send_failure")
        batch_op.drop_column("ntfy_send_available")
        batch_op.drop_column("ntfy_send_request")
        batch_op.drop_column("ntfy_enabled")
        batch_op.drop_column("telegram_send_failure")
        batch_op.drop_column("telegram_send_available")
        batch_op.drop_column("telegram_send_request")
        batch_op.drop_column("telegram_enabled")
        batch_op.drop_column("discord_send_failure")
        batch_op.drop_column("discord_send_available")
        batch_op.drop_column("discord_send_request")
        batch_op.drop_column("discord_enabled")
        batch_op.drop_column("email_on_failure")
