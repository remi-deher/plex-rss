"""Persiste la suspension globale des notifications."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0074_notification_hold"
down_revision: Union[str, None] = "0073_availability_torrent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("notification_hold_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("settings", "notification_hold_enabled")
