"""Admin notification email + per-user notify_admin toggle

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-14

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("settings", sa.Column("admin_notification_email", sa.String(), nullable=True))
    op.add_column("plex_users", sa.Column("notify_admin", sa.Boolean(), nullable=False, server_default="1"))


def downgrade() -> None:
    op.drop_column("settings", "admin_notification_email")
    op.drop_column("plex_users", "notify_admin")
