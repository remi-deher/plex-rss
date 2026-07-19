"""user roles and Plex SSO login fields

Revision ID: 0045_user_roles
Revises: 0044_pending_notifications
Create Date: 2026-07-09
"""

from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0045_user_roles"
down_revision: Union[str, None] = "0044_pending_notifications"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.add_column(sa.Column("role", sa.String(), nullable=False, server_default="user"))
        batch_op.add_column(sa.Column("can_login", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("plex_account_uuid", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("avatar_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("last_login_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("auto_approve", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("plex_users") as batch_op:
        batch_op.drop_column("auto_approve")
        batch_op.drop_column("last_login_at")
        batch_op.drop_column("avatar_url")
        batch_op.drop_column("plex_account_uuid")
        batch_op.drop_column("can_login")
        batch_op.drop_column("role")
