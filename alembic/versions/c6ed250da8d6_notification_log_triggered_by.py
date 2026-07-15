"""Ajout de notification_logs.triggered_by (auto|manual)

Revision ID: c6ed250da8d6
Revises: c1f8a3e5d9b2
Create Date: 2026-07-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c6ed250da8d6"
down_revision: Union[str, None] = "c1f8a3e5d9b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notification_logs",
        sa.Column("triggered_by", sa.String(), nullable=False, server_default="auto"),
    )


def downgrade() -> None:
    op.drop_column("notification_logs", "triggered_by")
