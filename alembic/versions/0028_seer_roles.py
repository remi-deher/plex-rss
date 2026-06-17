"""seer: separate send_requests and fallback_arr roles

Revision ID: 0028
Revises: 0027
Create Date: 2026-06-17 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "d0a28c3c1303"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("seer_send_requests", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "settings",
        sa.Column("seer_fallback_arr", sa.Boolean(), nullable=False, server_default="1"),
    )
    # Migrer seer_enabled existant vers seer_send_requests
    op.execute("UPDATE settings SET seer_send_requests = seer_enabled")


def downgrade() -> None:
    op.drop_column("settings", "seer_fallback_arr")
    op.drop_column("settings", "seer_send_requests")
